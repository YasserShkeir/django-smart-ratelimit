"""Tests for performance module."""

import time

from django.test import TestCase

from django_smart_ratelimit.backends.memory import MemoryBackend
from django_smart_ratelimit.performance import RateLimitMetrics, get_memory_usage, timed


class TestPerformance(TestCase):
    """Tests for performance utilities."""

    def test_timing_decorator(self):
        """Test the timing decorator captures execution time."""

        @timed
        def slow_function():
            time.sleep(0.01)
            return "done"

        result = slow_function()

        assert result == "done"
        # We can't easily check the log output without capturing logs,
        # but we verified the function runs and returns.

    def test_metrics_collection(self):
        """Test metrics are collected properly."""
        metrics = RateLimitMetrics()

        metrics.record_request("key1", allowed=True, duration=0.01)
        metrics.record_request("key1", allowed=False, duration=0.02)

        stats = metrics.get_stats("key1")

        assert stats["total_requests"] == 2
        assert stats["allowed_requests"] == 1
        assert stats["denied_requests"] == 1
        assert abs(stats["total_duration"] - 0.03) < 0.001

    def test_memory_usage_tracking(self):
        """Test memory usage tracking for backends."""
        backend = MemoryBackend()

        # Add some data
        for i in range(100):
            backend.incr(f"key:{i}", period=60)

        memory = get_memory_usage(backend)

        assert memory > 0


class TestMetricsCollector(TestCase):
    """Tests for the new MetricsCollector singleton."""

    def test_singleton_nature(self):
        from django_smart_ratelimit.performance import MetricsCollector, get_metrics

        m1 = get_metrics()
        m2 = get_metrics()
        m3 = MetricsCollector()

        self.assertIs(m1, m2)
        self.assertIs(m1, m3)

    def test_record_request(self):
        from django_smart_ratelimit.performance import get_metrics

        metrics = get_metrics()
        metrics.reset()

        metrics.record_request("k1", True, 10.5, "memory")
        metrics.record_request("k1", False, 5.0, "memory")
        metrics.record_request("k2", True, 2.0, "redis")

        stats = metrics.get_stats()
        self.assertEqual(stats["total_requests"], 3)
        self.assertEqual(stats["allowed_requests"], 2)
        self.assertEqual(stats["denied_requests"], 1)
        self.assertEqual(stats["unique_keys"], 2)

        # Check internal storage history
        self.assertEqual(len(metrics._metrics["k1"]), 2)
        self.assertEqual(metrics._metrics["k1"][0].duration_ms, 10.5)
