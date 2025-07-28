"""Simplified tests for performance module."""

from unittest.mock import patch

from django.test import TestCase

from django_smart_ratelimit import RateLimitCache


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
