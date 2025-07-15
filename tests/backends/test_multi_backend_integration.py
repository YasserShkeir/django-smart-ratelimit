"""Integration test for multi-backend functionality.

This test verifies multi-backend works in real scenarios using Django's unittest.
"""

from django.test import TestCase, override_settings

from django_smart_ratelimit.backends import get_backend
from django_smart_ratelimit.backends.multi import MultiBackend


class MultiBackendIntegrationTest(TestCase):
    """Test multi-backend integration with real backends."""

    @override_settings(
        RATELIMIT_BACKENDS=[
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
        RATELIMIT_MULTI_BACKEND_STRATEGY="first_healthy",
        RATELIMIT_HEALTH_CHECK_INTERVAL=30,
    )
    def test_multi_backend_integration(self):
        """Test multi-backend integration with real backends."""
        # Get multi-backend
        backend = get_backend()

        # Verify it's a MultiBackend
        self.assertIsInstance(
            backend, MultiBackend, f"Expected MultiBackend, got {type(backend)}"
        )

        # Test basic operations
        key = "test_integration_key"

        # Test incr
        count = backend.incr(key, 60)
        self.assertEqual(count, 1, f"Expected count 1, got {count}")

        # Test get_count
        count = backend.get_count(key)
        self.assertEqual(count, 1, f"Expected count 1, got {count}")

        # Test get_reset_time
        reset_time = backend.get_reset_time(key)
        self.assertIsNotNone(reset_time, "Expected reset time, got None")

        # Test backend status
        status = backend.get_backend_status()
        self.assertIn("memory1", status, "Expected memory1 in status")
        self.assertIn("memory2", status, "Expected memory2 in status")
        self.assertTrue(status["memory1"]["healthy"], "Expected memory1 to be healthy")
        self.assertTrue(status["memory2"]["healthy"], "Expected memory2 to be healthy")

        # Test stats
        stats = backend.get_stats()
        self.assertEqual(
            stats["total_backends"],
            2,
            f"Expected 2 backends, got {stats['total_backends']}",
        )
        self.assertEqual(
            stats["healthy_backends"],
            2,
            f"Expected 2 healthy backends, got {stats['healthy_backends']}",
        )
        self.assertEqual(
            stats["fallback_strategy"],
            "first_healthy",
            f"Expected first_healthy strategy, got {stats['fallback_strategy']}",
        )

        # Test reset
        backend.reset(key)
        count = backend.get_count(key)
        self.assertEqual(count, 0, f"Expected count 0 after reset, got {count}")
