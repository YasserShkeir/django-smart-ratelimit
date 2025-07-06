#!/usr/bin/env python
"""Integration test for multi-backend functionality.

This is a standalone test to verify multi-backend works in real scenarios.
"""

import os
import sys

import django
from django.conf import settings

# Add the project directory to Python path
sys.path.insert(0, "/Users/yassershkeir/Documents/GitHub/django-ratelimit")

# Configure Django settings for testing
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
django.setup()

from django_smart_ratelimit.backends import get_backend  # noqa: E402
from django_smart_ratelimit.backends.multi import MultiBackend  # noqa: E402


def test_multi_backend_integration() -> None:
    """Test multi-backend integration with real backends."""
    # Test with multi-backend configuration
    test_settings = {
        "RATELIMIT_BACKENDS": [
            {
                "name": "memory1",
                "backend": "django_smart_ratelimit.backends.memory.MemoryBackend",
                "config": {},
            },
            {
                "name": "memory2",
                "backend": "django_smart_ratelimit.backends.memory.MemoryBackend",
                "config": {},
            },
        ],
        "RATELIMIT_MULTI_BACKEND_STRATEGY": "first_healthy",
        "RATELIMIT_HEALTH_CHECK_INTERVAL": 30,
    }

    # Temporarily modify settings
    original_backends = getattr(settings, "RATELIMIT_BACKENDS", None)
    original_strategy = getattr(settings, "RATELIMIT_MULTI_BACKEND_STRATEGY", None)
    original_interval = getattr(settings, "RATELIMIT_HEALTH_CHECK_INTERVAL", None)

    try:
        # Set test settings
        settings.RATELIMIT_BACKENDS = test_settings["RATELIMIT_BACKENDS"]
        settings.RATELIMIT_MULTI_BACKEND_STRATEGY = test_settings[
            "RATELIMIT_MULTI_BACKEND_STRATEGY"
        ]
        settings.RATELIMIT_HEALTH_CHECK_INTERVAL = test_settings[
            "RATELIMIT_HEALTH_CHECK_INTERVAL"
        ]

        # Get multi-backend
        backend = get_backend()

        # Verify it's a MultiBackend
        assert isinstance(
            backend, MultiBackend
        ), f"Expected MultiBackend, got {type(backend)}"

        # Test basic operations
        key = "test_integration_key"

        # Test incr
        count = backend.incr(key, 60)
        assert count == 1, f"Expected count 1, got {count}"

        # Test get_count
        count = backend.get_count(key)
        assert count == 1, f"Expected count 1, got {count}"

        # Test get_reset_time
        reset_time = backend.get_reset_time(key)
        assert reset_time is not None, "Expected reset time, got None"

        # Test backend status
        status = backend.get_backend_status()
        assert "memory1" in status, "Expected memory1 in status"
        assert "memory2" in status, "Expected memory2 in status"
        assert status["memory1"]["healthy"], "Expected memory1 to be healthy"
        assert status["memory2"]["healthy"], "Expected memory2 to be healthy"

        # Test stats
        stats = backend.get_stats()
        assert (
            stats["total_backends"] == 2
        ), f"Expected 2 backends, got {stats['total_backends']}"
        assert (
            stats["healthy_backends"] == 2
        ), f"Expected 2 healthy backends, got {stats['healthy_backends']}"
        assert (
            stats["fallback_strategy"] == "first_healthy"
        ), f"Expected first_healthy strategy, got {stats['fallback_strategy']}"

        # Test reset
        backend.reset(key)
        count = backend.get_count(key)
        assert count == 0, f"Expected count 0 after reset, got {count}"

        print("✅ Multi-backend integration test passed!")

    finally:
        # Restore original settings
        if original_backends is not None:
            settings.RATELIMIT_BACKENDS = original_backends
        elif hasattr(settings, "RATELIMIT_BACKENDS"):
            delattr(settings, "RATELIMIT_BACKENDS")

        if original_strategy is not None:
            settings.RATELIMIT_MULTI_BACKEND_STRATEGY = original_strategy
        elif hasattr(settings, "RATELIMIT_MULTI_BACKEND_STRATEGY"):
            delattr(settings, "RATELIMIT_MULTI_BACKEND_STRATEGY")

        if original_interval is not None:
            settings.RATELIMIT_HEALTH_CHECK_INTERVAL = original_interval
        elif hasattr(settings, "RATELIMIT_HEALTH_CHECK_INTERVAL"):
            delattr(settings, "RATELIMIT_HEALTH_CHECK_INTERVAL")


if __name__ == "__main__":
    test_multi_backend_integration()
    print("🎉 All integration tests passed!")
