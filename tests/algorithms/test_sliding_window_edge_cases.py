"""Tests for sliding window edge cases."""

import time

from django.test import TestCase

from django_smart_ratelimit.backends.memory import MemoryBackend


class TestSlidingWindowEdgeCases(TestCase):
    """Tests for sliding window algorithm edge cases."""

    def test_sliding_window_exact_boundary(self):
        """Test behavior at exact window boundary."""
        backend = MemoryBackend()
        key = "test:boundary"
        period = 1  # Short period for testing
        limit = 5

        # Fill to limit
        for _ in range(limit):
            backend.incr(key, period=period)

        # Current count should be limit
        self.assertEqual(backend.get_count(key, period=period), limit)

        # Next increment should exceed limit
        count = backend.incr(key, period=period)
        self.assertGreater(count, limit)

        # Wait for window to expire
        time.sleep(period + 0.1)

        # Should be allowed again (count resets or slides out)
        self.assertEqual(backend.get_count(key, period=period), 0)

        # Increment should be 1
        count = backend.incr(key, period=period)
        self.assertEqual(count, 1)

    def test_sliding_window_partial_expiry(self):
        """Test that old requests slide out of window."""
        backend = MemoryBackend()
        key = "test:sliding"
        period = 2

        # Add requests over time
        backend.incr(key, period=period)  # T=0
        time.sleep(0.5)
        backend.incr(key, period=period)  # T=0.5
        time.sleep(0.5)
        backend.incr(key, period=period)  # T=1.0

        # Current count should be 3
        count = backend.get_count(key, period=period)
        self.assertEqual(count, 3)

        # Wait for first request to expire (expires at T=2.0)
        # We are at T=1.0. Sleep 1.1s -> T=2.1
        time.sleep(1.1)

        # Count should be reduced (Req 1 expired, Req 2 and 3 valid)
        count = backend.get_count(key, period=period)
        self.assertEqual(count, 2)
