import unittest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test.utils import override_settings

from django_smart_ratelimit.backends.memory import MemoryBackend

# Check if redis is available
try:
    import redis as redis_module  # noqa: F401

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class BatchCheckTests(SimpleTestCase):
    def test_base_backend_batch_fallback(self):
        """Test BaseBackend implementation of check_batch (via MemoryBackend)."""
        backend = MemoryBackend()

        checks = [
            {"key": "user:1", "limit": 5, "period": 60},
            {"key": "user:2", "limit": 1, "period": 60},
        ]

        # 1. First run, all allow (count=1)
        results = backend.check_batch(checks)
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0][0])  # Allowed
        self.assertEqual(results[0][1]["count"], 1)
        self.assertTrue(results[1][0])  # Allowed
        self.assertEqual(results[1][1]["count"], 1)

        # 2. Second run for user:2, limits is 1, so should exceed (count=2)
        results = backend.check_batch([checks[1]])
        self.assertFalse(results[0][0])  # Blocked
        self.assertEqual(results[0][1]["count"], 2)

    @unittest.skipUnless(HAS_REDIS, "redis package not installed")
    @override_settings(RATELIMIT_REDIS={"host": "localhost", "port": 6379})
    @patch("django_smart_ratelimit.backends.redis_backend.redis.Redis")
    def test_redis_batch_pipeline(self, MockRedis):
        """Test RedisBackend check_batch uses pipeline."""
        from django_smart_ratelimit.backends.redis_backend import RedisBackend

        mock_client = MockRedis.return_value
        mock_pipeline = mock_client.pipeline.return_value
        mock_pipeline.__enter__.return_value = mock_pipeline

        backend = RedisBackend()
        backend.sliding_window_sha = "mock_sha"

        checks = [
            {"key": "ip:1.2.3.4", "limit": 10, "period": 60},
            {"key": "ip:5.6.7.8", "limit": 5, "period": 300},
        ]

        # Mock pipeline execution results: counts 1 and 6 respectively
        # 1 <= 10 (Allowed)
        # 6 > 5 (Blocked)
        mock_pipeline.execute.return_value = [1, 6]

        results = backend.check_batch(checks)

        # Check pipeline usage
        mock_client.pipeline.assert_called_once()
        self.assertEqual(mock_pipeline.evalsha.call_count, 2)
        mock_pipeline.execute.assert_called_once()

        # Check results
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0][0])
        self.assertEqual(results[0][1]["count"], 1)
        self.assertFalse(results[1][0])  # 6 > 5
        self.assertEqual(results[1][1]["count"], 6)

    @unittest.skipUnless(HAS_REDIS, "redis package not installed")
    @override_settings(RATELIMIT_REDIS={"host": "localhost", "port": 6379})
    @patch("django_smart_ratelimit.backends.redis_backend.redis.Redis")
    def test_redis_batch_fallback_on_error(self, MockRedis):
        """Test fallback to sequential check if pipeline fails."""
        from django_smart_ratelimit.backends.redis_backend import RedisBackend

        mock_client = MockRedis.return_value
        mock_client.pipeline.side_effect = Exception("Connection lost")

        backend = RedisBackend()

        # Mock incr() for fallback calls
        with patch.object(backend, "incr", side_effect=[1, 2]):
            checks = [
                {"key": "k1", "limit": 10, "period": 60},
                {"key": "k2", "limit": 10, "period": 60},
            ]

            results = backend.check_batch(checks)

            # Verify fallback was used (incr called)
            self.assertEqual(backend.incr.call_count, 2)
            self.assertEqual(len(results), 2)
            self.assertTrue(results[0][0])
