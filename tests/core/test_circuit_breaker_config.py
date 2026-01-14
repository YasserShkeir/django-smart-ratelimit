"""Tests for circuit breaker configuration."""

import unittest

from django.test import TestCase

from django_smart_ratelimit.circuit_breaker import CircuitBreaker, CircuitBreakerConfig


class CircuitBreakerConfigTests(TestCase):
    """Tests for circuit breaker configuration."""

    def test_config_backend(self):
        """Test that CircuitBreakerConfig correctly stores the backend configuration."""
        config = CircuitBreakerConfig(state_backend="redis")
        assert config.state_backend == "redis"

        cb = CircuitBreaker(config, redis_client="mock_redis")
        assert cb._redis_client == "mock_redis"


if __name__ == "__main__":
    pass

    import django
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            DATABASES={
                "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
            },
            INSTALLED_APPS=["django_smart_ratelimit"],
        )
        django.setup()

    unittest.main()
