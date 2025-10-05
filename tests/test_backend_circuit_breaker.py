"""
Integration tests for circuit breaker with backend implementations.

Focused to avoid duplication with unit-level circuit breaker tests and
backend generic tests.
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
    circuit_breaker_registry._breakers.clear()
    yield
    circuit_breaker_registry.reset_all()
    circuit_breaker_registry._breakers.clear()


class TestBackendCircuitBreakerIntegration:
    """Memory backend + circuit breaker key paths."""

    def test_memory_backend_with_circuit_breaker(self):
        backend = MemoryBackend(enable_circuit_breaker=True)

        assert backend.incr_with_circuit_breaker("test_key", 60) == 1
        assert backend.incr_with_circuit_breaker("test_key", 60) == 2
        assert backend.get_count_with_circuit_breaker("test_key") == 2

        status = backend.get_circuit_breaker_status()
        assert (
            status is not None
            and status["state"] == "closed"
            and status["failure_count"] == 0
        )

    def test_backend_circuit_breaker_failure_simulation(self):
        backend = MemoryBackend(
            enable_circuit_breaker=True,
            circuit_breaker_config={
                "failure_threshold": 2,
                "recovery_timeout": 0.1,
                "expected_exception": ConnectionError,
            },
        )

        original_incr = backend.incr

        def failing_incr(*args, **kwargs):
            raise ConnectionError("Backend unavailable")

        backend.incr = failing_incr

        with pytest.raises(ConnectionError):
            backend.incr_with_circuit_breaker("test_key", 60)
        with pytest.raises(ConnectionError):
            backend.incr_with_circuit_breaker("test_key", 60)

        status = backend.get_circuit_breaker_status()
        assert status["state"] == "open"

        with pytest.raises(CircuitBreakerError):
            backend.incr_with_circuit_breaker("test_key", 60)

        backend.incr = original_incr
        time.sleep(0.2)
        assert backend.incr_with_circuit_breaker("test_key", 60) == 1

    def test_backend_without_circuit_breaker(self):
        backend = MemoryBackend(enable_circuit_breaker=False)
        assert backend.incr("test_key", 60) == 1
        assert backend.get_count("test_key") == 1
        assert backend.get_circuit_breaker_status() is None
        assert not backend.is_circuit_breaker_enabled()

    def test_backend_health_status(self):
        backend = MemoryBackend(enable_circuit_breaker=True)
        health_status = backend.get_backend_health_status()
        assert health_status["circuit_breaker_enabled"] is True
        assert health_status["circuit_breaker_available"] is True
        assert "circuit_breaker" in health_status

    def test_circuit_breaker_manual_reset(self):
        custom_config = {"failure_threshold": 1, "expected_exception": Exception}
        backend = MemoryBackend(
            enable_circuit_breaker=True, circuit_breaker_config=custom_config
        )

        status = backend.get_circuit_breaker_status()
        assert status["failure_threshold"] == 1

        def failing_incr(*args, **kwargs):
            raise Exception("Test failure")

        backend.incr = failing_incr

        with pytest.raises(Exception):
            backend.incr_with_circuit_breaker("test_key", 60)

        assert backend.get_circuit_breaker_status()["state"] == "open"

        backend.reset_circuit_breaker()
        assert backend.get_circuit_breaker_status()["state"] == "closed"

    def test_circuit_breaker_with_token_bucket(self):
        backend = MemoryBackend(enable_circuit_breaker=True)
        try:
            result, metadata = backend.token_bucket_check_with_circuit_breaker(
                "bucket_key", 10, 1.0, 10, 1
            )
            assert isinstance(result, bool)
            assert isinstance(metadata, dict)
        except NotImplementedError:
            pytest.skip("Token bucket not implemented in MemoryBackend")

    @patch("django_smart_ratelimit.backends.base.CIRCUIT_BREAKER_AVAILABLE", False)
    def test_backend_without_circuit_breaker_available(self):
        backend = MemoryBackend(enable_circuit_breaker=True)
        assert backend.incr("test_key", 60) == 1
        assert backend.get_circuit_breaker_status() is None
        assert not backend.is_circuit_breaker_enabled()
        health_status = backend.get_backend_health_status()
        assert health_status["circuit_breaker_available"] is False


class MockFailingBackend(BaseBackend):
    """Mock backend that always fails for testing."""

    def __init__(self, **kwargs):
        """Initialize mock failing backend."""
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
    """Consistently failing backend behavior."""

    def test_failing_backend_opens_circuit(self):
        backend = MockFailingBackend(
            enable_circuit_breaker=True,
            circuit_breaker_config={"failure_threshold": 3, "recovery_timeout": 0.1},
        )

        for _ in range(3):
            with pytest.raises(ConnectionError):
                backend.incr_with_circuit_breaker("test_key", 60)

        status = backend.get_circuit_breaker_status()
        assert status["state"] == "open"
        assert status["failure_count"] == 3

        with pytest.raises(CircuitBreakerError):
            backend.incr_with_circuit_breaker("test_key", 60)
        assert backend.call_count == 3

    def test_failing_backend_recovery_attempt(self):
        backend = MockFailingBackend(
            enable_circuit_breaker=True,
            circuit_breaker_config={"failure_threshold": 2, "recovery_timeout": 0.1},
        )

        for _ in range(2):
            with pytest.raises(ConnectionError):
                backend.incr_with_circuit_breaker("test_key", 60)

        assert backend.get_circuit_breaker_status()["state"] == "open"

        time.sleep(0.15)
        with pytest.raises(CircuitBreakerError):
            backend.incr_with_circuit_breaker("test_key", 60)
        assert backend.get_circuit_breaker_status()["state"] == "open"


class MockRecoveringBackend(BaseBackend):
    """Mock backend that fails initially but then recovers."""

    def __init__(self, fail_count=3, **kwargs):
        """Initialize mock recovering backend with configurable fail count."""
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
    """Backend that recovers closes the circuit again after timeout."""

    def test_recovering_backend_closes_circuit(self):
        backend = MockRecoveringBackend(
            fail_count=2,
            enable_circuit_breaker=True,
            circuit_breaker_config={"failure_threshold": 2, "recovery_timeout": 0.1},
        )

        for _ in range(2):
            with pytest.raises(ConnectionError):
                backend.incr_with_circuit_breaker("test_key", 60)

        assert backend.get_circuit_breaker_status()["state"] == "open"

        time.sleep(0.2)
        assert backend.incr_with_circuit_breaker("test_key", 60) == 1
        assert backend.get_circuit_breaker_status()["state"] == "closed"
        assert backend.incr_with_circuit_breaker("test_key", 60) == 2
