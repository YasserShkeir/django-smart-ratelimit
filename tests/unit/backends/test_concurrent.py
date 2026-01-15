"""Tests for concurrent backend access."""

import threading

import pytest

from django.test import TransactionTestCase

from django_smart_ratelimit.backends.memory import MemoryBackend

try:
    from django_smart_ratelimit.backends.redis_backend import RedisBackend

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class TestConcurrentAccess(TransactionTestCase):
    """Tests for concurrent rate limiting accuracy."""

    def test_concurrent_increment_accuracy_memory(self):
        """Verify count accuracy under concurrent increments (MemoryBackend)."""
        backend = MemoryBackend()
        key = "test:concurrent:memory"
        num_threads = 10
        increments_per_thread = 100
        expected_total = num_threads * increments_per_thread

        errors = []

        def increment_worker():
            try:
                for _ in range(increments_per_thread):
                    backend.incr(key, period=60)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=increment_worker) for _ in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"

        count = backend.get_count(key, period=60)
        # Allow small margin for timing issues
        assert (
            abs(count - expected_total) <= 5
        ), f"Expected ~{expected_total}, got {count}"

    def test_concurrent_rate_limit_enforcement_memory(self):
        """Verify rate limit is enforced under concurrent access (MemoryBackend)."""
        backend = MemoryBackend()
        key = "test:limit:memory"
        limit = 100
        num_threads = 20
        requests_per_thread = 20  # 400 total, but limit is 100

        allowed_count = 0
        denied_count = 0
        lock = threading.Lock()

        def check_worker():
            nonlocal allowed_count, denied_count
            for _ in range(requests_per_thread):
                # Simulate request: increment and check
                count = backend.incr(key, period=60)
                allowed = count <= limit

                with lock:
                    if allowed:
                        allowed_count += 1
                    else:
                        denied_count += 1

        threads = [threading.Thread(target=check_worker) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should allow approximately 'limit' requests
        # We allow a small margin because of potential race conditions in the test setup itself
        # or slight over-counting in some backends (though MemoryBackend should be strict)
        assert (
            allowed_count <= limit + 5
        ), f"Allowed too many: {allowed_count} (Limit: {limit})"
        assert denied_count >= (num_threads * requests_per_thread) - limit - 5

    @pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not available")
    def test_concurrent_increment_accuracy_redis(self):
        """Verify count accuracy under concurrent increments (RedisBackend)."""
        try:
            backend = RedisBackend()
            # Ensure redis is connected
            if backend.redis is None:
                raise Exception("Redis Connection Failed (fail_open=True)")
            backend.redis.ping()
        except Exception as e:
            pytest.skip("Redis server not available: " + str(e))

        key = "test:concurrent:redis"
        # Clear key first
        backend.reset(key)

        num_threads = 10
        increments_per_thread = (
            50  # Reduced for Redis to avoid timeout/connection limits in test env
        )
        expected_total = num_threads * increments_per_thread

        errors = []

        def increment_worker():
            try:
                for _ in range(increments_per_thread):
                    backend.incr(key, period=60)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=increment_worker) for _ in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"

        count = backend.get_count(key, period=60)
        assert (
            abs(count - expected_total) <= 5
        ), f"Expected ~{expected_total}, got {count}"
