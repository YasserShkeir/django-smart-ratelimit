"""Expanded tests for performance module."""

from unittest.mock import patch

from django.http import HttpRequest
from django.test import TestCase

from django_smart_ratelimit import RateLimitCache
from django_smart_ratelimit.performance import PerformanceMonitor, RateLimitOptimizer


class RateLimitCacheTests(TestCase):
    """Tests for RateLimitCache class."""

    def setUp(self):
        """Set up test fixtures."""
        self.cache = RateLimitCache()

    def test_initialization(self):
        """Test cache initialization."""
        self.assertEqual(self.cache.cache_prefix, "rl_cache")
        self.assertEqual(self.cache.default_timeout, 300)

    def test_custom_initialization(self):
        """Test cache initialization with custom parameters."""
        cache = RateLimitCache(cache_prefix="custom", default_timeout=600)
        self.assertEqual(cache.cache_prefix, "custom")
        self.assertEqual(cache.default_timeout, 600)

    def test_make_cache_key(self):
        """Test cache key generation."""
        key = self.cache._make_cache_key("test_key")
        self.assertEqual(key, "rl_cache:test_key")

    def test_make_cache_key_with_operation(self):
        """Test cache key generation with operation."""
        key = self.cache._make_cache_key("test_key", "info")
        self.assertEqual(key, "rl_cache:info:test_key")

    @patch("django_smart_ratelimit.performance.cache")
    def test_get_rate_limit_info(self, mock_cache):
        """Test get rate limit info."""
        mock_cache.get.return_value = {"limit": 100, "remaining": 50}
        info = self.cache.get_rate_limit_info("test_key")

        mock_cache.get.assert_called_once_with("rl_cache:info:test_key")
        self.assertEqual(info, {"limit": 100, "remaining": 50})

    @patch("django_smart_ratelimit.performance.cache")
    def test_set_rate_limit_info(self, mock_cache):
        """Test set rate limit info."""
        info = {"limit": 100, "remaining": 50}
        self.cache.set_rate_limit_info("test_key", info)

        mock_cache.set.assert_called_once_with("rl_cache:info:test_key", info, 300)

    @patch("django_smart_ratelimit.performance.cache")
    def test_invalidate_rate_limit_info(self, mock_cache):
        """Test invalidating cached rate limit info."""
        self.cache.invalidate_rate_limit_info("test_key")
        mock_cache.delete.assert_called_once_with("rl_cache:info:test_key")

    @patch("django_smart_ratelimit.performance.cache")
    def test_backend_health_cache(self, mock_cache):
        """Test backend health get/set caching."""
        self.cache.set_backend_health("redis", True, timeout=42)
        mock_cache.set.assert_called_once_with("rl_cache:health:redis", True, 42)

        mock_cache.get.return_value = True
        is_healthy = self.cache.get_backend_health("redis")
        mock_cache.get.assert_called_once_with("rl_cache:health:redis")
        self.assertTrue(is_healthy)

    @patch("django_smart_ratelimit.performance.cache")
    def test_batch_invalidate(self, mock_cache):
        """Test batch invalidation of multiple keys."""
        self.cache.batch_invalidate(["k1", "k2"])
        mock_cache.delete_many.assert_called_once_with(
            ["rl_cache:info:k1", "rl_cache:info:k2"]
        )


class PerformanceMonitorTests(TestCase):
    """Tests for PerformanceMonitor timing and metrics."""

    def test_time_operation_and_metrics(self):
        monitor = PerformanceMonitor()
        with monitor.time_operation("op1"):
            # Simulate work
            pass

        metrics = monitor.get_metrics("op1")
        self.assertEqual(metrics["count"], 1)
        self.assertGreaterEqual(metrics["avg_time"], 0.0)

        summary = monitor.get_performance_summary()
        self.assertIn("total_operations", summary)
        self.assertEqual(summary["total_operations"], 1)
        self.assertEqual(summary["operations"], ["op1"])

        monitor.reset_metrics()
        self.assertEqual(monitor.get_metrics(), {})


class RateLimitOptimizerTests(TestCase):
    """Tests for RateLimitOptimizer key generation optimization."""

    @patch("django_smart_ratelimit.performance.cache")
    def test_optimize_key_generation_uses_cache(self, mock_cache):
        optimizer = RateLimitOptimizer()

        def original_key_func(request: HttpRequest) -> str:
            return f"{request.method}:{request.path}"

        optimized = optimizer.optimize_key_generation(
            original_key_func, cache_timeout=5
        )

        # Build minimal request
        req = HttpRequest()
        req.method = "GET"
        req.path = "/api/test/"
        req.META["REMOTE_ADDR"] = "127.0.0.1"
        req.user = type("U", (), {"is_authenticated": False})()

        # First call should set cache
        mock_cache.get.return_value = None
        result1 = optimized(req)
        self.assertEqual(result1, "GET:/api/test/")
        self.assertTrue(mock_cache.set.called)

        # Second call should hit cache
        mock_cache.get.reset_mock()
        mock_cache.set.reset_mock()
        mock_cache.get.return_value = "GET:/api/test/"
        result2 = optimized(req)
        self.assertEqual(result2, "GET:/api/test/")
        mock_cache.get.assert_called_once()
        mock_cache.set.assert_not_called()
