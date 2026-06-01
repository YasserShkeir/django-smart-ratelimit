"""Regression tests for the bugs found by the v4.0.3 deep code review.

Each test here fails on the pre-fix code and passes after. They guard the HIGH +
security fixes shipped in v4.0.3:

* get_tenant_key: authenticated tenant wins over a spoofable ?tenant_id / header.
* IPList: IPv4-mapped IPv6 (``::ffff:1.2.3.4``) matches an IPv4 entry.
* CircuitBreakerError: the exported class catches what the decorator raises.
* allow/deny lists: a malformed inline CIDR fails fast at config time (no silent
  fail-open), and middleware/DRF parse the list once (not per request).
* MongoDB fixed_window enforces even with ALIGN_WINDOW_TO_CLOCK=False.
* DRF throttle honors a declared bucket ``algorithm`` instead of always
  window-counting.
* Sync token/leaky bucket 429s carry rate-limit headers.
* Redis fixed_window 429s carry X-RateLimit-Reset / Retry-After.
"""

import time

import pytest

from django.http import HttpResponse
from django.test import override_settings

from django_smart_ratelimit import CircuitBreakerError, circuit_breaker, rate_limit
from django_smart_ratelimit.enums import Algorithm
from django_smart_ratelimit.key_functions import get_tenant_key
from django_smart_ratelimit.middleware import RateLimitMiddleware
from django_smart_ratelimit.policy.lists import IPList

from .conftest import (
    MONGODB,
    AuthedUser,
    exhaust,
    make_request,
    skip_without_mongo,
    skip_without_redis,
    use_backend,
)

# ---------------------------------------------------------------------------
# Security: tenant-key precedence
# ---------------------------------------------------------------------------


def test_tenant_key_prefers_authenticated_user_over_query_param():
    """An authenticated user's tenant must win over a spoofed ?tenant_id.

    Pre-fix, get_tenant_key read the query parameter first, letting a user whose
    real tenant is ``A`` rate-limit as tenant ``B`` (cross-tenant bucket
    poisoning + self-bypass by varying the value).
    """
    user = AuthedUser(1)
    user.tenant_id = "A"
    key = get_tenant_key(
        make_request(ip="203.0.113.7", user=user, params={"tenant_id": "B"})
    )
    assert "tenant:A" in key
    assert "tenant:B" not in key


def test_tenant_key_uses_query_param_only_when_unauthenticated():
    """With no authenticated tenant, the query parameter is still honored."""
    key = get_tenant_key(make_request(ip="203.0.113.8", params={"tenant_id": "Z"}))
    assert "tenant:Z" in key


# ---------------------------------------------------------------------------
# Security: IPv4-mapped IPv6 list matching
# ---------------------------------------------------------------------------


def test_iplist_matches_ipv4_mapped_ipv6():
    """``::ffff:1.2.3.4`` must match an IPv4 list entry ``1.2.3.4``.

    Pre-fix, the mapped form slipped past a deny list keyed on the plain IPv4.
    """
    ips = IPList(["1.2.3.4", "10.0.0.0/8"])
    assert ips.contains("1.2.3.4")
    assert ips.contains("::ffff:1.2.3.4")
    assert ips.contains("::ffff:10.1.2.3")
    assert not ips.contains("::ffff:9.9.9.9")


# ---------------------------------------------------------------------------
# API contract: a single CircuitBreakerError
# ---------------------------------------------------------------------------


def test_exported_circuit_breaker_error_catches_what_decorator_raises():
    """``except CircuitBreakerError`` on the public export catches the open circuit.

    Pre-fix there were two unrelated classes named CircuitBreakerError -- the
    package exported one while the breaker raised another -- so the documented
    catch never fired.
    """

    @circuit_breaker(failure_threshold=1)
    def flaky():
        raise ValueError("boom")

    open_circuit_caught = False
    for _ in range(4):
        try:
            flaky()
        except ValueError:
            pass  # the underlying failure that trips the breaker
        except CircuitBreakerError:
            open_circuit_caught = True
            break
    assert open_circuit_caught


# ---------------------------------------------------------------------------
# Security: allow/deny list parsing (fail-fast + parse-once)
# ---------------------------------------------------------------------------


def test_malformed_inline_deny_list_fails_fast():
    """A malformed inline CIDR must fail fast at middleware construction.

    Pre-fix it was swallowed per request, silently disabling the deny list
    (failing open) instead of surfacing the misconfiguration.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "100/m",
            "DENY_LIST": ["203.0.113.0/24", "10.0.0.0/33"],  # /33 is invalid
        }
    ):
        with pytest.raises(Exception):
            RateLimitMiddleware(lambda request: HttpResponse("ok"))


def test_middleware_parses_policy_lists_once():
    """Middleware stores a parsed IPList built once at init.

    It must not keep the raw value to re-parse / re-fetch on every request.
    """
    with override_settings(
        RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "100/m", "DENY_LIST": ["203.0.113.0/24"]}
    ):
        middleware = RateLimitMiddleware(lambda request: HttpResponse("ok"))
        assert isinstance(middleware.deny_list, IPList)


# ---------------------------------------------------------------------------
# Backends: MongoDB fixed_window enforces regardless of clock alignment
# ---------------------------------------------------------------------------


@skip_without_mongo
@pytest.mark.parametrize("align", [True, False])
def test_mongodb_fixed_window_enforces_with_any_alignment(align):
    """Fixed-window counting on MongoDB enforces under any clock alignment.

    Pre-fix, with ALIGN_WINDOW_TO_CLOCK=False the counter document was keyed on a
    per-request microsecond timestamp, so every request inserted a fresh count=1
    document and the limit was never enforced.
    """
    from pymongo import MongoClient

    MongoClient(host="localhost", port=27017).drop_database("ratelimit")
    with override_settings(
        RATELIMIT_BACKEND=MONGODB,
        RATELIMIT_MONGODB={
            "host": "localhost",
            "port": 27017,
            "database": "ratelimit",
            "algorithm": "fixed_window",
        },
        RATELIMIT_ALIGN_WINDOW_TO_CLOCK=align,
    ):
        from django_smart_ratelimit.backends import clear_backend_cache, get_backend

        clear_backend_cache()
        try:
            backend = get_backend()
            counts = [backend.incr("mongo-fw", 60) for _ in range(5)]
            assert counts == [1, 2, 3, 4, 5]
        finally:
            clear_backend_cache()
            MongoClient(host="localhost", port=27017).drop_database("ratelimit")


# ---------------------------------------------------------------------------
# Integrations: DRF throttle honors the declared algorithm
# ---------------------------------------------------------------------------


def test_drf_throttle_honors_token_bucket_algorithm():
    """A DRF throttle declaring algorithm='token_bucket' gets burst semantics.

    Pre-fix the throttle always called backend.incr (window counting) and
    ignored ``algorithm``; a bucket_size larger than the rate had no effect.
    """
    pytest.importorskip("rest_framework")
    from django_smart_ratelimit.integrations.drf import SmartRateLimitThrottle

    with use_backend("memory"):

        class BurstThrottle(SmartRateLimitThrottle):
            scope = None
            rate = "3/m"
            algorithm = "token_bucket"
            algorithm_config = {"bucket_size": 5, "refill_rate": 0}

            def get_cache_key(self, request, view):
                return "drf-regression:token-bucket"

        throttle = BurstThrottle()
        results = [
            throttle.allow_request(make_request(ip="203.0.113.9"), None)
            for _ in range(7)
        ]
        # bucket_size=5 admits 5 bursts; plain 3/m window would admit only 3.
        assert sum(bool(r) for r in results) == 5


# ---------------------------------------------------------------------------
# Integrations: bucket-limit 429s carry rate-limit headers
# ---------------------------------------------------------------------------


def test_sync_token_bucket_429_has_rate_limit_headers():
    """A sync token-bucket 429 carries machine-readable retry headers."""
    with use_backend("memory"):

        @rate_limit(
            key="ip",
            rate="3/m",
            algorithm=Algorithm.TOKEN_BUCKET,
            algorithm_config={"bucket_size": 3, "refill_rate": 0},
            block=True,
        )
        def view(_request):
            return HttpResponse("ok")

        exhaust(view, 5, ip="203.0.113.21")  # drain the 3-token bucket
        resp = view(make_request(ip="203.0.113.21"))
        assert resp.status_code == 429
        header_names = {k.lower() for k in resp.headers}
        assert "retry-after" in header_names
        assert any(name.startswith("x-ratelimit") for name in header_names)


# ---------------------------------------------------------------------------
# Backends: Redis fixed_window 429 carries reset/retry headers
# ---------------------------------------------------------------------------


@skip_without_redis
def test_redis_fixed_window_429_has_reset_header():
    """A Redis fixed_window 429 carries X-RateLimit-Reset / Retry-After.

    Pre-fix, get_reset_time() read the bare key while the counter lived under a
    clock-aligned suffixed key, so the 429 carried no retry guidance at all.
    """
    import redis as redis_module

    redis_module.Redis(host="localhost", port=6379, db=0).flushdb()
    with use_backend("redis"):
        with override_settings(RATELIMIT_ALGORITHM="fixed_window"):
            from django_smart_ratelimit.backends import clear_backend_cache

            clear_backend_cache()

            @rate_limit(
                key="ip", rate="2/m", algorithm=Algorithm.FIXED_WINDOW, block=True
            )
            def view(_request):
                return HttpResponse("ok")

            exhaust(view, 2, ip="203.0.113.31")
            resp = view(make_request(ip="203.0.113.31"))
            assert resp.status_code == 429
            reset = resp.headers.get("X-RateLimit-Reset")
            assert reset is not None
            assert int(reset) > int(time.time())
