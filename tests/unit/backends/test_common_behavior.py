"""Tests for common backend behavior."""

import time
import unittest
from unittest.mock import MagicMock, patch

from django.test import TestCase

from django_smart_ratelimit.backends.memory import MemoryBackend

# Check if redis is available
try:
    import redis as redis_module  # noqa: F401

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class GetCountPeriodTests(TestCase):
    """Tests for get_count period parameter."""

    def test_memory_backend_get_count_period(self):
        backend = MemoryBackend(algorithm="sliding_window")
        key = "test_key"

        # Add some requests
        backend.incr(key, 60)

        # Check count with different periods
        # Since we just added it, it should be in the last 1 second
        self.assertEqual(backend.get_count(key, 1), 1)
        self.assertEqual(backend.get_count(key, 60), 1)

        # Mock time to simulate passage of time
        real_time = time.time()
        with patch("time.time") as mock_time:
            # Move forward 2 seconds
            mock_time.return_value = real_time + 2

            # Should be 0 for 1 second period (expired)
            self.assertEqual(backend.get_count(key, 1), 0)
            # Should be 1 for 60 second period (still valid)
            self.assertEqual(backend.get_count(key, 60), 1)

    @unittest.skipUnless(HAS_REDIS, "redis package not installed")
    @patch("django_smart_ratelimit.backends.redis_backend.redis.Redis")
    def test_redis_backend_get_count_period(self, mock_redis_cls):
        from django_smart_ratelimit.backends.redis_backend import RedisBackend

        mock_redis = MagicMock()
        mock_redis_cls.return_value = mock_redis

        backend = RedisBackend()
        key = "test_key"

        # Mock zcount return value
        mock_redis.zcount.return_value = 5

        count = backend.get_count(key, 30)

        self.assertEqual(count, 5)
        # Verify zcount was called with correct window start
        # window_start = now - 30
        args, _ = mock_redis.zcount.call_args
        self.assertEqual(args[0], "test:ratelimit:test_key")
        # args[1] is window_start, args[2] is "+inf"
        self.assertEqual(args[2], "+inf")
