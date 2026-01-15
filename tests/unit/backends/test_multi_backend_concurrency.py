"""Tests for multi-backend concurrency."""

import itertools
import threading
from unittest.mock import MagicMock

from django.test import TestCase

from django_smart_ratelimit.backends.multi import MultiBackend


class MultiBackendConcurrencyTests(TestCase):
    """Tests for multi-backend concurrency."""

    def test_round_robin_thread_safety(self):
        """Test round-robin is thread-safe under concurrent access."""
        # Create 3 memory backends
        backends = [
            {
                "backend": "django_smart_ratelimit.backends.memory.MemoryBackend",
                "name": "b1",
            },
            {
                "backend": "django_smart_ratelimit.backends.memory.MemoryBackend",
                "name": "b2",
            },
            {
                "backend": "django_smart_ratelimit.backends.memory.MemoryBackend",
                "name": "b3",
            },
        ]

        multi = MultiBackend(
            backends=backends,
            fallback_strategy="round_robin",
            enable_circuit_breaker=False,
        )

        # We want to verify that backends are selected in round-robin fashion
        # even with concurrent access.
        # Since we can't easily check which backend was used internally without mocking,
        # we'll mock the backends in the multi instance.

        # Replace initialized backends with mocks
        mock_backends = []
        for i in range(3):
            mock = MagicMock()
            mock.get_count.return_value = 0
            mock_backends.append((f"b{i+1}", mock))

        multi.backends = mock_backends

        # Update thread-safe cycle with new backends
        multi._backend_cycle = itertools.cycle(multi.backends)
        multi._backend_health = {id(b): True for _, b in multi.backends}

        # Pre-warm health checks to avoid counting them in the test
        for name, mock in mock_backends:
            multi.health_checker.is_healthy(name, mock)
            mock.reset_mock()

        # Function to be run in threads
        def make_request():
            multi.get_count("key")

        threads = []
        for _ in range(30):
            t = threading.Thread(target=make_request)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Verify distribution
        # Each backend should have been called roughly 10 times
        counts = [mock.get_count.call_count for _, mock in mock_backends]
        print(f"Backend counts: {counts}")

        # In a perfect round-robin with 30 requests and 3 backends, each gets 10.
        # Since we advance index atomically, it should be exactly 10.
        for count in counts:
            self.assertEqual(count, 10)


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

    import unittest

    unittest.main()
