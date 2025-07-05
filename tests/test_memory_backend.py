"""
Tests for the memory backend.

This module tests the in-memory rate limiting backend including thread safety,
memory management, and algorithm correctness.
"""

import threading
import time
import unittest

from django.test import TestCase, override_settings

from django_smart_ratelimit.backends.memory import MemoryBackend


class MemoryBackendTest(TestCase):
    """Test cases for the MemoryBackend class."""

    def setUp(self):
        """Set up test fixtures."""
        self.backend = MemoryBackend()

    def tearDown(self):
        """Clean up after tests."""
        self.backend.clear_all()

    def test_incr_basic(self):
        """Test basic increment functionality."""
        # First increment
        count = self.backend.incr("test_key", 60)
        self.assertEqual(count, 1)

        # Second increment
        count = self.backend.incr("test_key", 60)
        self.assertEqual(count, 2)

        # Third increment
        count = self.backend.incr("test_key", 60)
        self.assertEqual(count, 3)

    def test_incr_different_keys(self):
        """Test increment with different keys."""
        count1 = self.backend.incr("key1", 60)
        count2 = self.backend.incr("key2", 60)
        count3 = self.backend.incr("key1", 60)

        self.assertEqual(count1, 1)
        self.assertEqual(count2, 1)
        self.assertEqual(count3, 2)

    def test_get_count(self):
        """Test get_count method."""
        # Non-existent key
        count = self.backend.get_count("nonexistent")
        self.assertEqual(count, 0)

        # After increment
        self.backend.incr("test_key", 60)
        self.backend.incr("test_key", 60)
        count = self.backend.get_count("test_key")
        self.assertEqual(count, 2)

    def test_reset(self):
        """Test reset functionality."""
        # Increment counter
        self.backend.incr("test_key", 60)
        self.backend.incr("test_key", 60)

        # Verify count
        count = self.backend.get_count("test_key")
        self.assertEqual(count, 2)

        # Reset
        self.backend.reset("test_key")

        # Verify reset
        count = self.backend.get_count("test_key")
        self.assertEqual(count, 0)

    def test_get_reset_time(self):
        """Test get_reset_time method."""
        # Non-existent key
        reset_time = self.backend.get_reset_time("nonexistent")
        self.assertIsNone(reset_time)

        # After increment
        start_time = time.time()
        self.backend.incr("test_key", 60)
        reset_time = self.backend.get_reset_time("test_key")

        self.assertIsNotNone(reset_time)
        self.assertGreaterEqual(reset_time, int(start_time + 60))
        self.assertLessEqual(reset_time, int(start_time + 61))

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

        # Wait another 1.5 seconds (first request should expire)
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
        results = []
        errors = []

        def increment_worker():
            """Worker function for thread safety test."""
            try:
                for _ in range(10):
                    count = self.backend.incr("thread_test", 60)
                    results.append(count)
                    time.sleep(0.001)  # Small delay to increase contention
            except Exception as e:
                errors.append(e)

        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=increment_worker)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

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


class MemoryBackendIntegrationTest(TestCase):
    """Integration tests for the memory backend."""

    def test_backend_factory_integration(self):
        """Test that the backend factory returns MemoryBackend."""
        from django_smart_ratelimit.backends import get_backend

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
            def test_view(request):
                return HttpResponse("OK")

            factory = RequestFactory()
            request = factory.get("/")
            request.META["REMOTE_ADDR"] = "127.0.0.1"

            # First 5 requests should succeed
            for i in range(5):
                response = test_view(request)
                self.assertEqual(response.status_code, 200)
                # Check rate limit headers
                self.assertIn("X-RateLimit-Limit", response.headers)
                self.assertEqual(response.headers["X-RateLimit-Limit"], "5")

            # 6th request should be rate limited
            response = test_view(request)
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

            middleware = RateLimitMiddleware(lambda request: HttpResponse("OK"))

            factory = RequestFactory()
            request = factory.get("/")
            request.META["REMOTE_ADDR"] = "127.0.0.1"

            # First 3 requests should succeed
            for i in range(3):
                response = middleware(request)
                self.assertEqual(response.status_code, 200)

            # 4th request should be rate limited
            response = middleware(request)
            self.assertEqual(response.status_code, 429)


if __name__ == "__main__":
    unittest.main()
