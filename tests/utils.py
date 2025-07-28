"""
Test utilities for reducing duplicate code in rate limiting tests.

This module provides common test patterns, mock backends, and utilities
that are used across multiple test files.
"""

import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from django_smart_ratelimit import BaseBackend, MemoryBackend


class MockBackend(BaseBackend):
    """
    Mock backend for testing that provides consistent behavior.

    This eliminates the need to duplicate mock backend code across test files.
    """

    def __init__(
        self,
        fail_health_check: bool = False,
        fail_operations: bool = False,
        fail_only_specific_operations: Optional[List[str]] = None,
        **_kwargs,
    ):
        """Initialize mock backend with failure options."""
        self.fail_health_check = fail_health_check
        self.fail_operations = fail_operations
        self.fail_only_specific_operations = fail_only_specific_operations or []
        self.operation_calls = []
        self.storage = {}

    def _should_fail_operation(self, operation: str) -> bool:
        """Check if operation should fail based on configuration."""
        if self.fail_operations:
            return True
        return operation in self.fail_only_specific_operations

    def incr(self, key: str, period: int) -> int:
        """Mock incr method."""
        self.operation_calls.append(("incr", key, period))
        if self._should_fail_operation("incr"):
            raise Exception("Mock backend operation failed")

        current = self.storage.get(key, 0)
        self.storage[key] = current + 1
        return current + 1

    def get_count(self, key: str) -> int:
        """Mock get_count method."""
        self.operation_calls.append(("get_count", key))
        if self._should_fail_operation("get_count"):
            raise Exception("Mock backend operation failed")
        # Return 1 for test compatibility if no storage exists
        return self.storage.get(key, 1)

    def get_reset_time(self, key: str) -> Optional[int]:
        """Mock get_reset_time method."""
        self.operation_calls.append(("get_reset_time", key))
        if self._should_fail_operation("get_reset_time"):
            raise Exception("Mock backend operation failed")
        return int(time.time()) + 3600

    def reset(self, key: str) -> None:
        """Mock reset method."""
        self.operation_calls.append(("reset", key))
        if self._should_fail_operation("reset"):
            # Don't fail health check calls
            if "__health_check_" in key:
                return
            raise Exception("Mock backend operation failed")
        self.storage.pop(key, None)

    def increment(self, key: str, window_seconds: int, limit: int) -> Tuple[int, int]:
        """Mock increment method."""
        self.operation_calls.append(("increment", key, window_seconds, limit))
        if self._should_fail_operation("increment"):
            raise Exception("Mock backend operation failed")

        count = self.incr(key, window_seconds)
        remaining = max(0, limit - count)
        return count, remaining

    def cleanup_expired(self) -> int:
        """Mock cleanup_expired method."""
        self.operation_calls.append(("cleanup_expired",))
        if self._should_fail_operation("cleanup_expired"):
            raise Exception("Mock backend operation failed")
        return 10

    def health_check(self) -> Dict[str, Any]:
        """Mock health check method."""
        if self.fail_health_check:
            return {"healthy": False, "error": "Mock health check failed"}
        return {"healthy": True, "backend": "mock"}


class BaseBackendTestCase(TestCase):
    """
    Base test case for backend tests with common setup and utilities.

    This reduces setup code duplication across backend test classes.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.backend = self.get_backend()
        self.test_key = "test_key"
        self.test_period = 60
        self.test_limit = 10

    def tearDown(self):
        """Clean up after tests."""
        if hasattr(self.backend, "clear_all"):
            self.backend.clear_all()

    def get_backend(self):
        """Override this method to return the backend to test."""
        return MemoryBackend()

    def assert_increment_behavior(self, key: str, period: int, expected_count: int):
        """Assert that incrementing a key results in expected count."""
        count = self.backend.incr(key, period)
        self.assertEqual(count, expected_count)

    def assert_get_count(self, key: str, expected_count: int):
        """Assert that getting count returns expected value."""
        count = self.backend.get_count(key)
        self.assertEqual(count, expected_count)

    def assert_reset_behavior(self, key: str):
        """Assert that resetting a key works correctly."""
        # First increment to create some data
        self.backend.incr(key, self.test_period)

        # Verify data exists
        count_before = self.backend.get_count(key)
        self.assertGreater(count_before, 0)

        # Reset
        self.backend.reset(key)

        # Verify reset
        count_after = self.backend.get_count(key)
        self.assertEqual(count_after, 0)

    def assert_get_reset_time(self, key: str, should_exist: bool = True):
        """Assert that get_reset_time returns expected result."""
        reset_time = self.backend.get_reset_time(key)

        if should_exist:
            self.assertIsNotNone(reset_time)
            self.assertIsInstance(reset_time, int)
            self.assertGreater(reset_time, int(time.time()))
        else:
            self.assertIsNone(reset_time)

    def create_test_data(self, key: str, count: int = 1):
        """Create test data by incrementing a key."""
        for _ in range(count):
            self.backend.incr(key, self.test_period)

    def assert_health_check_healthy(self):
        """Assert that backend health check returns healthy."""
        if hasattr(self.backend, "health_check"):
            health = self.backend.health_check()
            self.assertIsInstance(health, dict)
            self.assertIn("healthy", health)
            self.assertTrue(health["healthy"])

    def assert_stats_available(self):
        """Assert that backend statistics are available."""
        if hasattr(self.backend, "get_stats"):
            stats = self.backend.get_stats()
            self.assertIsInstance(stats, dict)


class RedisBackendTestMixin:
    """
    Mixin for Redis backend tests that provides common Redis mocking.

    This eliminates duplicate Redis mocking code across test files.
    """

    def setUp(self):
        """Set up Redis mocking."""
        self.redis_patcher = patch(
            "django_smart_ratelimit.backends.redis_backend.redis"
        )
        self.mock_redis_module = self.redis_patcher.start()

        # Create mock Redis client
        self.mock_redis_client = Mock()
        self.mock_redis_module.Redis.return_value = self.mock_redis_client
        self.mock_redis_client.ping.return_value = True
        self.mock_redis_client.script_load.return_value = "script_sha"

        super().setUp()

    def tearDown(self):
        """Clean up Redis mocking."""
        self.redis_patcher.stop()
        super().tearDown()

    def configure_redis_mock(self, **_kwargs):
        """Configure Redis mock with specific behaviors."""
        for attr, value in _kwargs.items():
            setattr(self.mock_redis_client, attr, value)

    def assert_redis_ping_called(self):
        """Assert that Redis ping was called."""
        self.mock_redis_client.ping.assert_called()

    def assert_redis_script_load_called(self, expected_count: int = 4):
        """Assert that Redis script_load was called expected number of times."""
        self.assertEqual(self.mock_redis_client.script_load.call_count, expected_count)


class MongoBackendTestMixin:
    """
    Mixin for MongoDB backend tests that provides common MongoDB mocking.

    This eliminates duplicate MongoDB mocking code across test files.
    """

    def setUp(self):
        """Set up MongoDB mocking."""
        self.mongo_patcher = patch("django_smart_ratelimit.backends.mongodb.pymongo")
        self.mock_pymongo = self.mongo_patcher.start()

        # Create mock MongoDB client
        self.mock_client = Mock()
        self.mock_db = Mock()
        self.mock_collection = Mock()

        self.mock_pymongo.MongoClient.return_value = self.mock_client
        # Configure the client to return the database mock when accessed with []
        self.mock_client.__getitem__ = Mock(return_value=self.mock_db)
        # Configure the database to return the collection mock when accessed with []
        self.mock_db.__getitem__ = Mock(return_value=self.mock_collection)

        super().setUp()

    def tearDown(self):
        """Clean up MongoDB mocking."""
        self.mongo_patcher.stop()
        super().tearDown()

    def configure_mongo_mock(self, **_kwargs):
        """Configure MongoDB mock with specific behaviors."""
        for attr, value in _kwargs.items():
            setattr(self.mock_collection, attr, value)


@contextmanager
def temporary_settings(**_kwargs):
    """Context manager for temporarily overriding Django settings."""
    with override_settings(**_kwargs):
        yield


def create_test_settings(backend_type: str = "memory", **overrides):
    """Create test settings for a specific backend type."""
    base_settings = {
        "memory": {
            "RATELIMIT_BACKEND": "memory",
            "RATELIMIT_MEMORY": {
                "max_entries": 1000,
                "cleanup_interval": 60,
            },
        },
        "redis": {
            "RATELIMIT_BACKEND": "redis",
            "RATELIMIT_REDIS": {
                "host": "localhost",
                "port": 6379,
                "db": 0,
            },
        },
        "mongodb": {
            "RATELIMIT_BACKEND": "mongodb",
            "RATELIMIT_MONGODB": {
                "host": "localhost",
                "port": 27017,
                "db": "test",
            },
        },
        "database": {
            "RATELIMIT_BACKEND": "database",
            "RATELIMIT_DATABASE": {
                "cleanup_threshold": 1000,
            },
        },
    }

    settings = base_settings.get(backend_type, {})
    settings.update(overrides)
    return settings


class AlgorithmTestMixin:
    """
    Mixin for algorithm tests that provides common algorithm testing patterns.

    This eliminates duplicate algorithm testing code across test files.
    """

    def assert_algorithm_respects_limits(
        self, algorithm, backend, key: str, limit: int, period: int
    ):
        """Assert that algorithm respects rate limits."""
        # Should allow up to limit requests
        for i in range(limit):
            is_allowed, metadata = algorithm.is_allowed(backend, key, limit, period)
            self.assertTrue(is_allowed, f"Request {i+1} should be allowed")
            # Allow for floating point precision issues
            expected_remaining = limit - i - 1
            self.assertAlmostEqual(
                metadata["tokens_remaining"], expected_remaining, places=1
            )

        # Next request should be denied
        is_allowed, metadata = algorithm.is_allowed(backend, key, limit, period)
        self.assertFalse(is_allowed, "Request beyond limit should be denied")

    def assert_algorithm_metadata_format(self, metadata: Dict[str, Any]):
        """Assert that algorithm metadata has expected format."""
        required_fields = ["tokens_remaining", "tokens_requested", "bucket_size"]
        for field in required_fields:
            self.assertIn(field, metadata, f"Metadata missing field: {field}")
            self.assertIsInstance(metadata[field], (int, float))

    def assert_algorithm_refill_behavior(
        self, algorithm, backend, key: str, limit: int, period: int
    ):
        """Assert that algorithm refills tokens correctly."""
        # Consume all tokens
        for _ in range(limit):
            algorithm.is_allowed(backend, key, limit, period)

        # Should be denied
        is_allowed, _ = algorithm.is_allowed(backend, key, limit, period)
        self.assertFalse(is_allowed)

        # Mock time passage
        import time

        current_time = time.time()
        with patch("time.time") as mock_time:
            mock_time.return_value = current_time + period

            # Should be allowed again after refill
            is_allowed, metadata = algorithm.is_allowed(backend, key, limit, period)
            self.assertTrue(is_allowed, "Should be allowed after refill period")


class PerformanceTestMixin:
    """
    Mixin for performance tests that provides common performance testing patterns.

    This eliminates duplicate performance testing code across test files.
    """

    def assert_performance_under_load(
        self, operation_func, max_operations: int = 1000, max_time: float = 1.0
    ):
        """Assert that operation performs well under load."""
        start_time = time.time()

        for i in range(max_operations):
            operation_func()

        end_time = time.time()
        duration = end_time - start_time

        self.assertLess(
            duration,
            max_time,
            f"Operation took {duration:.2f}s for {max_operations} operations, "
            f"expected < {max_time}s",
        )

    def assert_memory_usage_reasonable(self, backend, max_memory_mb: float = 10.0):
        """Assert that backend memory usage is reasonable."""
        if hasattr(backend, "get_stats"):
            stats = backend.get_stats()
            if "memory_usage" in stats:
                memory_mb = stats["memory_usage"] / (1024 * 1024)
                self.assertLess(
                    memory_mb,
                    max_memory_mb,
                    f"Memory usage {memory_mb:.2f}MB exceeds limit {max_memory_mb}MB",
                )


class ErrorHandlingTestMixin:
    """
    Mixin for error handling tests that provides common error testing patterns.

    This eliminates duplicate error handling code across test files.
    """

    def assert_graceful_error_handling(self, operation_func, expected_exception=None):
        """Assert that operation handles errors gracefully."""
        if expected_exception:
            with self.assertRaises(expected_exception):
                operation_func()
        else:
            # Should not raise any exception
            try:
                operation_func()
            except Exception as e:
                self.fail(f"Operation raised unexpected exception: {e}")

    def assert_backend_recovery(self, backend, operation_func):
        """Assert that backend can recover from failures."""
        # This is a placeholder for backend-specific recovery testing
        # Subclasses should implement specific recovery scenarios


# Utility functions for common test patterns


def create_expired_data(backend, key: str, hours_ago: int = 2):
    """Create expired data for testing cleanup functionality."""
    # This is a placeholder - implementation depends on backend type


def wait_for_expiration(seconds: float = 1.1):
    """Wait for data to expire in tests."""
    time.sleep(seconds)


def assert_cleanup_effectiveness(test_case, backend, key: str):
    """Assert that cleanup removes expired data."""
    # Create some data
    backend.incr(key, 1)  # Short expiry

    # Wait for expiration
    wait_for_expiration()

    # Trigger cleanup
    if hasattr(backend, "cleanup_expired"):
        backend.cleanup_expired()
    elif hasattr(backend, "_cleanup_if_needed"):
        backend._cleanup_if_needed()

    # Verify cleanup
    count = backend.get_count(key)
    test_case.assertEqual(count, 0, "Expired data should be cleaned up")


def generate_test_keys(count: int = 10, prefix: str = "test") -> List[str]:
    """Generate test keys for testing."""
    return [f"{prefix}:{i}" for i in range(count)]


def run_concurrent_operations(
    operation_func, num_threads: int = 5, operations_per_thread: int = 10
):
    """Run concurrent operations for testing thread safety."""
    import threading

    results = []
    errors = []

    def worker():
        try:
            for _ in range(operations_per_thread):
                result = operation_func()
                results.append(result)
        except Exception as e:
            errors.append(e)

    threads = []
    for _ in range(num_threads):
        thread = threading.Thread(target=worker)
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    return results, errors


def create_test_user(
    username="testuser", email="test@example.com", password="testpass123"
):
    """Create a test user with default credentials."""
    from django.contrib.auth.models import User

    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
    )


def create_test_staff_user(
    username="staffuser", email="staff@example.com", password="testpass123"
):
    """Create a staff test user with default credentials."""
    from django.contrib.auth.models import User

    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        is_staff=True,
    )


def create_test_superuser(
    username="superuser", email="super@example.com", password="testpass123"
):
    """Create a superuser test user with default credentials."""
    from django.contrib.auth.models import User

    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        is_staff=True,
        is_superuser=True,
    )


def create_test_request(factory, path="/", method="GET", user=None, **_kwargs):
    """Create a test request with optional user authentication."""
    if method.upper() == "GET":
        request = factory.get(path, **_kwargs)
    elif method.upper() == "POST":
        request = factory.post(path, **_kwargs)
    elif method.upper() == "PUT":
        request = factory.put(path, **_kwargs)
    elif method.upper() == "DELETE":
        request = factory.delete(path, **_kwargs)
    else:
        request = factory.get(path, **_kwargs)

    if user:
        request.user = user
    else:
        from django.contrib.auth.models import AnonymousUser

        request.user = AnonymousUser()

    return request
