"""Real-backend end-to-end scenarios for ``RateLimitMiddleware``.

These tests drive the middleware exactly the way Django does in production: a
configured ``RATELIMIT_MIDDLEWARE`` dict, a real (non-mocked) storage backend,
and ``make_request()``-built requests fed through ``middleware(request)``. The
limiter always talks to real Redis / real MongoDB / real memory storage — only
the surrounding HTTP plumbing (RequestFactory + a fake ``get_response``) is
synthetic.

The headline scenario the suite encodes is a realistic site config:

    * site-wide default of 100/m,
    * a stricter ``/auth/`` bucket of 5/m to protect login,
    * ``/health/`` skipped entirely (load balancers must never be throttled),
    * an internal CIDR (``10.0.0.0/8``) allow-listed so office traffic bypasses,
    * a known abuser CIDR deny-listed and force-blocked,
    * and a shadow rollout where a brand-new limit only logs instead of blocking.

Each test selects its backend via the shared ``real_backend`` fixture (so the
behavior is verified on memory + redis + async_redis + mongodb) or, for the
async ``__acall__`` path, pins memory explicitly. Distinct client IPs per test
keep every scenario self-contained on the shared live stores.
"""

import time

import pytest

from django.http import HttpResponse, JsonResponse
from django.test import override_settings

from django_smart_ratelimit.middleware import RateLimitMiddleware

from .conftest import AuthedUser, exhaust, make_request

# ``real_backend`` is a pytest fixture from conftest.py; it is auto-discovered by
# name when used as a test parameter, so it needs no explicit import here.

# ---------------------------------------------------------------------------
# Fake downstream apps. A real Django middleware wraps ``get_response``; we
# stand in lightweight callables so the *only* thing under test is the limiter.
# ---------------------------------------------------------------------------


def ok_view(request):
    """Sync downstream that always returns 200 OK (an unthrottled handler)."""
    return HttpResponse("ok")


async def async_ok_view(request):
    """Async downstream returning 200 OK; triggers the middleware's __acall__."""
    return HttpResponse("ok")


def build(**middleware_config):
    """Build a RateLimitMiddleware with the given RATELIMIT_MIDDLEWARE dict.

    ``BACKEND`` is intentionally never injected so the middleware resolves the
    backend from ``RATELIMIT_BACKEND`` (which the ``real_backend`` /
    ``use_backend`` fixtures set to the live store under test).
    """
    return RateLimitMiddleware(ok_view)


# The production-like site config reused across the headline scenarios.
SITE_CONFIG = {
    "DEFAULT_RATE": "100/m",
    "BLOCK": True,
    "SKIP_PATHS": ["/admin/", "/health/"],
    "RATE_LIMITS": {
        "/api/": "1000/h",
        "/auth/": "5/m",
    },
}


# ---------------------------------------------------------------------------
# DEFAULT_RATE — the site-wide bucket.
# ---------------------------------------------------------------------------


def test_default_rate_blocks_after_limit_then_serves_headers(real_backend):
    """Site default 5/m: the 6th hit from one IP is blocked with 429+headers.

    A small explicit default keeps the scenario fast while still exercising the
    real incr-per-request path: five requests pass (200) and the sixth trips the
    limit (429), proving the middleware enforces DEFAULT_RATE against real
    storage.
    """
    with override_settings(RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "5/m", "BLOCK": True}):
        mw = build()
        codes = exhaust(mw, 6, ip="198.51.100.1")

    assert codes[:5] == [200, 200, 200, 200, 200]
    assert codes[5] == 429

    # A passing response carries the standard rate-limit headers.
    ok = mw(make_request(ip="198.51.100.2"))
    assert ok.status_code == 200
    assert ok.headers["X-RateLimit-Limit"] == "5"
    assert ok.headers["X-RateLimit-Remaining"] == "4"
    assert "X-RateLimit-Reset" in ok.headers


def test_default_rate_independent_buckets_per_ip(real_backend):
    """Default 3/m per IP: an attacker hammering one IP cannot affect another.

    The middleware keys on client IP, so two distinct REMOTE_ADDRs get two
    independent buckets — a real-life DoS from one source must not exhaust a
    legitimate user's allowance.
    """
    with override_settings(RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "3/m", "BLOCK": True}):
        mw = build()
        attacker = exhaust(mw, 5, ip="203.0.113.50")
        # Legitimate user from a different IP is untouched.
        victim = mw(make_request(ip="203.0.113.51"))

    assert attacker == [200, 200, 200, 429, 429]
    assert victim.status_code == 200
    assert victim.headers["X-RateLimit-Remaining"] == "2"


def test_429_response_has_retry_after_and_zero_remaining(real_backend):
    """A blocked request returns Retry-After and X-RateLimit-Remaining: 0.

    Operators and well-behaved clients rely on these headers to back off; assert
    the real 429 carries them.
    """
    with override_settings(RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "2/m", "BLOCK": True}):
        mw = build()
        codes = exhaust(mw, 3, ip="198.51.100.9")
        blocked = mw(make_request(ip="198.51.100.9"))

    assert codes == [200, 200, 429]
    assert blocked.status_code == 429
    assert blocked.headers["X-RateLimit-Limit"] == "2"
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) >= 0


# ---------------------------------------------------------------------------
# RATE_LIMITS — per-path overrides with isolated buckets.
# ---------------------------------------------------------------------------


def test_auth_path_stricter_than_default(real_backend):
    """/auth/ login is 5/m even though the site default is 100/m.

    An attacker credential-stuffing /auth/login/ from one IP is blocked after 5
    attempts, while the same IP can still browse the 100/m default site.
    """
    with override_settings(RATELIMIT_MIDDLEWARE=SITE_CONFIG):
        mw = build()
        login = exhaust(mw, 7, ip="198.51.100.20", path="/auth/login/")
        # Same IP, default-rate page: untouched by the /auth/ bucket.
        home = mw(make_request(ip="198.51.100.20", path="/"))

    assert login[:5] == [200, 200, 200, 200, 200]
    assert login[5] == 429 and login[6] == 429
    assert home.status_code == 200
    # The default page sees the 100/m limit, not 5/m.
    assert home.headers["X-RateLimit-Limit"] == "100"


def test_path_specific_buckets_are_isolated_from_each_other(real_backend):
    """/auth/ (5/m) and /api/ (1000/h) keep separate buckets for the same IP.

    Exhausting the strict /auth/ bucket leaves the generous /api/ bucket fully
    available — path-specific limits include the path in the key so they never
    cross-contaminate.
    """
    with override_settings(RATELIMIT_MIDDLEWARE=SITE_CONFIG):
        mw = build()
        auth = exhaust(mw, 6, ip="198.51.100.21", path="/auth/login/")
        api = mw(make_request(ip="198.51.100.21", path="/api/users/"))

    assert auth[5] == 429
    assert api.status_code == 200
    assert api.headers["X-RateLimit-Limit"] == "1000"
    assert api.headers["X-RateLimit-Remaining"] == "999"


def test_longest_prefix_first_match_wins(real_backend):
    """RATE_LIMITS matches by prefix; /api/ traffic uses the 1000/h bucket.

    A burst of API calls well under 1000/h all pass and report the API limit,
    confirming get_rate_for_path picks the configured /api/ rate rather than the
    site default.
    """
    with override_settings(RATELIMIT_MIDDLEWARE=SITE_CONFIG):
        mw = build()
        codes = exhaust(mw, 20, ip="198.51.100.22", path="/api/items/")
        sample = mw(make_request(ip="198.51.100.23", path="/api/items/"))

    assert codes == [200] * 20
    assert sample.headers["X-RateLimit-Limit"] == "1000"


# ---------------------------------------------------------------------------
# SKIP_PATHS — health checks and admin are never throttled.
# ---------------------------------------------------------------------------


def test_skip_paths_never_rate_limited(real_backend):
    """/health/ is skipped: a load balancer polling it is never throttled.

    Far more requests than any configured limit are issued to /health/ and all
    succeed with no rate-limit headers (the middleware returns before evaluating
    the limiter).
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "2/m",
            "BLOCK": True,
            "SKIP_PATHS": ["/health/", "/admin/"],
        }
    ):
        mw = build()
        health = exhaust(mw, 10, ip="198.51.100.30", path="/health/live")
        admin = mw(make_request(ip="198.51.100.30", path="/admin/login/"))
        # A non-skipped path from the same IP still enforces 2/m.
        normal = exhaust(mw, 3, ip="198.51.100.30", path="/dashboard/")

    assert health == [200] * 10
    assert "X-RateLimit-Limit" not in health and admin.status_code == 200
    # Skipped traffic did not consume the /dashboard/ bucket.
    assert normal == [200, 200, 429]


# ---------------------------------------------------------------------------
# ALLOW_LIST — internal CIDR bypasses rate limiting.
# ---------------------------------------------------------------------------


def test_allow_list_cidr_bypasses_limit(real_backend):
    """Internal 10.0.0.0/8 office range is allow-listed and bypasses 2/m.

    Requests from inside the allow-listed CIDR are never counted (and carry no
    rate-limit headers), while an outside IP is still capped at the default.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "2/m",
            "BLOCK": True,
            "ALLOW_LIST": ["10.0.0.0/8"],
        }
    ):
        mw = build()
        internal = exhaust(mw, 8, ip="10.4.5.6", path="/reports/")
        external = exhaust(mw, 3, ip="198.51.100.40", path="/reports/")

    assert internal == [200] * 8
    # Allow-listed bypass returns before headers are attached.
    last_internal = mw(make_request(ip="10.4.5.6", path="/reports/"))
    assert last_internal.status_code == 200
    assert "X-RateLimit-Limit" not in last_internal.headers
    # Outside the CIDR, the 2/m default still applies.
    assert external == [200, 200, 429]


# ---------------------------------------------------------------------------
# DENY_LIST — known abuser CIDR is force-blocked. Deny wins over allow.
# ---------------------------------------------------------------------------


def test_deny_list_force_blocks_immediately(real_backend):
    """A deny-listed abuser is 429'd on the very first request.

    No allowance is granted to deny-listed IPs — the first hit is blocked with a
    429 carrying zeroed rate-limit headers, while a clean IP sails through.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "100/m",
            "BLOCK": True,
            "DENY_LIST": ["192.0.2.0/24"],
        }
    ):
        mw = build()
        abuser = mw(make_request(ip="192.0.2.66", path="/"))
        clean = mw(make_request(ip="198.51.100.50", path="/"))

    assert abuser.status_code == 429
    assert abuser.headers["X-RateLimit-Limit"] == "0"
    assert abuser.headers["X-RateLimit-Remaining"] == "0"
    assert clean.status_code == 200


def test_deny_wins_over_allow_for_overlapping_ranges(real_backend):
    """When an IP is in both lists, deny takes precedence (fail-closed).

    A surgical deny entry inside a broadly allow-listed range is still blocked —
    the canonical "the office is trusted, but this one compromised host is not"
    scenario.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "100/m",
            "BLOCK": True,
            "ALLOW_LIST": ["10.0.0.0/8"],
            "DENY_LIST": ["10.9.9.9"],
        }
    ):
        mw = build()
        compromised = mw(make_request(ip="10.9.9.9", path="/"))
        trusted = mw(make_request(ip="10.1.2.3", path="/"))

    assert compromised.status_code == 429
    assert trusted.status_code == 200
    # Trusted (allow-listed) traffic bypasses, so it carries no limit headers.
    assert "X-RateLimit-Limit" not in trusted.headers


# ---------------------------------------------------------------------------
# BLOCK — when False, over-limit requests pass through (monitoring posture).
# ---------------------------------------------------------------------------


def test_block_false_lets_over_limit_requests_through(real_backend):
    """BLOCK=False: over-limit requests are NOT 429'd, they pass with 200.

    Some deployments want to measure traffic against a limit without rejecting
    anyone yet. With BLOCK=False the counter still increments (real storage) but
    the response stays 200 even past the limit.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "2/m", "BLOCK": False}
    ):
        mw = build()
        codes = exhaust(mw, 5, ip="198.51.100.60")

    assert codes == [200] * 5


def test_block_false_reports_zero_remaining_when_over(real_backend):
    """BLOCK=False still reflects exhaustion in X-RateLimit-Remaining.

    Operators reading headers see remaining clamp to 0 once the bucket is spent,
    even though the request was allowed through.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "2/m", "BLOCK": False}
    ):
        mw = build()
        exhaust(mw, 2, ip="198.51.100.61")
        over = mw(make_request(ip="198.51.100.61"))

    assert over.status_code == 200
    assert over.headers["X-RateLimit-Limit"] == "2"
    assert over.headers["X-RateLimit-Remaining"] == "0"


# ---------------------------------------------------------------------------
# SHADOW — a new limit logs would-be blocks but does not enforce them.
# ---------------------------------------------------------------------------


def test_shadow_mode_allows_but_logs_would_be_block(real_backend, caplog):
    """SHADOW rollout: over-limit requests are allowed but logged, not blocked.

    The standard "run the new limit in shadow for a day" workflow — exhaust the
    bucket, observe that nothing is 429'd, and confirm the structured
    SHADOW_RATE_LIMIT_BLOCK log line fired for the would-be block.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "2/m", "BLOCK": True, "SHADOW": True}
    ):
        mw = build()
        with caplog.at_level("INFO", logger="django_smart_ratelimit.pipeline"):
            codes = exhaust(mw, 4, ip="198.51.100.70")

    # Nothing blocked despite blowing past the 2/m limit.
    assert codes == [200] * 4
    shadow_logs = [
        r for r in caplog.records if r.getMessage() == "SHADOW_RATE_LIMIT_BLOCK"
    ]
    assert shadow_logs, "expected a shadow block log line for the over-limit request"
    assert getattr(shadow_logs[0], "event", None) == "ratelimit.shadow.block"


def test_shadow_mode_does_not_block_deny_list(real_backend, caplog):
    """SHADOW also downgrades a deny-list block to an allow-with-log.

    Before enforcing a freshly added deny list, operators run it in shadow: the
    deny-listed IP is allowed through but a shadow log line is emitted so they
    can confirm the list matches the right traffic.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "100/m",
            "BLOCK": True,
            "SHADOW": True,
            "DENY_LIST": ["192.0.2.0/24"],
        }
    ):
        mw = build()
        with caplog.at_level("INFO", logger="django_smart_ratelimit.pipeline"):
            resp = mw(make_request(ip="192.0.2.77", path="/"))

    assert resp.status_code == 200
    keys = [getattr(r, "key", None) for r in caplog.records]
    assert "deny_list" in keys


# ---------------------------------------------------------------------------
# KEY_FUNCTION — custom keying (per-user instead of per-IP).
# ---------------------------------------------------------------------------


def test_user_key_function_buckets_per_user(real_backend):
    """KEY_FUNCTION=user_key_function: two authed users share an IP but not a bucket.

    With the bundled user_key_function, the bucket is keyed on user id, so two
    logged-in users behind the same NAT'd office IP each get their own 3/m
    allowance instead of competing for one.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "3/m",
            "BLOCK": True,
            "KEY_FUNCTION": ("django_smart_ratelimit.middleware.user_key_function"),
        }
    ):
        mw = build()
        shared_ip = "198.51.100.80"
        user_a = AuthedUser(uid=9001)
        user_b = AuthedUser(uid=9002)
        a_codes = [
            mw(make_request(ip=shared_ip, user=user_a)).status_code for _ in range(4)
        ]
        b_first = mw(make_request(ip=shared_ip, user=user_b))

    assert a_codes == [200, 200, 200, 429]
    # Different user id => fresh bucket even on the same IP.
    assert b_first.status_code == 200


# ---------------------------------------------------------------------------
# Async path — the same enforcement via __acall__ on a real backend.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_call_enforces_limit(real_backend):
    """Async __acall__: an ASGI app's middleware blocks the 4th of a 3/m bucket.

    Driving the middleware with an async get_response exercises __acall__ and
    backend.aincr against real storage; behavior must match the sync path.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "3/m", "BLOCK": True, "SKIP_PATHS": []}
    ):
        mw = RateLimitMiddleware(async_ok_view)
        assert mw.async_mode
        codes = []
        for _ in range(4):
            resp = await mw(make_request(ip="198.51.100.90", path="/async/"))
            codes.append(resp.status_code)
        # A fresh IP still has its full allowance and reports headers.
        ok = await mw(make_request(ip="198.51.100.91", path="/async/"))

    assert codes == [200, 200, 200, 429]
    assert ok.status_code == 200
    assert ok.headers["X-RateLimit-Limit"] == "3"
    assert ok.headers["X-RateLimit-Remaining"] == "2"


@pytest.mark.asyncio
async def test_async_call_honors_skip_and_deny(real_backend):
    """Async __acall__ respects SKIP_PATHS and DENY_LIST just like the sync path.

    /health/ probes are never throttled and a deny-listed IP is 429'd on the
    first async request — proving the v3 policy pipeline runs in both call paths.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "1/m",
            "BLOCK": True,
            "SKIP_PATHS": ["/health/"],
            "DENY_LIST": ["192.0.2.0/24"],
        }
    ):
        mw = RateLimitMiddleware(async_ok_view)
        health_codes = []
        for _ in range(5):
            r = await mw(make_request(ip="198.51.100.92", path="/health/ready"))
            health_codes.append(r.status_code)
        denied = await mw(make_request(ip="192.0.2.88", path="/"))

    assert health_codes == [200] * 5
    assert denied.status_code == 429


# ---------------------------------------------------------------------------
# RATELIMIT_ENABLE — global kill switch short-circuits the middleware.
# ---------------------------------------------------------------------------


def test_global_disable_short_circuits_middleware(real_backend):
    """RATELIMIT_ENABLE=False disables all enforcement site-wide.

    The kill switch must let everything through even with an aggressive 1/m
    default — used for incident response when the limiter itself is suspect.
    """
    with override_settings(
        RATELIMIT_ENABLE=False,
        RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "1/m", "BLOCK": True},
    ):
        mw = build()
        codes = exhaust(mw, 5, ip="198.51.100.99")

    assert codes == [200] * 5


# ---------------------------------------------------------------------------
# Header semantics across consecutive allowed requests.
# ---------------------------------------------------------------------------


def test_remaining_header_counts_down(real_backend):
    """X-RateLimit-Remaining decrements on each allowed request.

    Clients implementing client-side backoff depend on a monotonically
    decreasing remaining counter; assert it walks 4 -> 3 -> 2 -> 1 -> 0 for a
    5/m bucket against real storage.
    """
    with override_settings(RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "5/m", "BLOCK": True}):
        mw = build()
        remaining = []
        for _ in range(5):
            resp = mw(make_request(ip="198.51.100.100"))
            remaining.append(int(resp.headers["X-RateLimit-Remaining"]))

    assert remaining == [4, 3, 2, 1, 0]


def test_does_not_clobber_existing_decorator_headers(real_backend):
    """Middleware respects stricter decorator-set headers already on the response.

    When a downstream view (simulating a @rate_limit decorator) has already set a
    tighter X-RateLimit-Limit, the lenient site default must not overwrite it
    with looser numbers.
    """

    def decorated_view(request):
        resp = JsonResponse({"ok": True})
        resp.headers["X-RateLimit-Limit"] = "5"
        resp.headers["X-RateLimit-Remaining"] = "1"
        return resp

    with override_settings(
        RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "1000/m", "BLOCK": True}
    ):
        mw = RateLimitMiddleware(decorated_view)
        resp = mw(make_request(ip="198.51.100.101"))

    assert resp.status_code == 200
    # The stricter decorator limit (5) survives the lenient 1000/m middleware.
    assert resp.headers["X-RateLimit-Limit"] == "5"
    assert resp.headers["X-RateLimit-Remaining"] == "1"


def test_reset_header_is_a_future_timestamp(real_backend):
    """X-RateLimit-Reset points to a future epoch second (now + period).

    Clients use Reset to know when the window clears; verify it is plausibly in
    the future for a 60s window.
    """
    before = int(time.time())
    with override_settings(
        RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "10/m", "BLOCK": True}
    ):
        mw = build()
        resp = mw(make_request(ip="198.51.100.102"))

    reset = int(resp.headers["X-RateLimit-Reset"])
    assert reset >= before
    assert reset <= int(time.time()) + 120
