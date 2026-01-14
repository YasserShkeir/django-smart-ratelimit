"""Configuration settings for the rate limit library."""

from typing import Any

from django.conf import settings

DEFAULTS = {
    "RATELIMIT_ENABLE": True,
    "RATELIMIT_BACKEND": "django_smart_ratelimit.backends.redis.RedisBackend",
    "RATELIMIT_FAIL_OPEN": False,
    "RATELIMIT_LOG_EXCEPTIONS": True,
    "RATELIMIT_EXCEPTION_HANDLER": None,
    "RATELIMIT_KEY_PREFIX": "ratelimit:",
    "RATELIMIT_ALGORITHM": "sliding_window",
    "RATELIMIT_REDIS": {},
    "RATELIMIT_MONGODB": {},
    "RATELIMIT_MIDDLEWARE": {},
    "RATELIMIT_BACKENDS": {},
    "RATELIMIT_MULTI_BACKENDS": [],
    "RATELIMIT_HEALTH_CHECK_INTERVAL": 30,
    "RATELIMIT_HEALTH_CHECK_TIMEOUT": 5,
    "RATELIMIT_BACKEND_CONFIG": {},
    "RATELIMIT_CIRCUIT_BREAKER": {},
    "RATELIMIT_MULTI_BACKEND_STRATEGY": "first_healthy",
}


class RateLimitConfig:
    """Central configuration access for Django Smart Ratelimit."""

    def __getattr__(self, name: str) -> Any:
        """Get setting value from Django settings or defaults."""
        if name in DEFAULTS:
            return getattr(settings, name, DEFAULTS[name])
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def is_set(self, name: str) -> bool:
        """Check if a setting is explicitly defined in Django settings."""
        return hasattr(settings, name)


config = RateLimitConfig()
