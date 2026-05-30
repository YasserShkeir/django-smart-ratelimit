"""Live-Redis regression: token bucket with refill_rate=0 (never refill).

The native Redis Lua script used to compute the key expiration as
``bucket_size / refill_rate``, which is ``inf`` when refill_rate=0 and made
Redis raise "value is not an integer or out of range" on EXPIRE. The token
bucket then silently fell back to window counting. These tests run against a
real Redis (the mock-based unit tests cannot exercise the Lua script).
"""

import pytest

from django.test import override_settings

from django_smart_ratelimit.backends import clear_backend_cache, get_backend


def _redis_available():
    try:
        import redis as _redis
    except ImportError:
        return False
    try:
        _redis.Redis(host="localhost", port=6379, db=0).ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_available(), reason="live Redis not available"
)


@override_settings(
    RATELIMIT_BACKEND="redis",
    RATELIMIT_REDIS={"host": "localhost", "port": 6379, "db": 0},
)
def test_redis_token_bucket_refill_rate_zero_native():
    clear_backend_cache()
    backend = get_backend()
    backend.redis.delete("ratelimit:rrtest:token_bucket")
    # bucket_size=3, refill_rate=0 -> exactly 3 allowed, then denied, with no
    # Lua error and no window fallback.
    results = [
        backend.token_bucket_check(
            "rrtest",
            bucket_size=3,
            refill_rate=0.0,
            initial_tokens=3,
            tokens_requested=1,
        )[0]
        for _ in range(4)
    ]
    assert results == [True, True, True, False], results
    clear_backend_cache()


@override_settings(
    RATELIMIT_BACKEND="redis",
    RATELIMIT_REDIS={"host": "localhost", "port": 6379, "db": 0},
)
def test_redis_token_bucket_info_refill_rate_zero():
    clear_backend_cache()
    backend = get_backend()
    backend.redis.delete("ratelimit:rrinfo:token_bucket")
    backend.token_bucket_check(
        "rrinfo", bucket_size=5, refill_rate=0.0, initial_tokens=5, tokens_requested=1
    )
    info = backend.token_bucket_info("rrinfo", bucket_size=5, refill_rate=0.0)
    # No inf/error; time_to_refill is a finite number.
    assert info["time_to_refill"] in (0, 0.0)
    clear_backend_cache()
