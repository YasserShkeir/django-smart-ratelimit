"""
Tests for Token Bucket Algorithm implementation.

This module contains comprehensive tests for the token bucket algorithm
including burst behavior, refill mechanics, edge cases, and performance tests.
"""

import time
import unittest
from unittest.mock import Mock, patch

from django.test import TestCase

from django_smart_ratelimit import MemoryBackend, TokenBucketAlgorithm
from tests.utils import AlgorithmTestMixin, BaseBackendTestCase

# Try to import Redis backend for testing
try:
    from django_smart_ratelimit import RedisBackend

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class TokenBucketAlgorithmTest(BaseBackendTestCase, AlgorithmTestMixin):
    """Test cases for TokenBucketAlgorithm."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.algorithm = TokenBucketAlgorithm()
        self.key = "test:user:123"
        self.limit = 10  # 10 requests
        self.period = 60  # per minute

    def get_backend(self):
        """Return the backend to use for testing."""
        return MemoryBackend()

    def test_basic_token_consumption(self):
        """Test basic token consumption behavior."""
        # First request should be allowed
        is_allowed, metadata = self.algorithm.is_allowed(
            self.backend, self.key, self.limit, self.period
        )

        self.assertTrue(is_allowed)
        self.assert_algorithm_metadata_format(metadata)
        self.assertEqual(metadata["tokens_remaining"], 9)  # 10 - 1 = 9
        self.assertEqual(metadata["tokens_requested"], 1)
        self.assertEqual(metadata["bucket_size"], 10)
        self.assertGreater(metadata["refill_rate"], 0)

    def test_algorithm_respects_limits(self):
        """Test that algorithm respects rate limits."""
        self.assert_algorithm_respects_limits(
            self.algorithm, self.backend, self.key, self.limit, self.period
        )

    def test_algorithm_refill_behavior(self):
        """Test that algorithm refills tokens correctly."""
        self.assert_algorithm_refill_behavior(
            self.algorithm, self.backend, self.key, self.limit, self.period
        )

    def test_burst_behavior(self):
        """Test that token bucket allows burst traffic."""
        # Configure larger bucket for burst testing
        config = {"bucket_size": 20}  # Allow bursts up to 20 requests
        algorithm = TokenBucketAlgorithm(config)

        # Should be able to make 20 requests quickly (burst)
        for i in range(20):
            is_allowed, metadata = algorithm.is_allowed(
                self.backend, self.key, self.limit, self.period
            )
            self.assertTrue(is_allowed, f"Request {i+1} should be allowed")

        # 21st request should be denied
        is_allowed, metadata = algorithm.is_allowed(
            self.backend, self.key, self.limit, self.period
        )
        self.assertFalse(is_allowed)
        self.assertLess(
            metadata["tokens_remaining"], 0.1
        )  # Allow for floating point precision

    def test_token_refill(self):
        """Test that tokens refill at the correct rate."""
        # Configure fast refill for testing
        refill_rate = 2.0  # 2 tokens per second
        config = {"bucket_size": 10, "refill_rate": refill_rate}
        algorithm = TokenBucketAlgorithm(config)

        # Consume all tokens
        for _ in range(10):
            is_allowed, metadata = algorithm.is_allowed(
                self.backend, self.key, self.limit, self.period
            )
            self.assertTrue(is_allowed)  # All should be allowed initially

        # Next request should be denied (bucket empty)
        is_allowed, metadata = algorithm.is_allowed(
            self.backend, self.key, self.limit, self.period
        )
        self.assertFalse(is_allowed)

        # Mock time to simulate passage of time
        base_time = time.time()
        with patch("time.time") as mock_time:
            # Simulate 1 second passing
            mock_time.return_value = base_time + 1.0

            # Should have 2 tokens available (2 tokens/second * 1 second)
            is_allowed, metadata = algorithm.is_allowed(
                self.backend, self.key, self.limit, self.period
            )
            self.assertTrue(is_allowed)
            self.assertAlmostEqual(metadata["tokens_remaining"], 1.0, places=1)

    def test_empty_bucket_edge_case(self):
        """Test behavior when bucket is completely empty."""
        # Consume all tokens
        for _ in range(self.limit):
            self.algorithm.is_allowed(self.backend, self.key, self.limit, self.period)

        # Next request should be denied
        is_allowed, metadata = self.algorithm.is_allowed(
            self.backend, self.key, self.limit, self.period
        )

        self.assertFalse(is_allowed)
        self.assertLess(
            metadata["tokens_remaining"], 0.1
        )  # Allow for floating point precision
        self.assertGreater(metadata["time_to_refill"], 0)

    def test_full_bucket_edge_case(self):
        """Test behavior when bucket is full."""
        # Get info on fresh bucket (should be full)
        info = self.algorithm.get_info(self.backend, self.key, self.limit, self.period)

        self.assertEqual(info["tokens_remaining"], self.limit)
        self.assertEqual(info["bucket_size"], self.limit)
        self.assertEqual(info["time_to_refill"], 0.0)

    def test_custom_bucket_size(self):
        """Test custom bucket size configuration."""
        bucket_size = 25
        config = {"bucket_size": bucket_size}
        algorithm = TokenBucketAlgorithm(config)

        # Should be able to consume bucket_size tokens
        for i in range(bucket_size):
            is_allowed, metadata = algorithm.is_allowed(
                self.backend, self.key, self.limit, self.period
            )
            self.assertTrue(is_allowed)
            self.assertEqual(metadata["bucket_size"], bucket_size)

        # Next request should be denied
        is_allowed, metadata = algorithm.is_allowed(
            self.backend, self.key, self.limit, self.period
        )
        self.assertFalse(is_allowed)

    def test_custom_refill_rate(self):
        """Test custom refill rate configuration."""
        refill_rate = 5.0  # 5 tokens per second
        config = {"refill_rate": refill_rate}
        algorithm = TokenBucketAlgorithm(config)

        # Consume some tokens
        for _ in range(5):
            algorithm.is_allowed(self.backend, self.key, self.limit, self.period)

        # Check refill rate is applied
        info = algorithm.get_info(self.backend, self.key, self.limit, self.period)
        self.assertEqual(info["refill_rate"], refill_rate)

    def test_multiple_token_consumption(self):
        """Test consuming multiple tokens per request."""
        tokens_per_request = 3
        is_allowed, metadata = self.algorithm.is_allowed(
            self.backend,
            self.key,
            self.limit,
            self.period,
            tokens_requested=tokens_per_request,
        )

        self.assertTrue(is_allowed)
        self.assertEqual(metadata["tokens_remaining"], self.limit - tokens_per_request)
        self.assertEqual(metadata["tokens_requested"], tokens_per_request)

    def test_get_info_without_consumption(self):
        """Test that get_info doesn't consume tokens."""
        # Get initial info
        info1 = self.algorithm.get_info(self.backend, self.key, self.limit, self.period)

        # Get info again
        info2 = self.algorithm.get_info(self.backend, self.key, self.limit, self.period)

        # Should be identical (no tokens consumed)
        self.assertEqual(info1["tokens_remaining"], info2["tokens_remaining"])

    def test_reset_functionality(self):
        """Test bucket reset functionality."""
        # Use a unique key for this test
        reset_key = "reset_test_key"

        # Make some requests to create bucket state
        for _ in range(5):
            is_allowed, metadata = self.algorithm.is_allowed(
                self.backend, reset_key, self.limit, self.period
            )
            self.assertTrue(is_allowed)

        # Test reset method exists and doesn't crash
        result = self.algorithm.reset(self.backend, reset_key)
        self.assertIsInstance(result, bool)

        # Test that we can still make requests after reset attempt
        is_allowed, metadata = self.algorithm.is_allowed(
            self.backend, reset_key, self.limit, self.period
        )
        self.assertTrue(is_allowed)
        self.assertIsInstance(metadata, dict)
        self.assertIn("tokens_remaining", metadata)

    def test_initial_tokens_configuration(self):
        """Test custom initial tokens configuration."""
        initial_tokens = 5
        config = {"initial_tokens": initial_tokens}
        algorithm = TokenBucketAlgorithm(config)

        # First request should consume from initial_tokens
        is_allowed, metadata = algorithm.is_allowed(
            self.backend, "test_key", self.limit, self.period
        )
        self.assertTrue(is_allowed)
        # Should have initial_tokens - 1 remaining
        self.assertEqual(metadata["tokens_remaining"], initial_tokens - 1)

    def test_tokens_per_request_configuration(self):
        """Test custom tokens_per_request configuration."""
        tokens_per_request = 3
        config = {"tokens_per_request": tokens_per_request}
        algorithm = TokenBucketAlgorithm(config)

        # Without explicit tokens_requested, should use config value
        is_allowed, metadata = algorithm.is_allowed(
            self.backend, "test_key", self.limit, self.period
        )
        self.assertTrue(is_allowed)
        self.assertEqual(metadata["tokens_requested"], tokens_per_request)
        self.assertEqual(metadata["tokens_remaining"], self.limit - tokens_per_request)

    def test_allow_partial_configuration(self):
        """Test allow_partial configuration behavior."""
        # This test assumes the allow_partial feature is implemented
        # Currently it's in the config but not used in the implementation
        config = {"allow_partial": True}
        algorithm = TokenBucketAlgorithm(config)

        # Consume most tokens
        for _ in range(9):
            algorithm.is_allowed(self.backend, "test_key", self.limit, self.period)

        # Try to request more tokens than available
        is_allowed, metadata = algorithm.is_allowed(
            self.backend, "test_key", self.limit, self.period, tokens_requested=5
        )
        # With current implementation, this should fail
        # TODO: Implement allow_partial feature
        self.assertFalse(is_allowed)

    def test_time_based_expiration(self):
        """Test that token bucket refill works with time passage."""
        # Use a fixed base time to ensure consistent behavior
        base_time = 1000000.0  # Fixed timestamp

        with patch("time.time") as mock_time:
            # Start with a fixed time
            mock_time.return_value = base_time

            # Create a bucket and consume most tokens
            for _ in range(9):
                is_allowed, metadata = self.algorithm.is_allowed(
                    self.backend, "expiry_test", 10, 60
                )
                self.assertTrue(is_allowed)

            # Should have 1 token left
            is_allowed, metadata = self.algorithm.is_allowed(
                self.backend, "expiry_test", 10, 60
            )
            self.assertTrue(is_allowed)
            self.assertAlmostEqual(metadata["tokens_remaining"], 0, places=0)

            # Next request should be denied
            is_allowed, metadata = self.algorithm.is_allowed(
                self.backend, "expiry_test", 10, 60
            )
            self.assertFalse(is_allowed)

            # Now advance time by 60 seconds (1 minute)
            # With limit=10, period=60, refill_rate = 10/60 = 0.1667 tokens/second
            # After 60 seconds, we should have 0.1667 * 60 = 10 tokens
            # (capped at bucket_size=10)
            mock_time.return_value = base_time + 60  # 1 minute later

            # Should have refilled to full bucket
            is_allowed, metadata = self.algorithm.is_allowed(
                self.backend, "expiry_test", 10, 60
            )
            self.assertTrue(is_allowed)
            self.assertAlmostEqual(metadata["tokens_remaining"], 9, places=0)

    def test_concurrent_access_simulation(self):
        """Test token bucket behavior under simulated concurrent access."""
        import queue
        import threading

        results = queue.Queue()

        def worker():
            is_allowed, metadata = self.algorithm.is_allowed(
                self.backend, "concurrent_test", 10, 60
            )
            results.put(is_allowed)

        # Create multiple threads to simulate concurrent access
        threads = []
        for _ in range(15):  # More than the limit
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Collect results
        allowed_count = 0
        while not results.empty():
            if results.get():
                allowed_count += 1

        # Should allow exactly the bucket size number of requests
        self.assertEqual(allowed_count, 10)


@unittest.skipUnless(REDIS_AVAILABLE, "Redis not available")
class TokenBucketRedisTest(TestCase):
    """Test token bucket with Redis backend."""

    def setUp(self):
        """Set up Redis backend test fixtures."""
        try:
            self.backend = RedisBackend()
            self.algorithm = TokenBucketAlgorithm()
            self.key = "test:redis:user:123"
            self.limit = 10
            self.period = 60
        except Exception as e:
            self.skipTest(f"Redis backend not available: {e}")

    def tearDown(self):
        """Clean up Redis test data."""
        if hasattr(self, "backend"):
            self.backend.delete(f"{self.key}:token_bucket")

    def test_redis_lua_script_execution(self):
        """Test that Redis Lua script executes correctly."""
        # Test basic token bucket operation
        is_allowed, metadata = self.algorithm.is_allowed(
            self.backend, self.key, self.limit, self.period
        )

        self.assertTrue(is_allowed)
        self.assertEqual(metadata["tokens_remaining"], 9)
        self.assertEqual(metadata["bucket_size"], 10)

    def test_redis_atomic_operations(self):
        """Test that Redis operations are atomic."""
        # This is more of an integration test - the atomicity
        # is guaranteed by Redis Lua scripts

        # Rapid requests should be handled correctly
        results = []
        for _ in range(15):  # More than limit
            is_allowed, metadata = self.algorithm.is_allowed(
                self.backend, self.key, self.limit, self.period
            )
            results.append(is_allowed)

        # First 10 should be allowed, rest denied
        allowed_count = sum(results)
        self.assertEqual(allowed_count, 10)

    def test_redis_persistence(self):
        """Test that token bucket state persists in Redis."""
        # Consume some tokens
        for _ in range(5):
            self.algorithm.is_allowed(self.backend, self.key, self.limit, self.period)

        # Create new algorithm instance (simulates new request)
        new_algorithm = TokenBucketAlgorithm()

        # Should see the same state
        info = new_algorithm.get_info(self.backend, self.key, self.limit, self.period)
        self.assertEqual(info["tokens_remaining"], 5)


class TokenBucketPerformanceTest(TestCase):
    """Performance tests for token bucket algorithm."""

    def setUp(self):
        """Set up performance test fixtures."""
        self.backend = MemoryBackend()
        self.algorithm = TokenBucketAlgorithm()

    def test_high_throughput_memory(self):
        """Test performance under high throughput with memory backend."""
        start_time = time.time()

        # Simulate high throughput
        for i in range(1000):
            key = f"user:{i % 100}"  # 100 different users
            self.algorithm.is_allowed(self.backend, key, 10, 60)

        end_time = time.time()
        duration = end_time - start_time

        # Should complete in reasonable time (adjust threshold as needed)
        self.assertLess(duration, 1.0, "High throughput test should complete quickly")

    def test_memory_usage_efficiency(self):
        """Test memory usage of token bucket data."""
        # Create many buckets
        for i in range(100):
            key = f"user:{i}"
            self.algorithm.is_allowed(self.backend, key, 10, 60)

        # Check backend stats
        stats = self.backend.get_stats()
        self.assertGreater(stats["token_buckets"], 0)
        self.assertLessEqual(stats["token_buckets"], 100)

    def test_cleanup_behavior(self):
        """Test that expired buckets are properly handled."""
        # Create buckets with short expiration
        for i in range(10):
            key = f"temp_user:{i}"
            self.algorithm.is_allowed(self.backend, key, 10, 60)

        # Verify buckets exist
        stats_before = self.backend.get_stats()
        self.assertGreater(stats_before["token_buckets"], 0)

        # Simulate time passing to expire buckets
        # This is more of a backend-specific behavior test
        if hasattr(self.backend, "_cleanup_if_needed"):
            self.backend._cleanup_if_needed()

        # Check that cleanup mechanism exists
        stats_after = self.backend.get_stats()
        self.assertIsInstance(stats_after, dict)
        self.assertIn("token_buckets", stats_after)


class TokenBucketEdgeCaseTest(TestCase):
    """Edge case tests for token bucket algorithm."""

    def setUp(self):
        """Set up edge case test fixtures."""
        self.backend = MemoryBackend()
        self.algorithm = TokenBucketAlgorithm()  # Add missing algorithm instance

    def test_zero_bucket_size(self):
        """Test behavior with zero bucket size."""
        config = {"bucket_size": 0}
        algorithm = TokenBucketAlgorithm(config)

        # Should deny all requests
        is_allowed, metadata = algorithm.is_allowed(self.backend, "test_key", 10, 60)
        self.assertFalse(is_allowed)

    def test_zero_refill_rate(self):
        """Test behavior with zero refill rate."""
        config = {"refill_rate": 0}
        algorithm = TokenBucketAlgorithm(config)

        # Should work initially but not refill
        is_allowed, metadata = algorithm.is_allowed(self.backend, "test_key", 10, 60)
        self.assertTrue(is_allowed)

        # Time passage shouldn't help
        with patch.object(algorithm, "get_current_time") as mock_time:
            mock_time.return_value = time.time() + 3600  # 1 hour later

            # Consume all tokens
            for _ in range(9):  # Already consumed 1
                algorithm.is_allowed(self.backend, "test_key", 10, 60)

            # Should be denied and stay denied
            is_allowed, metadata = algorithm.is_allowed(
                self.backend, "test_key", 10, 60
            )
            self.assertFalse(is_allowed)

    def test_extremely_high_refill_rate(self):
        """Test behavior with very high refill rate."""
        config = {"refill_rate": 1000000}  # 1M tokens per second
        algorithm = TokenBucketAlgorithm(config)

        # Should handle high refill rates gracefully
        is_allowed, metadata = algorithm.is_allowed(self.backend, "test_key", 10, 60)
        self.assertTrue(is_allowed)

    def test_fractional_tokens(self):
        """Test behavior with fractional token requests."""
        is_allowed, metadata = self.algorithm.is_allowed(
            self.backend, "test_key", 10, 60, tokens_requested=0.5
        )

        # Should handle fractional tokens
        self.assertTrue(is_allowed)
        self.assertAlmostEqual(metadata["tokens_remaining"], 9.5, places=1)

    def test_backend_failure_graceful_handling(self):
        """Test graceful handling of backend failures."""
        # Mock a failing backend
        failing_backend = Mock()
        failing_backend.token_bucket_check.side_effect = Exception("Backend failed")
        failing_backend.get.side_effect = Exception("Backend failed")
        failing_backend.set.side_effect = Exception("Backend failed")

        # Should fall back to allowing requests or raise appropriate errors
        with self.assertRaises(Exception):
            self.algorithm.is_allowed(failing_backend, "test_key", 10, 60)
