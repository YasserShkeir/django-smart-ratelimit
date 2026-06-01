"""Real-backend end-to-end concurrency tests.

Fire many requests at a single rate-limited key SIMULTANEOUSLY against a REAL
store and assert EXACT admission -- no over-count (the failure that lets extra
traffic through) and no under-count. This proves the atomic check-and-increment
contract of the enforcement primitives under genuine contention, which is the
one property a single-threaded or mock-based test can never demonstrate.

Only backends whose increment is atomic are asserted exactly:

* ``memory``      -- guarded by an in-process lock,
* ``redis``       -- atomic server-side Lua (sliding window and token bucket),
* ``async_redis`` -- the same Lua, driven concurrently via ``asyncio.gather``.

MongoDB standalone has no atomic sliding-window increment (it would need a
replica set), so it is intentionally excluded from exact-admission assertions
rather than asserted with a fudge factor that would hide real over-admission.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from django.http import HttpResponse

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.enums import Algorithm

from .conftest import make_request, skip_without_redis, use_backend

# Backends with an atomic sync increment -> exact admission is a hard guarantee.
_ATOMIC_SYNC = [
    pytest.param("memory", id="memory"),
    pytest.param("redis", id="redis", marks=skip_without_redis),
]

_CONCURRENCY = 50
_WORKERS = 16


def _drive_sync(view, n, ip):
    """Fire ``n`` requests from the same IP concurrently; return status codes."""

    def hit(_):
        return view(make_request(ip=ip)).status_code

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        return list(pool.map(hit, range(n)))


@pytest.mark.parametrize("backend_name", _ATOMIC_SYNC)
def test_concurrent_sliding_window_admits_exactly_the_limit(backend_name):
    """50 simultaneous requests at 10/min -> exactly 10 pass, 40 are blocked.

    A non-atomic check-then-increment would let several racing requests all read
    "9 used" and admit together (over-admission). Asserting an exact split proves
    the real store enforces the limit atomically under contention.
    """
    with use_backend(backend_name):

        @rate_limit(key="ip", rate="10/m")
        def view(_request):
            return HttpResponse("ok")

        codes = _drive_sync(view, _CONCURRENCY, ip="100.64.0.1")
        assert codes.count(200) == 10
        assert codes.count(429) == _CONCURRENCY - 10


@pytest.mark.parametrize("backend_name", _ATOMIC_SYNC)
def test_concurrent_token_bucket_admits_exactly_bucket_size(backend_name):
    """50 simultaneous requests drain a 10-token bucket to exactly 10 allowed.

    bucket_size=10, refill_rate=0 (no refill during the test). The native token
    bucket (memory lock / Redis Lua) must hand out each token to exactly one
    racing request.
    """
    with use_backend(backend_name):

        @rate_limit(
            key="ip",
            rate="100/m",
            algorithm=Algorithm.TOKEN_BUCKET,
            algorithm_config={"bucket_size": 10, "refill_rate": 0},
        )
        def view(_request):
            return HttpResponse("ok")

        codes = _drive_sync(view, _CONCURRENCY, ip="100.64.0.2")
        assert codes.count(200) == 10
        assert codes.count(429) == _CONCURRENCY - 10


@pytest.mark.parametrize("backend_name", _ATOMIC_SYNC)
def test_concurrent_independent_keys_do_not_interfere(backend_name):
    """Two IPs hammering concurrently each get their own full budget.

    Interleaved traffic on key A must not consume key B's allowance; each IP
    sees exactly its 10 admissions.
    """
    with use_backend(backend_name):

        @rate_limit(key="ip", rate="10/m")
        def view(_request):
            return HttpResponse("ok")

        def hit(i):
            ip = "100.64.1.1" if i % 2 == 0 else "100.64.1.2"
            return ip, view(make_request(ip=ip)).status_code

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            results = list(pool.map(hit, range(80)))

        for ip in ("100.64.1.1", "100.64.1.2"):
            allowed = sum(1 for got_ip, code in results if got_ip == ip and code == 200)
            assert allowed == 10, f"{ip} admitted {allowed}, expected 10"


@skip_without_redis
async def test_concurrent_async_redis_admits_exactly_the_limit():
    """40 coroutines awaited together on async Redis -> exactly 10 admitted.

    Exercises the async enforcement path (``@rate_limit`` on an ``async def``
    view, async Redis backend) under real ``asyncio`` concurrency. A warm-up call
    on a separate key primes the Lua script cache so the burst measures admission,
    not first-use script reloads.
    """
    with use_backend("async_redis"):

        @rate_limit(key="ip", rate="10/m")
        async def view(_request):
            return HttpResponse("ok")

        async def hit(ip):
            result = view(make_request(ip=ip))
            if asyncio.iscoroutine(result):
                result = await result
            return result.status_code

        # Warm the script cache (distinct key, does not affect the measured IP).
        await hit("100.64.2.254")

        ip = "100.64.2.3"
        codes = await asyncio.gather(*[hit(ip) for _ in range(40)])
        assert codes.count(200) == 10
        assert codes.count(429) == 30
