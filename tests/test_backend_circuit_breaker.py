"""
Integration tests for circuit breaker with backend implementations.

This module tests circuit breaker integration with actual backend
implementations to ensure the circuit breaker works in real scenarios.
"""

import time
from unittest.mock import patch

import pytest

from django_smart_ratelimit import (
    BaseBackend,
    CircuitBreakerError,
    MemoryBackend,
    circuit_breaker_registry,
)


@pytest.fixture(autouse=True)
def cleanup_circuit_breaker_registry():
    """Clean up circuit breaker registry before and after each test."""
    circuit_breaker_registry.reset_all()
    # Clear the registry completely
    circuit_breaker_registry._breakers.clear()
    yield
    circuit_breaker_registry.reset_all()
    circuit_breaker_registry._breakers.clear()


class TestBackendCircuitBreakerIntegration:
    """Test circuit breaker integration with backends."""

    def test_memory_backend_with_circuit_breaker(self):
        """Test memory backend with circuit breaker enabled."""
        backend = MemoryBackend(enable_circuit_breaker=True)

        # Test successful operations
        assert backend.incr_with_circuit_breaker("test_key", 60) == 1
        assert backend.incr_with_circuit_breaker("test_key", 60) == 2
        assert backend.get_count_with_circuit_breaker("test_key") == 2

        # Check circuit breaker status
        status = backend.get_circuit_breaker_status()
        assert status is not None
        assert status["state"] == "closed"
        assert status["failure_count"] == 0

    def test_backend_circuit_breaker_failure_simulation(self):
        """Test circuit breaker behavior when backend fails."""
        backend = MemoryBackend(
            enable_circuit_breaker=True,
            circuit_breaker_config={
                "failure_threshold": 2,
                "recovery_timeout": 0.1,
                "expected_exception": ConnectionError,  # Specify the expected exception type
            },
        )

        # Mock the incr method to simulate failures
        original_incr = backend.incr

        def failing_incr(*args, **kwargs):
            raise ConnectionError("Backend unavailable")

        backend.incr = failing_incr

        # Trigger failures to open circuit
        with pytest.raises(ConnectionError):
            backend.incr_with_circuit_breaker("test_key", 60)
        with pytest.raises(ConnectionError):
            backend.incr_with_circuit_breaker("test_key", 60)

        # Circuit should be open now
        status = backend.get_circuit_breaker_status()
        assert status["state"] == "open"

        # Subsequent calls should be blocked
        with pytest.raises(CircuitBreakerError):
            backend.incr_with_circuit_breaker("test_key", 60)

        # Restore original method and wait for recovery
        backend.incr = original_incr
        time.sleep(0.2)  # Wait for recovery timeout

        # Should work again
        result = backend.incr_with_circuit_breaker("test_key", 60)
        assert result == 1  # New key since we're using memory backend

    def test_backend_without_circuit_breaker(self):
        """Test backend without circuit breaker enabled."""
        backend = MemoryBackend(enable_circuit_breaker=False)

        # Test successful operations
        assert backend.incr("test_key", 60) == 1
        assert backend.get_count("test_key") == 1

        # Circuit breaker should not be available
        assert backend.get_circuit_breaker_status() is None
        assert not backend.is_circuit_breaker_enabled()

    def test_backend_health_status(self):
        """Test backend health status reporting."""
        backend = MemoryBackend(enable_circuit_breaker=True)

        health_status = backend.get_backend_health_status()

        assert "backend_class" in health_status
        assert health_status["circuit_breaker_enabled"] is True
        assert health_status["circuit_breaker_available"] is True
        assert "circuit_breaker" in health_status

    def test_circuit_breaker_manual_reset(self):
        """Test manual reset of backend circuit breaker."""
        # Create a very simple test with a custom configuration
        custom_config = {
            "failure_threshold": 1,  # Only need 1 failure to open
            "expected_exception": Exception,
        }

        backend = MemoryBackend(
            enable_circuit_breaker=True, circuit_breaker_config=custom_config
        )

        # Verify the configuration was applied
        status = backend.get_circuit_breaker_status()
        assert (
            status["failure_threshold"] == 1
        ), f"Expected threshold 1, got {status['failure_threshold']}"

        # Store original method
        backend.incr

        # Mock failure
        def failing_incr(*args, **kwargs):
            raise Exception("Test failure")

        backend.incr = failing_incr

        # Trigger failure
        with pytest.raises(Exception):
            backend.incr_with_circuit_breaker("test_key", 60)

        # Circuit should be open now
        status = backend.get_circuit_breaker_status()
        assert (
            status["state"] == "open"
        ), f"Expected open, got {status['state']}. Status: {status}"

        # Manual reset
        backend.reset_circuit_breaker()

        # Circuit should be closed
        status = backend.get_circuit_breaker_status()
        assert status["state"] == "closed"

    def test_circuit_breaker_with_token_bucket(self):
        """Test circuit breaker with token bucket operations."""
        backend = MemoryBackend(enable_circuit_breaker=True)

        # Test token bucket operation with circuit breaker
        # Since MemoryBackend implements token bucket, this should work
        try:
            result, metadata = backend.token_bucket_check_with_circuit_breaker(
                "bucket_key", 10, 1.0, 10, 1
            )
            # If implementation exists, result should be valid
            assert isinstance(result, bool)
            assert isinstance(metadata, dict)
        except NotImplementedError:
            # If not implemented, that's also fine for this test
            pytest.skip("Token bucket not implemented in MemoryBackend")

    def test_circuit_breaker_config_from_backend_init(self):
        """Test custom circuit breaker configuration passed to backend."""
        custom_config = {
            "failure_threshold": 10,
            "recovery_timeout": 30,
            "exponential_backoff_multiplier": 3.0,
        }

        backend = MemoryBackend(
            enable_circuit_breaker=True, circuit_breaker_config=custom_config
        )

        status = backend.get_circuit_breaker_status()
        # The configuration should use the custom values
        assert status["failure_threshold"] == 10

    @patch("django_smart_ratelimit.backends.base.CIRCUIT_BREAKER_AVAILABLE", False)
    def test_backend_without_circuit_breaker_available(self):
        """Test backend behavior when circuit breaker is not available."""
        backend = MemoryBackend(enable_circuit_breaker=True)

        # Should still work but without circuit breaker
        assert backend.incr("test_key", 60) == 1
        assert backend.get_circuit_breaker_status() is None
        assert not backend.is_circuit_breaker_enabled()

        health_status = backend.get_backend_health_status()
        assert health_status["circuit_breaker_available"] is False


class MockFailingBackend(BaseBackend):
    """Mock backend that always fails for testing."""

    def __init__(self, **kwargs):
        """Initialize the failing backend."""
        super().__init__(**kwargs)
        self.call_count = 0

    def incr(self, key: str, period: int) -> int:
        self.call_count += 1
        raise ConnectionError(f"Backend failure #{self.call_count}")

    def reset(self, key: str) -> None:
        raise ConnectionError("Backend failure")

    def get_count(self, key: str) -> int:
        raise ConnectionError("Backend failure")

    def get_reset_time(self, key: str) -> int:
        raise ConnectionError("Backend failure")


class TestFailingBackendCircuitBreaker:
    """Test circuit breaker with consistently failing backend."""

    def test_failing_backend_opens_circuit(self):
        """Test that consistently failing backend opens circuit breaker."""
        backend = MockFailingBackend(
            enable_circuit_breaker=True,
            circuit_breaker_config={"failure_threshold": 3, "recovery_timeout": 0.1},
        )

        # First few calls should fail and reach threshold
        for i in range(3):
            with pytest.raises(ConnectionError):
                backend.incr_with_circuit_breaker("test_key", 60)

        # Circuit should be open now
        status = backend.get_circuit_breaker_status()
        assert status["state"] == "open"
        assert status["failure_count"] == 3

        # Next calls should be blocked by circuit breaker
        with pytest.raises(CircuitBreakerError):
            backend.incr_with_circuit_breaker("test_key", 60)

        # Backend should not have been called again
        assert backend.call_count == 3

    def test_failing_backend_recovery_attempt(self):
        """Test circuit breaker recovery attempt with failing backend."""
        backend = MockFailingBackend(
            enable_circuit_breaker=True,
            circuit_breaker_config={"failure_threshold": 2, "recovery_timeout": 0.1},
        )

        # Open the circuit
        for i in range(2):
            with pytest.raises(ConnectionError):
                backend.incr_with_circuit_breaker("test_key", 60)

        assert backend.get_circuit_breaker_status()["state"] == "open"

        # Wait for recovery timeout but not enough for exponential backoff
        time.sleep(0.15)  # Slightly more than initial timeout

        # Next call should be blocked because circuit should still be open
        # due to exponential backoff after consecutive failures
        with pytest.raises(CircuitBreakerError):
            backend.incr_with_circuit_breaker("test_key", 60)

        # Circuit should be open
        assert backend.get_circuit_breaker_status()["state"] == "open"


class MockRecoveringBackend(BaseBackend):
    """Mock backend that fails initially but then recovers."""

    def __init__(self, fail_count=3, **kwargs):
        """Initialize the recovering backend with configurable failure count."""
        super().__init__(**kwargs)
        self.call_count = 0
        self.fail_count = fail_count

    def incr(self, key: str, period: int) -> int:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise ConnectionError(f"Backend failure #{self.call_count}")
        return self.call_count - self.fail_count

    def reset(self, key: str) -> None:
        pass

    def get_count(self, key: str) -> int:
        return max(0, self.call_count - self.fail_count)

    def get_reset_time(self, key: str) -> int:
        return None


class TestRecoveringBackendCircuitBreaker:
    """Test circuit breaker with backend that recovers."""

    def test_recovering_backend_closes_circuit(self):
        """Test that recovering backend closes circuit breaker."""
        backend = MockRecoveringBackend(
            fail_count=2,
            enable_circuit_breaker=True,
            circuit_breaker_config={"failure_threshold": 2, "recovery_timeout": 0.1},
        )

        # Fail enough times to open circuit
        for i in range(2):
            with pytest.raises(ConnectionError):
                backend.incr_with_circuit_breaker("test_key", 60)

        assert backend.get_circuit_breaker_status()["state"] == "open"

        # Wait for recovery timeout
        time.sleep(0.2)

        # Next call should succeed and close circuit
        result = backend.incr_with_circuit_breaker("test_key", 60)
        assert result == 1

        # Circuit should be closed
        assert backend.get_circuit_breaker_status()["state"] == "closed"

        # Subsequent calls should work
        result = backend.incr_with_circuit_breaker("test_key", 60)
        assert result == 2
