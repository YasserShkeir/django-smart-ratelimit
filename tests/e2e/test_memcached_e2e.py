"""End-to-end tests for the Memcached backend against a live server.

No mocks: these drive the real `@rate_limit` decorator and `RateLimitMiddleware`
through a real Memcached instance. They skip when Memcached is unreachable. The
backend implements clock-aligned fixed-window counting, so the assertions here
are written for fixed-window semantics (a burst up to the limit, then blocking
until the window rolls over).
"""

import time

from django.http import HttpResponse
from django.test import override_settings

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import get_backend
from django_smart_ratelimit.middleware import RateLimitMiddleware

from .conftest import exhaust, make_request, skip_without_memcached, use_backend

pytestmark = skip_without_memcached


def _uid():
    return time.time_ns()


# ---------------------------------------------------------------------------
# Backend through the public get_backend() path
# ---------------------------------------------------------------------------


def test_get_backend_returns_memcached_and_counts():
    with use_backend("memcached"):
        backend = get_backend()
        assert backend.name == "memcached"
        key = f"e2e:{_uid()}"
        assert [backend.incr(key, 60) for _ in range(3)] == [1, 2, 3]
        assert backend.get_count(key, 60) == 3


# ---------------------------------------------------------------------------
# Decorator over a real Memcached
# ---------------------------------------------------------------------------


def test_decorator_allows_then_blocks_fixed_window():
    with use_backend("memcached"):

        @rate_limit(key="ip", rate="5/m", algorithm="fixed_window")
        def view(_request):
            return HttpResponse("ok")

        codes = exhaust(view, 7, ip=f"198.51.100.{_uid() % 200}")
        assert codes[:5] == [200] * 5
        assert codes[5:] == [429, 429]


def test_decorator_isolates_distinct_clients():
    with use_backend("memcached"):

        @rate_limit(key="ip", rate="2/m", algorithm="fixed_window")
        def view(_request):
            return HttpResponse("ok")

        a = exhaust(view, 3, ip="203.0.113.41")
        b = exhaust(view, 3, ip="203.0.113.42")
        assert a == [200, 200, 429]
        assert b == [200, 200, 429]  # independent bucket per IP


def test_window_rolls_over_and_allows_again():
    with use_backend("memcached"):

        @rate_limit(key="ip", rate="2/s", algorithm="fixed_window")
        def view(_request):
            return HttpResponse("ok")

        ip = "203.0.113.77"
        # Align to just after a 1s clock boundary so the burst lands entirely in
        # one window (clock-aligned fixed windows otherwise let a burst straddle
        # a boundary and admit more than the limit -- a timing flake on CI).
        time.sleep(1.0 - (time.time() % 1.0) + 0.05)
        first = exhaust(view, 3, ip=ip)
        assert first == [200, 200, 429]
        time.sleep(1.2)  # next clock-aligned 1s window
        assert exhaust(view, 1, ip=ip) == [200]


# ---------------------------------------------------------------------------
# Middleware over a real Memcached
# ---------------------------------------------------------------------------


@override_settings(
    RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "3/m", "BACKEND": "memcached"},
    RATELIMIT_ALGORITHM="fixed_window",
)
def test_middleware_enforces_default_rate():
    with use_backend("memcached"):
        mw = RateLimitMiddleware(lambda req: HttpResponse("ok"))
        codes = [
            mw(make_request(ip="203.0.113.90", path="/api/x")).status_code
            for _ in range(5)
        ]
        assert codes.count(200) == 3
        assert codes[-1] == 429


# ---------------------------------------------------------------------------
# Real-life scenarios
# ---------------------------------------------------------------------------


def test_scenario_login_brute_force_throttle():
    """A login endpoint capped at 5 attempts/min per IP blocks the 6th try."""
    with use_backend("memcached"):

        @rate_limit(key="ip", rate="5/m", algorithm="fixed_window", block=True)
        def login(_request):
            return HttpResponse("login form")

        attacker = "203.0.113.6"
        codes = exhaust(login, 8, ip=attacker)
        assert codes[:5] == [200] * 5
        assert all(c == 429 for c in codes[5:])
        # A different user from another IP is unaffected.
        assert exhaust(login, 1, ip="203.0.113.7") == [200]


def test_scenario_api_quota_per_api_key():
    """Per-API-key quota: each key gets its own budget via a header key."""
    with use_backend("memcached"):

        @rate_limit(
            key=lambda r, *a, **k: f"apikey:{r.headers.get('X-API-Key', 'anon')}",
            rate="4/m",
            algorithm="fixed_window",
        )
        def api(_request):
            return HttpResponse("data")

        def call(api_key):
            return api(make_request(headers={"X-API-Key": api_key})).status_code

        gold = [call("gold") for _ in range(5)]
        silver = [call("silver") for _ in range(2)]
        assert gold == [200, 200, 200, 200, 429]
        assert silver == [200, 200]  # separate key, separate quota


def test_scenario_burst_traffic_under_limit_all_allowed():
    """A burst that stays under the limit is fully served."""
    with use_backend("memcached"):

        @rate_limit(key="ip", rate="50/m", algorithm="fixed_window")
        def page(_request):
            return HttpResponse("ok")

        codes = exhaust(page, 40, ip="203.0.113.123")
        assert codes == [200] * 40


def test_scenario_fail_open_when_memcached_unreachable():
    """With fail_open, a dead Memcached lets traffic through (availability)."""
    with use_backend("memcached"):

        @rate_limit(
            key="ip",
            rate="1/m",
            algorithm="fixed_window",
            backend="django_smart_ratelimit.backends.memcached.MemcachedBackend",
        )
        def view(_request):
            return HttpResponse("ok")

        # Point the live backend instance at a dead port and enable fail_open.
        backend = get_backend()
        from pymemcache.client.base import Client

        backend._client = Client(("127.0.0.1", 1), connect_timeout=1, timeout=1)
        backend.fail_open = True
        # Both requests are allowed despite the backend being unreachable.
        codes = exhaust(view, 2, ip="203.0.113.200")
        assert codes == [200, 200]
