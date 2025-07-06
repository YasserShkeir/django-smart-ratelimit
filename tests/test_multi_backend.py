"""Tests for multi-backend support."""

import time
from typing import Optional
from unittest.mock import patch

import pytest

from django_smart_ratelimit.backends.base import BaseBackend
from django_smart_ratelimit.backends.factory import BackendFactory
from django_smart_ratelimit.backends.multi import BackendHealthChecker, MultiBackend


class MockBackend(BaseBackend):
    """Mock backend for testing."""

    def __init__(self, fail_health_check=False, fail_operations=False, **kwargs):
        """Initialize mock backend."""
        self.fail_health_check = fail_health_check
        self.fail_operations = fail_operations
        self.operation_calls = []

    def incr(self, key: str, period: int) -> int:
        """Mock incr method."""
        self.operation_calls.append(("incr", key, period))
        if self.fail_operations:
            raise Exception("Mock backend operation failed")
        return 1

    def get_count(self, key: str) -> int:
        """Mock get_count method."""
        self.operation_calls.append(("get_count", key))
        if self.fail_operations:
            raise Exception("Mock backend operation failed")
        return 1

    def get_reset_time(self, key: str) -> Optional[int]:
        """Mock get_reset_time method."""
        self.operation_calls.append(("get_reset_time", key))
        if self.fail_operations:
            raise Exception("Mock backend operation failed")
        return int(time.time()) + 3600

    def reset(self, key: str) -> None:
        """Mock reset method."""
        self.operation_calls.append(("reset", key))
        if self.fail_operations:
            raise Exception("Mock backend operation failed")

    def increment(self, key: str, window_seconds: int, limit: int):
        """Mock increment method."""
        self.operation_calls.append(("increment", key, window_seconds, limit))
        if self.fail_operations:
            raise Exception("Mock backend operation failed")
        return 1, limit - 1

    def cleanup_expired(self):
        """Mock cleanup_expired method."""
        self.operation_calls.append(("cleanup_expired",))
        if self.fail_operations:
            raise Exception("Mock backend operation failed")
        return 10


class TestBackendFactory:
    """Test backend factory functionality."""

    def test_get_backend_class_valid_path(self):
        """Test getting backend class with valid path."""
        backend_class = BackendFactory.get_backend_class(
            "django_smart_ratelimit.backends.memory.MemoryBackend"
        )
        assert backend_class.__name__ == "MemoryBackend"

    def test_get_backend_class_invalid_path(self):
        """Test getting backend class with invalid path."""
        with pytest.raises(ImportError):
            BackendFactory.get_backend_class("nonexistent.backend.Class")

    def test_get_backend_class_invalid_class(self):
        """Test getting backend class with invalid class name."""
        with pytest.raises(AttributeError):
            BackendFactory.get_backend_class(
                "django_smart_ratelimit.backends.memory.NonExistentClass"
            )

    def test_create_backend(self):
        """Test creating backend instance."""
        backend = BackendFactory.create_backend(
            "django_smart_ratelimit.backends.memory.MemoryBackend"
        )
        assert backend.__class__.__name__ == "MemoryBackend"

    def test_create_backend_with_config(self):
        """Test creating backend instance with configuration."""
        backend = BackendFactory.create_backend(
            "django_smart_ratelimit.backends.memory.MemoryBackend",
        )
        # Memory backend reads from settings, so we can't test custom config here
        assert backend.__class__.__name__ == "MemoryBackend"

    def test_backend_cache(self):
        """Test that backend classes are cached."""
        # Clear cache first
        BackendFactory.clear_cache()

        # First call should load and cache
        backend_class1 = BackendFactory.get_backend_class(
            "django_smart_ratelimit.backends.memory.MemoryBackend"
        )

        # Second call should use cache
        backend_class2 = BackendFactory.get_backend_class(
            "django_smart_ratelimit.backends.memory.MemoryBackend"
        )

        assert backend_class1 is backend_class2

    def test_clear_cache(self):
        """Test clearing backend cache."""
        # Load a backend class
        BackendFactory.get_backend_class(
            "django_smart_ratelimit.backends.memory.MemoryBackend"
        )
        assert BackendFactory._backend_cache

        # Clear cache
        BackendFactory.clear_cache()
        assert not BackendFactory._backend_cache

    @patch("django_smart_ratelimit.backends.factory.settings")
    def test_create_from_settings_default(self, mock_settings):
        """Test creating backend from settings with default."""
        mock_settings.RATELIMIT_BACKEND = None
        mock_settings.RATELIMIT_BACKEND_CONFIG = {}

        with patch.object(BackendFactory, "create_backend") as mock_create:
            BackendFactory.create_from_settings()
            mock_create.assert_called_once_with(
                "django_smart_ratelimit.backends.redis_backend.RedisBackend"
            )

    @patch("django_smart_ratelimit.backends.factory.settings")
    def test_create_from_settings_custom(self, mock_settings):
        """Test creating backend from settings with custom configuration."""
        mock_settings.RATELIMIT_BACKEND = "custom.backend.Class"
        mock_settings.RATELIMIT_BACKEND_CONFIG = {"key": "value"}

        with patch.object(BackendFactory, "create_backend") as mock_create:
            BackendFactory.create_from_settings()
            mock_create.assert_called_once_with("custom.backend.Class", key="value")


class TestBackendHealthChecker:
    """Test backend health checker functionality."""

    def test_health_check_healthy_backend(self):
        """Test health check with healthy backend."""
        backend = MockBackend()
        checker = BackendHealthChecker(check_interval=1)

        assert checker.is_healthy("test_backend", backend)

    def test_health_check_unhealthy_backend(self):
        """Test health check with unhealthy backend."""
        backend = MockBackend(fail_operations=True)
        checker = BackendHealthChecker(check_interval=1)

        assert not checker.is_healthy("test_backend", backend)

    def test_health_check_caching(self):
        """Test that health check results are cached."""
        backend = MockBackend()
        checker = BackendHealthChecker(check_interval=10)

        # First check
        result1 = checker.is_healthy("test_backend", backend)
        call_count1 = len(backend.operation_calls)

        # Second check (should use cache)
        result2 = checker.is_healthy("test_backend", backend)
        call_count2 = len(backend.operation_calls)

        assert result1 == result2
        assert call_count1 == call_count2  # No additional calls

    def test_health_check_cache_expiry(self):
        """Test that health check cache expires."""
        backend = MockBackend()
        checker = BackendHealthChecker(check_interval=0.1)

        # First check
        checker.is_healthy("test_backend", backend)
        call_count1 = len(backend.operation_calls)

        # Wait for cache to expire
        time.sleep(0.2)

        # Second check (should not use cache)
        checker.is_healthy("test_backend", backend)
        call_count2 = len(backend.operation_calls)

        assert call_count2 > call_count1  # Additional calls made


class TestMultiBackend:
    """Test multi-backend functionality."""

    def test_init_with_backends(self):
        """Test initializing multi-backend with backend configurations."""
        config = {
            "backends": [
                {
                    "name": "memory1",
                    "backend": "django_smart_ratelimit.backends.memory.MemoryBackend",
                    "config": {},
                },
                {
                    "name": "memory2",
                    "backend": "django_smart_ratelimit.backends.memory.MemoryBackend",
                    "config": {},
                },
            ]
        }

        multi_backend = MultiBackend(**config)
        assert len(multi_backend.backends) == 2
        assert multi_backend.backends[0][0] == "memory1"
        assert multi_backend.backends[1][0] == "memory2"

    def test_init_empty_backends(self):
        """Test initializing multi-backend with empty backend list."""
        with pytest.raises(ValueError):
            MultiBackend(backends=[])

    def test_init_invalid_backend(self):
        """Test initializing multi-backend with invalid backend."""
        config = {
            "backends": [{"name": "invalid", "backend": "nonexistent.backend.Class"}]
        }

        with pytest.raises(ValueError):
            MultiBackend(**config)

    def test_first_healthy_strategy(self):
        """Test first_healthy fallback strategy."""
        # Create mock backends
        backend1 = MockBackend(fail_operations=True)
        backend2 = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.side_effect = [backend1, backend2]

            config = {
                "backends": [
                    {"name": "backend1", "backend": "mock.Backend1"},
                    {"name": "backend2", "backend": "mock.Backend2"},
                ],
                "fallback_strategy": "first_healthy",
            }

            multi_backend = MultiBackend(**config)

            # Should use backend2 since backend1 fails
            count = multi_backend.get_count("test_key")
            assert count == 1
            assert len(backend1.operation_calls) >= 1  # Health check
            assert len(backend2.operation_calls) >= 2  # Health check + actual call

    def test_round_robin_strategy(self):
        """Test round_robin fallback strategy."""
        # Create mock backends
        backend1 = MockBackend()
        backend2 = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.side_effect = [backend1, backend2]

            config = {
                "backends": [
                    {"name": "backend1", "backend": "mock.Backend1"},
                    {"name": "backend2", "backend": "mock.Backend2"},
                ],
                "fallback_strategy": "round_robin",
            }

            multi_backend = MultiBackend(**config)

            # First call should use backend1
            result1 = multi_backend.get_count("test_key")

            # Second call should use backend2
            result2 = multi_backend.get_count("test_key")

            # Both calls should return 1
            assert result1 == 1
            assert result2 == 1

            # At least one backend should have been called
            total_calls = len(backend1.operation_calls) + len(backend2.operation_calls)
            assert total_calls >= 2

    def test_all_backends_fail(self):
        """Test behavior when all backends fail."""
        # Create mock backends that fail
        backend1 = MockBackend(fail_operations=True)
        backend2 = MockBackend(fail_operations=True)

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.side_effect = [backend1, backend2]

            config = {
                "backends": [
                    {"name": "backend1", "backend": "mock.Backend1"},
                    {"name": "backend2", "backend": "mock.Backend2"},
                ]
            }

            multi_backend = MultiBackend(**config)

            # Should raise exception when all backends fail
            with pytest.raises(Exception):
                multi_backend.get_count("test_key")

    def test_increment_with_fallback(self):
        """Test increment method with fallback."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {"backends": [{"name": "backend1", "backend": "mock.Backend1"}]}

            multi_backend = MultiBackend(**config)
            count, remaining = multi_backend.increment("test_key", 60, 10)

            assert count == 1
            assert remaining == 9
            assert ("increment", "test_key", 60, 10) in backend.operation_calls

    def test_reset_with_fallback(self):
        """Test reset method with fallback."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {"backends": [{"name": "backend1", "backend": "mock.Backend1"}]}

            multi_backend = MultiBackend(**config)
            multi_backend.reset("test_key")

            assert ("reset", "test_key") in backend.operation_calls

    def test_cleanup_expired_with_fallback(self):
        """Test cleanup_expired method with fallback."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {"backends": [{"name": "backend1", "backend": "mock.Backend1"}]}

            multi_backend = MultiBackend(**config)
            cleaned = multi_backend.cleanup_expired()

            assert cleaned == 10
            assert ("cleanup_expired",) in backend.operation_calls

    def test_get_backend_status(self):
        """Test getting backend status."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {"backends": [{"name": "backend1", "backend": "mock.Backend1"}]}

            multi_backend = MultiBackend(**config)
            status = multi_backend.get_backend_status()

            assert "backend1" in status
            assert status["backend1"]["healthy"] is True
            assert status["backend1"]["backend_class"] == "MockBackend"

    def test_get_stats(self):
        """Test getting backend statistics."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {
                "backends": [{"name": "backend1", "backend": "mock.Backend1"}],
                "fallback_strategy": "first_healthy",
            }

            multi_backend = MultiBackend(**config)
            stats = multi_backend.get_stats()

            assert stats["total_backends"] == 1
            assert stats["healthy_backends"] == 1
            assert stats["fallback_strategy"] == "first_healthy"
            assert "backends" in stats

    def test_health_check_configuration(self):
        """Test health check configuration."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {
                "backends": [{"name": "backend1", "backend": "mock.Backend1"}],
                "health_check_interval": 60,
                "health_check_timeout": 10,
            }

            multi_backend = MultiBackend(**config)

            assert multi_backend.health_checker.check_interval == 60
            assert multi_backend.health_checker.timeout == 10

    def test_backend_name_defaults_to_backend_path(self):
        """Test that backend name defaults to backend path if not provided."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {"backends": [{"backend": "mock.Backend1"}]}  # No name provided

            multi_backend = MultiBackend(**config)
            assert len(multi_backend.backends) == 1
            assert multi_backend.backends[0][0] == "mock.Backend1"

    def test_backend_health_recovery(self):
        """Test that backends can recover from unhealthy state."""
        backend = MockBackend(fail_operations=True)

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {
                "backends": [{"name": "backend1", "backend": "mock.Backend1"}],
                "health_check_interval": 0.1,
            }

            multi_backend = MultiBackend(**config)

            # First call should fail
            with pytest.raises(Exception):
                multi_backend.get_count("test_key")

            # Make backend healthy again
            backend.fail_operations = False

            # Wait for health check to expire
            time.sleep(0.2)

            # Now it should work
            count = multi_backend.get_count("test_key")
            assert count == 1

    def test_get_reset_time_with_fallback(self):
        """Test get_reset_time method with fallback."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {"backends": [{"name": "backend1", "backend": "mock.Backend1"}]}

            multi_backend = MultiBackend(**config)
            reset_time = multi_backend.get_reset_time("test_key")

            assert reset_time is not None
            assert reset_time > int(time.time())
            assert ("get_reset_time", "test_key") in backend.operation_calls

    def test_incr_method_with_fallback(self):
        """Test incr method with fallback."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {"backends": [{"name": "backend1", "backend": "mock.Backend1"}]}

            multi_backend = MultiBackend(**config)
            count = multi_backend.incr("test_key", 60)

            assert count == 1
            assert ("incr", "test_key", 60) in backend.operation_calls

    def test_mixed_healthy_unhealthy_backends(self):
        """Test behavior with mix of healthy and unhealthy backends."""
        backend1 = MockBackend(fail_operations=True)
        backend2 = MockBackend()
        backend3 = MockBackend(fail_operations=True)

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.side_effect = [backend1, backend2, backend3]

            config = {
                "backends": [
                    {"name": "backend1", "backend": "mock.Backend1"},
                    {"name": "backend2", "backend": "mock.Backend2"},
                    {"name": "backend3", "backend": "mock.Backend3"},
                ],
                "fallback_strategy": "first_healthy",
            }

            multi_backend = MultiBackend(**config)

            # Should use backend2 (the healthy one)
            count = multi_backend.get_count("test_key")
            assert count == 1

            # Check status
            status = multi_backend.get_backend_status()
            assert not status["backend1"]["healthy"]
            assert status["backend2"]["healthy"]
            assert not status["backend3"]["healthy"]

    def test_backend_config_missing_backend_key(self):
        """Test handling of backend config without 'backend' key."""
        config = {"backends": [{"name": "invalid"}]}  # Missing 'backend' key

        # Should not raise exception during init, but should have no backends
        with pytest.raises(ValueError):
            MultiBackend(**config)

    def test_legacy_methods_compatibility(self):
        """Test that legacy methods work with multi-backend."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {"backends": [{"name": "backend1", "backend": "mock.Backend1"}]}

            multi_backend = MultiBackend(**config)

            # Test get_count_with_window (should delegate to get_count)
            count = multi_backend.get_count_with_window("test_key", 60)
            assert count == 1
            # Should call get_count with just the key (window_seconds is ignored)
            assert ("get_count", "test_key") in backend.operation_calls

    def test_error_logging_on_backend_failure(self):
        """Test that backend failures are properly logged."""
        backend1 = MockBackend(fail_operations=True)
        backend2 = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.side_effect = [backend1, backend2]

            config = {
                "backends": [
                    {"name": "backend1", "backend": "mock.Backend1"},
                    {"name": "backend2", "backend": "mock.Backend2"},
                ]
            }

            multi_backend = MultiBackend(**config)

            # This should work but log warnings for backend1
            with patch("django_smart_ratelimit.backends.multi.logger") as mock_logger:
                count = multi_backend.get_count("test_key")
                assert count == 1
                # Should have logged a warning for backend1 failure
                mock_logger.warning.assert_called()

    def test_round_robin_with_failed_backends(self):
        """Test round-robin strategy with some failed backends."""
        backend1 = MockBackend(fail_operations=True)
        backend2 = MockBackend()
        backend3 = MockBackend(fail_operations=True)

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.side_effect = [backend1, backend2, backend3]

            config = {
                "backends": [
                    {"name": "backend1", "backend": "mock.Backend1"},
                    {"name": "backend2", "backend": "mock.Backend2"},
                    {"name": "backend3", "backend": "mock.Backend3"},
                ],
                "fallback_strategy": "round_robin",
            }

            multi_backend = MultiBackend(**config)

            # Multiple calls should all use backend2 (the only healthy one)
            for _ in range(3):
                count = multi_backend.get_count("test_key")
                assert count == 1

            # Only backend2 should have successful operation calls
            assert len(backend2.operation_calls) >= 3

    def test_all_methods_with_single_backend(self):
        """Test all methods work with single backend configuration."""
        backend = MockBackend()

        with patch.object(BackendFactory, "create_backend") as mock_create:
            mock_create.return_value = backend

            config = {"backends": [{"name": "single", "backend": "mock.Backend"}]}

            multi_backend = MultiBackend(**config)

            # Test all methods
            assert multi_backend.incr("key", 60) == 1
            assert multi_backend.get_count("key") == 1
            assert multi_backend.get_reset_time("key") is not None
            multi_backend.reset("key")
            assert multi_backend.increment("key", 60, 10) == (1, 9)
            assert multi_backend.cleanup_expired() == 10

            # Verify all methods were called
            expected_calls = [
                ("incr", "key", 60),
                ("get_count", "key"),
                ("get_reset_time", "key"),
                ("reset", "key"),
                ("increment", "key", 60, 10),
                ("cleanup_expired",),
            ]

            for expected_call in expected_calls:
                assert expected_call in backend.operation_calls
