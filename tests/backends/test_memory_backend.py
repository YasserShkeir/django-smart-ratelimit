"""
Tests for the memory backend.

This module tests the in-memory rate limiting backend including thread safety,
memory management, and algorithm correctness.
"""

import threading
import time
import unittest

from django.test import TestCase, override_settings

from django_smart_ratelimit import MemoryBackend
from tests.utils import (
    BaseBackendTestCase,
    ErrorHandlingTestMixin,
    PerformanceTestMixin,
    generate_test_keys,
    run_concurrent_operations,
)


class MemoryBackendTest(
    BaseBackendTestCase, PerformanceTestMixin, ErrorHandlingTestMixin
):
    """Test cases for the MemoryBackend class."""

    def get_backend(self):
        """Return the backend to test."""
        return MemoryBackend()

    def test_incr_basic(self):
        """Test basic increment functionality."""
        # Test using utility methods
        self.assert_increment_behavior(self.test_key, self.test_period, 1)
        self.assert_increment_behavior(self.test_key, self.test_period, 2)
        self.assert_increment_behavior(self.test_key, self.test_period, 3)

    def test_incr_different_keys(self):
        """Test increment with different keys."""
        keys = generate_test_keys(2)

        # Test multiple keys
        self.assert_increment_behavior(keys[0], self.test_period, 1)
        self.assert_increment_behavior(keys[1], self.test_period, 1)
        self.assert_increment_behavior(keys[0], self.test_period, 2)

    def test_get_count(self):
        """Test get_count method."""
        # Non-existent key
        self.assert_get_count("nonexistent", 0)

        # After increment
        self.create_test_data(self.test_key, 2)
        self.assert_get_count(self.test_key, 2)

    def test_reset(self):
        """Test reset functionality."""
        self.assert_reset_behavior(self.test_key)

    def test_get_reset_time(self):
        """Test get_reset_time method."""
        # Non-existent key
        self.assert_get_reset_time("nonexistent", should_exist=False)

        # After increment
        time.time()
        self.backend.incr("test_key", 60)
        self.assert_get_reset_time("test_key", should_exist=True)

    @override_settings(RATELIMIT_ALGORITHM="sliding_window")
    def test_sliding_window_algorithm(self):
        """Test sliding window algorithm."""
        backend = MemoryBackend()

        # Add requests
        count1 = backend.incr("test_key", 2)  # 2 second window
        self.assertEqual(count1, 1)

        # Wait 1 second
        time.sleep(1)
        count2 = backend.incr("test_key", 2)
        self.assertEqual(count2, 2)

        # Wait another 1.5 seconds (first _request should expire)
        time.sleep(1.5)
        count3 = backend.incr("test_key", 2)
        self.assertEqual(count3, 2)  # Only second and third requests

    @override_settings(RATELIMIT_ALGORITHM="fixed_window")
    def test_fixed_window_algorithm(self):
        """Test fixed window algorithm."""
        backend = MemoryBackend()

        # Add requests
        count1 = backend.incr("test_key", 2)  # 2 second window
        self.assertEqual(count1, 1)

        count2 = backend.incr("test_key", 2)
        self.assertEqual(count2, 2)

        # Wait for window to expire
        time.sleep(2.1)
        count3 = backend.incr("test_key", 2)
        self.assertEqual(count3, 1)  # New window started

    def test_thread_safety(self):
        """Test thread safety of the backend."""

        def increment_operation():
            return self.backend.incr("thread_test", 60)

        results, errors = run_concurrent_operations(increment_operation, 5, 10)

        # Check for errors
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")

        # Check that we got the expected number of results
        self.assertEqual(len(results), 50)  # 5 threads * 10 increments

        # Check that the final count is correct
        final_count = self.backend.get_count("thread_test")
        self.assertEqual(final_count, 50)

    def test_memory_limit_enforcement(self):
        """Test that memory limits are enforced."""
        with override_settings(RATELIMIT_MEMORY_MAX_KEYS=5):
            backend = MemoryBackend()

            # Add more keys than the limit
            for i in range(10):
                backend.incr(f"key_{i}", 60)

            # Force cleanup
            backend._cleanup_if_needed()

            # Should have at most max_keys
            stats = backend.get_stats()
            self.assertLessEqual(stats["total_keys"], 5)

    def test_cleanup_expired_keys(self):
        """Test cleanup of expired keys in fixed window mode."""
        with override_settings(RATELIMIT_ALGORITHM="fixed_window"):
            backend = MemoryBackend()

            # Add a key with short expiry
            backend.incr("short_key", 1)

            # Wait for expiry
            time.sleep(1.1)

            # Add another key to trigger cleanup
            backend.incr("new_key", 60)

            # Force cleanup
            backend._cleanup_if_needed()

            # Short key should be cleaned up
            count = backend.get_count("short_key")
            self.assertEqual(count, 0)

    def test_get_stats(self):
        """Test get_stats method."""
        # Initial stats
        stats = self.backend.get_stats()
        self.assertEqual(stats["total_keys"], 0)
        self.assertEqual(stats["active_keys"], 0)
        self.assertEqual(stats["total_requests"], 0)
        self.assertIn("max_keys", stats)
        self.assertIn("cleanup_interval", stats)
        self.assertIn("algorithm", stats)

        # Add some data
        self.backend.incr("key1", 60)
        self.backend.incr("key1", 60)
        self.backend.incr("key2", 60)

        stats = self.backend.get_stats()
        self.assertEqual(stats["total_keys"], 2)
        self.assertEqual(stats["active_keys"], 2)
        self.assertEqual(stats["total_requests"], 3)

    def test_clear_all(self):
        """Test clear_all method."""
        # Add some data
        self.backend.incr("key1", 60)
        self.backend.incr("key2", 60)

        # Verify data exists
        stats = self.backend.get_stats()
        self.assertEqual(stats["total_keys"], 2)

        # Clear all
        self.backend.clear_all()

        # Verify cleared
        stats = self.backend.get_stats()
        self.assertEqual(stats["total_keys"], 0)

    def test_configuration_settings(self):
        """Test configuration settings are properly loaded."""
        with override_settings(
            RATELIMIT_MEMORY_MAX_KEYS=1000,
            RATELIMIT_MEMORY_CLEANUP_INTERVAL=600,
            RATELIMIT_ALGORITHM="fixed_window",
        ):
            backend = MemoryBackend()
            stats = backend.get_stats()

            self.assertEqual(stats["max_keys"], 1000)
            self.assertEqual(stats["cleanup_interval"], 600)
            self.assertEqual(stats["algorithm"], "fixed_window")

    def test_concurrent_access_different_keys(self):
        """Test concurrent access to different keys."""
        results = {}
        errors = []

        def worker(key_suffix):
            """Worker function for concurrent access test."""
            try:
                key = f"concurrent_key_{key_suffix}"
                for i in range(20):
                    count = self.backend.incr(key, 60)
                    if key not in results:
                        results[key] = []
                    results[key].append(count)
            except Exception as e:
                errors.append(e)

        # Create threads for different keys
        threads = []
        for i in range(3):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Check results
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        self.assertEqual(len(results), 3)

        # Each key should have counts from 1 to 20
        for key, counts in results.items():
            self.assertEqual(len(counts), 20)
            self.assertEqual(counts, list(range(1, 21)))

    def test_reset_nonexistent_key(self):
        """Test resetting a non-existent key doesn't cause errors."""
        # This should not raise an exception
        self.backend.reset("nonexistent_key")

        # Verify no data was created
        count = self.backend.get_count("nonexistent_key")
        self.assertEqual(count, 0)

    def test_large_period_values(self):
        """Test with large period values."""
        large_period = 86400  # 24 hours

        count = self.backend.incr("large_period_key", large_period)
        self.assertEqual(count, 1)

        reset_time = self.backend.get_reset_time("large_period_key")
        self.assertIsNotNone(reset_time)
        self.assertGreater(reset_time, int(time.time() + large_period - 1))

    def test_token_bucket_check_allows_consumption(self):
        """Memory token_bucket_check should allow consumption and return metadata."""
        backend = self.backend
        allowed, meta = backend.token_bucket_check(
            key="tb_mem",
            bucket_size=10,
            refill_rate=1.0,
            initial_tokens=10,
            tokens_requested=3,
        )
        self.assertTrue(allowed)
        self.assertIn("tokens_remaining", meta)
        self.assertLessEqual(meta["tokens_remaining"], 7.0)
        self.assertEqual(meta.get("bucket_size"), 10)
        self.assertEqual(meta.get("refill_rate"), 1.0)
        self.assertEqual(meta.get("tokens_requested"), 3)

    def test_token_bucket_check_rejects_when_insufficient(self):
        """Memory token_bucket_check should reject when not enough tokens are available."""
        backend = self.backend
        allowed, meta = backend.token_bucket_check(
            key="tb_mem_reject",
            bucket_size=10,
            refill_rate=1.0,
            initial_tokens=1,
            tokens_requested=3,
        )
        self.assertFalse(allowed)
        self.assertGreaterEqual(meta.get("tokens_remaining", 0), 1.0)
        self.assertEqual(meta.get("bucket_size"), 10)
        self.assertEqual(meta.get("refill_rate"), 1.0)
        self.assertEqual(meta.get("tokens_requested"), 3)
        self.assertGreater(meta.get("time_to_refill", 0), 0)

    def test_token_bucket_check_zero_bucket_size_rejects(self):
        """Zero bucket size should be rejected with error-like metadata and inf time_to_refill."""
        backend = self.backend
        allowed, meta = backend.token_bucket_check(
            key="tb_zero",
            bucket_size=0,
            refill_rate=1.0,
            initial_tokens=0,
            tokens_requested=2,
        )
        self.assertFalse(allowed)
        self.assertEqual(meta.get("tokens_remaining"), 0)
        self.assertEqual(meta.get("bucket_size"), 0)
        self.assertEqual(meta.get("tokens_requested"), 2)
        # time_to_refill is set to infinity in memory backend for this path
        self.assertTrue(
            meta.get("time_to_refill") in (float("inf"),)
            or meta.get("time_to_refill") > 1e9
        )

    def test_token_bucket_info_before_and_after_consumption(self):
        """token_bucket_info reflects initial state and updates after consumption."""
        backend = self.backend
        # Before any consumption, bucket should appear full
        info_initial = backend.token_bucket_info("tb_info", 10, 1.0)
        self.assertEqual(info_initial.get("bucket_size"), 10)
        self.assertEqual(info_initial.get("refill_rate"), 1.0)
        self.assertEqual(info_initial.get("tokens_remaining"), 10)
        self.assertIn("last_refill", info_initial)

        # Consume 4 tokens
        allowed, meta = backend.token_bucket_check(
            key="tb_info",
            bucket_size=10,
            refill_rate=1.0,
            initial_tokens=10,
            tokens_requested=4,
        )
        self.assertTrue(allowed)
        # Immediately check info; should be <= 10 and around 6 (allowing tiny refill)
        info_after = backend.token_bucket_info("tb_info", 10, 1.0)
        self.assertEqual(info_after.get("bucket_size"), 10)
        self.assertLessEqual(info_after.get("tokens_remaining", 10), 10)
        self.assertGreaterEqual(info_after.get("tokens_remaining", 0), 6.0)
        self.assertIn("time_to_refill", info_after)


class MemoryBackendIntegrationTest(TestCase):
    """Integration tests for the memory backend."""

    def test_backend_factory_integration(self):
        """Test that the backend factory returns MemoryBackend."""
        from django_smart_ratelimit import get_backend

        with override_settings(RATELIMIT_BACKEND="memory"):
            backend = get_backend()
            self.assertIsInstance(backend, MemoryBackend)

    def test_decorator_integration(self):
        """Test integration with the rate limit decorator."""
        from django.http import HttpResponse
        from django.test import RequestFactory

        from django_smart_ratelimit import rate_limit
        from django_smart_ratelimit.backends import clear_backend_cache

        with override_settings(RATELIMIT_BACKEND="memory"):
            # Clear backend cache to ensure fresh instance
            clear_backend_cache()

            @rate_limit(key="ip", rate="5/m", backend="memory")
            def test_view(_request):
                return HttpResponse("OK")

            factory = RequestFactory()
            _request = factory.get("/")
            _request.META["REMOTE_ADDR"] = "127.0.0.1"

            # First 5 requests should succeed
            for i in range(5):
                response = test_view(_request)
                self.assertEqual(response.status_code, 200)
                # Check rate limit headers
                self.assertIn("X-RateLimit-Limit", response.headers)
                self.assertEqual(response.headers["X-RateLimit-Limit"], "5")

            # 6th _request should be rate limited
            response = test_view(_request)
            self.assertEqual(response.status_code, 429)

    def test_middleware_integration(self):
        """Test integration with the rate limit middleware."""
        from django.http import HttpResponse
        from django.test import RequestFactory

        from django_smart_ratelimit.backends import clear_backend_cache
        from django_smart_ratelimit.middleware import RateLimitMiddleware

        with override_settings(
            RATELIMIT_BACKEND="memory",
            RATELIMIT_MIDDLEWARE={
                "DEFAULT_RATE": "3/m",
                "BACKEND": "memory",
            },
        ):
            # Clear backend cache to ensure fresh instance
            clear_backend_cache()

            middleware = RateLimitMiddleware(lambda _request: HttpResponse("OK"))

            factory = RequestFactory()
            _request = factory.get("/")
            _request.META["REMOTE_ADDR"] = "127.0.0.1"

            # First 3 requests should succeed
            for i in range(3):
                response = middleware(_request)
                self.assertEqual(response.status_code, 200)

            # 4th _request should be rate limited
            response = middleware(_request)
            self.assertEqual(response.status_code, 429)


class MemoryBackendAdvancedTests(TestCase):
    """Advanced test scenarios for memory backend addressing coverage gaps."""

    def setUp(self):
        """Set up test environment."""
        self.backend = MemoryBackend()

    def test_eviction_under_many_keys_churn(self):
        """Test eviction behavior under high key churn scenarios."""
        with override_settings(RATELIMIT_MEMORY_MAX_KEYS=50):
            backend = MemoryBackend()

            # Generate many more keys than the limit to force eviction
            keys_created = []
            for i in range(200):
                key = f"churn_key_{i:04d}"
                backend.incr(key, 60)  # Long TTL
                keys_created.append(key)

                # Periodically force cleanup to trigger eviction
                if i % 25 == 0:
                    backend._cleanup_if_needed()

            # Force final cleanup
            backend._cleanup_if_needed()

            # Should maintain max_keys limit
            stats = backend.get_stats()
            self.assertLessEqual(stats["total_keys"], 50)

            # Verify some recent keys are preserved (LRU behavior)
            recent_keys_preserved = 0
            for key in keys_created[-25:]:  # Check last 25 keys
                if backend.get_count(key) > 0:
                    recent_keys_preserved += 1

            # Should preserve recent keys preferentially
            self.assertGreater(recent_keys_preserved, 10)

    def test_memory_growth_bounds_validation(self):
        """Test that memory usage stays within expected bounds."""

        with override_settings(RATELIMIT_MEMORY_MAX_KEYS=10):
            backend = MemoryBackend()

            # Create baseline memory footprint
            initial_keys = 5
            for i in range(initial_keys):
                backend.incr(f"baseline_{i}", 3600)

            baseline_stats = backend.get_stats()
            self.assertEqual(baseline_stats["total_keys"], initial_keys)

            # Add keys beyond limit to test bounds enforcement
            for i in range(20):  # Add 20 more keys
                backend.incr(f"overflow_{i}", 3600)
                backend._cleanup_if_needed()  # Force cleanup checks

            # Memory should be bounded by max_keys setting
            final_stats = backend.get_stats()
            self.assertLessEqual(final_stats["total_keys"], 10)

            # Verify data structure doesn't grow unbounded
            # This is a proxy test for memory bounds
            self.assertLess(len(backend._data), 15)  # Some buffer allowed

    def test_ttl_expiry_behavior_validation(self):
        """Test that TTL expiry behavior works as expected in memory backend."""
        import time

        from django.test import override_settings

        # Test with fixed window algorithm specifically
        with override_settings(RATELIMIT_ALGORITHM="fixed_window"):
            backend = MemoryBackend()

            # Create a short-lived key
            test_key = "expiry_test"
            backend.incr(test_key, 1)  # 1 second TTL

            # Should exist initially
            initial_count = backend.get_count(test_key)
            self.assertEqual(initial_count, 1)

            # Wait for expiry
            time.sleep(1.1)

            # Key should still be in data but is_expired should return True
            # The get_count method should return 0 for expired keys in fixed window
            expired_count = backend.get_count(test_key)

            # With fixed window, expired keys should return 0
            self.assertEqual(expired_count, 0)

            # After cleanup, the key should be removed from internal storage
            backend._last_cleanup = 0  # Force cleanup to run
            backend._cleanup_if_needed()

            # Verify cleanup worked by checking internal state
            normalized_key = f"memory:{test_key}"  # Assumes memory prefix
            # The key should either be gone or marked as expired
            if normalized_key in backend._data:
                expiry_time, _ = backend._data[normalized_key]
                # Expiry time should be in the past
                self.assertLess(expiry_time, time.time())

            # get_count should still return 0 after cleanup
            final_count = backend.get_count(test_key)
            self.assertEqual(final_count, 0)

    def test_gil_contention_scenarios_if_threading(self):
        """Test behavior under Python GIL contention scenarios."""
        import queue
        import threading

        backend = self.backend
        num_threads = 8
        operations_per_thread = 25
        results_queue = queue.Queue()
        errors_queue = queue.Queue()

        def gil_intensive_worker(worker_id):
            """Worker that performs GIL-intensive operations."""
            try:
                local_results = []
                for i in range(operations_per_thread):
                    # Mix of operations to create GIL contention
                    key = f"gil_test_{worker_id}_{i}"

                    # Increment
                    count = backend.incr(key, 30)
                    local_results.append(count)

                    # Get count (read operation)
                    read_count = backend.get_count(key)
                    self.assertEqual(read_count, count)

                    # Stats (aggregate operation)
                    if i % 5 == 0:
                        stats = backend.get_stats()
                        self.assertGreater(stats["total_keys"], 0)

                results_queue.put((worker_id, local_results))
            except Exception as e:
                errors_queue.put((worker_id, e))

        # Start threads
        threads = []
        for worker_id in range(num_threads):
            thread = threading.Thread(target=gil_intensive_worker, args=(worker_id,))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Validate results
        errors = []
        while not errors_queue.empty():
            worker_id, error = errors_queue.get()
            errors.append(f"Worker {worker_id}: {error}")

        self.assertEqual(len(errors), 0, f"GIL contention errors: {errors}")

        # Verify all workers completed successfully
        results = {}
        while not results_queue.empty():
            worker_id, worker_results = results_queue.get()
            results[worker_id] = worker_results

        self.assertEqual(len(results), num_threads)

        # Each worker should have sequential counts for their keys
        for worker_id, worker_results in results.items():
            self.assertEqual(len(worker_results), operations_per_thread)
            # Each increment on a unique key should return 1
            # (since each key is unique: f"gil_test_{worker_id}_{i}")
            expected_results = [1] * operations_per_thread
            self.assertEqual(worker_results, expected_results)

    def test_memory_backend_high_frequency_access_patterns(self):
        """Test performance under high-frequency access patterns."""
        backend = self.backend

        # Simulate high-frequency access to same key
        key = "high_freq_test"
        frequency_count = 100

        start_time = time.time()
        for i in range(frequency_count):
            count = backend.incr(key, 60)
            self.assertEqual(count, i + 1)

            # Occasionally read stats to exercise different code paths
            if i % 20 == 0:
                stats = backend.get_stats()
                self.assertGreater(stats["total_requests"], 0)

        end_time = time.time()
        duration = end_time - start_time

        # Sanity check: should complete reasonably quickly
        self.assertLess(duration, 1.0)  # Under 1 second for 100 operations

        # Verify final state
        final_count = backend.get_count(key)
        self.assertEqual(final_count, frequency_count)


if __name__ == "__main__":
    unittest.main()
