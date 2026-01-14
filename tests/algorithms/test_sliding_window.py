"""Tests for sliding window algorithm."""

import unittest

from django.test import TestCase

from django_smart_ratelimit.backends.utils import filter_sliding_window_requests


class SlidingWindowEdgeCaseTests(TestCase):
    """Tests for sliding window edge cases."""

    def test_floating_point_precision(self):
        """Test that floating point precision doesn't affect window calculation."""
        now = 100.0
        period = 60

        # Request exactly at the boundary (should be excluded)
        # Boundary is now - period = 40.0
        # If request was at 40.0, it is 60s old.
        # Sliding window is usually > cutoff.
        # So 40.0 > 40.0 is False. Excluded.

        requests = [(40.0, "id1")]
        filtered = filter_sliding_window_requests(requests, period, now)
        self.assertEqual(len(filtered), 0)

        # Request slightly after boundary (should be included)
        requests = [(40.002, "id2")]  # 2ms after
        filtered = filter_sliding_window_requests(requests, period, now)
        self.assertEqual(len(filtered), 1)

        # Request slightly before boundary (should be excluded)
        requests = [(39.998, "id3")]  # 2ms before
        filtered = filter_sliding_window_requests(requests, period, now)
        self.assertEqual(len(filtered), 0)

    def test_precision_edge_case(self):
        """Test with values that might cause float precision issues."""
        # 0.1 + 0.2 != 0.3 in float

        now = 0.3
        period = 0.1
        # cutoff = 0.2

        # Request at 0.2
        requests = [(0.2, "id1")]
        filtered = filter_sliding_window_requests(requests, period, now)
        self.assertEqual(len(filtered), 0)

        # Request at 0.201 (1ms after)
        requests = [(0.201, "id2")]
        filtered = filter_sliding_window_requests(requests, period, now)
        self.assertEqual(len(filtered), 1)


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
