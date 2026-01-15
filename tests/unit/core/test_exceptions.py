from django_smart_ratelimit.exceptions import (
    BackendError,
    RateLimitExceeded,
)


def test_rate_limit_exceeded_attributes():
    exc = RateLimitExceeded("Too many requests", retry_after=60, key="user:123")

    assert str(exc) == "Too many requests"
    assert exc.retry_after == 60
    assert exc.key == "user:123"


def test_backend_error_preserves_original():
    original = ValueError("connection failed")
    exc = BackendError("Redis error", backend="redis", original_exception=original)

    assert exc.backend == "redis"
    assert exc.original_exception is original
