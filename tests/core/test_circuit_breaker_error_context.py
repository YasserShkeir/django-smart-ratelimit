import pytest

from django.test import TestCase

from django_smart_ratelimit.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerState,
)


class TestCircuitBreakerErrorContext(TestCase):
    """Test enhanced context in CircuitBreakerError."""

    def test_error_context_in_open_state(self):
        """Test that CircuitBreakerError contains context when OPEN."""
        config = CircuitBreakerConfig(
            name="test_breaker",
            failure_threshold=1,
            recovery_timeout=60,
        )
        cb = CircuitBreaker(config)

        # Force failure to open circuit
        try:
            with cb:
                raise ValueError("Boom")
        except ValueError:
            pass

        assert cb.state == CircuitBreakerState.OPEN

        # Next call should raise CircuitBreakerError with context
        with pytest.raises(CircuitBreakerError) as excinfo:
            with cb:
                pass

        error = excinfo.value
        assert error.breaker_name == "test_breaker"
        assert error.failure_count == 1
        assert error.last_failure_time is not None
        assert error.recovery_time is not None
        assert error.recovery_time > 0  # It's a duration now

        # Check string representation
        assert "retry in" in str(error)

    def test_error_context_in_half_open_state(self):
        """Test that CircuitBreakerError contains context when HALF_OPEN limit exceeded."""
        config = CircuitBreakerConfig(
            name="test_breaker_half_open",
            failure_threshold=1,
            recovery_timeout=60,
            half_open_max_calls=1,
        )
        cb = CircuitBreaker(config)

        # Manually set state to HALF_OPEN and max out calls
        # We need to access protected members via storage for this white-box test
        name = config.name
        cb._storage.set_state(name, CircuitBreakerState.HALF_OPEN.value)

        # Max out calls (increments to 1)
        cb._storage.increment_half_open_calls(name)

        # Set failure count and last failure time
        for _ in range(5):
            cb._storage.increment_failure(name)

        # Call should fail because half_open_max_calls=1 and this is the 2nd call (incrementing to 2)
        with pytest.raises(CircuitBreakerError) as excinfo:
            with cb:
                pass

        error = excinfo.value
        assert error.breaker_name == "test_breaker_half_open"
        assert error.failure_count >= 5
        assert error.last_failure_time is not None
        # When rejected in HALF_OPEN, it triggers standard failure logic in call()
        # which calculates recovery_time.
        assert error.recovery_time is not None
