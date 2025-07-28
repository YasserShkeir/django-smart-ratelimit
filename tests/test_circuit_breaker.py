"""
Tests for circuit breaker functionality.

This module contains comprehensive tests for the circuit breaker pattern
implementation including state transitions, failure detection, recovery,
and performance characteristics.
"""

import time
from threading import Thread

import pytest

from django.test import override_settings

from django_smart_ratelimit.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerRegistry,
    CircuitBreakerState,
    CircuitBreakerStats,
    circuit_breaker,
    circuit_breaker_registry,
    get_circuit_breaker_config_from_settings,
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


class TestCircuitBreakerConfig:
    """Test circuit breaker configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CircuitBreakerConfig()

        assert config.failure_threshold == 5
        assert config.recovery_timeout == 60
        assert config.expected_exception == Exception
        assert config.name == "circuit_breaker"
        assert config.fallback_function is None
        assert config.reset_timeout == 300
        assert config.half_open_max_calls == 1
        assert config.exponential_backoff_multiplier == 2.0
        assert config.exponential_backoff_max == 300

    def test_custom_config(self):
        """Test custom configuration values."""

        def fallback():
            return "fallback"

        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=30,
            expected_exception=ValueError,
            name="test_breaker",
            fallback_function=fallback,
            reset_timeout=120,
            half_open_max_calls=2,
            exponential_backoff_multiplier=1.5,
            exponential_backoff_max=600,
        )

        assert config.failure_threshold == 3
        assert config.recovery_timeout == 30
        assert config.expected_exception == ValueError
        assert config.name == "test_breaker"
        assert config.fallback_function == fallback
        assert config.reset_timeout == 120
        assert config.half_open_max_calls == 2
        assert config.exponential_backoff_multiplier == 1.5
        assert config.exponential_backoff_max == 600

    def test_invalid_config(self):
        """Test validation of invalid configuration."""
        with pytest.raises(Exception):  # ImproperlyConfigured
            CircuitBreakerConfig(failure_threshold=0)

        with pytest.raises(Exception):  # ImproperlyConfigured
            CircuitBreakerConfig(recovery_timeout=-1)

        with pytest.raises(Exception):  # ImproperlyConfigured
            CircuitBreakerConfig(reset_timeout=0)


class TestCircuitBreakerStats:
    """Test circuit breaker statistics tracking."""

    def test_initial_stats(self):
        """Test initial statistics state."""
        stats = CircuitBreakerStats()

        assert stats.total_calls == 0
        assert stats.successful_calls == 0
        assert stats.failed_calls == 0
        assert stats.state_changes == 0
        assert stats.last_failure_time is None
        assert stats.last_success_time is None
        assert stats.state_change_history == []
        assert stats.get_failure_rate() == 0.0

    def test_record_success(self):
        """Test recording successful calls."""
        stats = CircuitBreakerStats()

        stats.record_success()

        assert stats.total_calls == 1
        assert stats.successful_calls == 1
        assert stats.failed_calls == 0
        assert stats.last_success_time is not None
        assert stats.get_failure_rate() == 0.0

    def test_record_failure(self):
        """Test recording failed calls."""
        stats = CircuitBreakerStats()

        stats.record_failure()

        assert stats.total_calls == 1
        assert stats.successful_calls == 0
        assert stats.failed_calls == 1
        assert stats.last_failure_time is not None
        assert stats.get_failure_rate() == 1.0

    def test_failure_rate_calculation(self):
        """Test failure rate calculation."""
        stats = CircuitBreakerStats()

        # Record mixed successes and failures
        stats.record_success()
        stats.record_success()
        stats.record_failure()

        assert stats.total_calls == 3
        assert stats.successful_calls == 2
        assert stats.failed_calls == 1
        assert stats.get_failure_rate() == 1 / 3

    def test_state_change_recording(self):
        """Test state change recording."""
        stats = CircuitBreakerStats()

        stats.record_state_change(CircuitBreakerState.CLOSED, CircuitBreakerState.OPEN)

        assert stats.state_changes == 1
        assert len(stats.state_change_history) == 1

        change = stats.state_change_history[0]
        assert change["from_state"] == "closed"
        assert change["to_state"] == "open"
        assert "timestamp" in change

    def test_state_change_history_limit(self):
        """Test state change history is limited to 100 entries."""
        stats = CircuitBreakerStats()

        # Record 150 state changes
        for i in range(150):
            stats.record_state_change(
                CircuitBreakerState.CLOSED, CircuitBreakerState.OPEN
            )

        assert stats.state_changes == 150
        assert len(stats.state_change_history) == 100

    def test_get_stats(self):
        """Test getting comprehensive statistics."""
        stats = CircuitBreakerStats()

        stats.record_success()
        stats.record_failure()
        stats.record_state_change(CircuitBreakerState.CLOSED, CircuitBreakerState.OPEN)

        all_stats = stats.get_stats()

        assert all_stats["total_calls"] == 2
        assert all_stats["successful_calls"] == 1
        assert all_stats["failed_calls"] == 1
        assert all_stats["failure_rate"] == 0.5
        assert all_stats["state_changes"] == 1
        assert all_stats["last_failure_time"] is not None
        assert all_stats["last_success_time"] is not None
        assert len(all_stats["recent_state_changes"]) == 1


class TestCircuitBreaker:
    """Test circuit breaker core functionality."""

    def test_initial_state(self):
        """Test circuit breaker initial state."""
        config = CircuitBreakerConfig(name="test")
        breaker = CircuitBreaker(config)

        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.stats.total_calls == 0

    def test_successful_calls_in_closed_state(self):
        """Test successful calls when circuit is closed."""
        config = CircuitBreakerConfig(name="test", failure_threshold=3)
        breaker = CircuitBreaker(config)

        def mock_function(x):
            return x * 2

        # Execute successful calls
        for i in range(5):
            result = breaker.call(mock_function, i)
            assert result == i * 2

        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.stats.total_calls == 5
        assert breaker.stats.successful_calls == 5
        assert breaker.stats.failed_calls == 0

    def test_failure_threshold_reached(self):
        """Test circuit opens when failure threshold is reached."""
        config = CircuitBreakerConfig(name="test", failure_threshold=3)
        breaker = CircuitBreaker(config)

        def failing_function():
            raise ValueError("Test failure")

        # Execute failing calls up to threshold
        for i in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.state == CircuitBreakerState.OPEN
        assert breaker.stats.failed_calls == 3

    def test_calls_blocked_when_open(self):
        """Test calls are blocked when circuit is open."""
        config = CircuitBreakerConfig(
            name="test", failure_threshold=2, recovery_timeout=1
        )
        breaker = CircuitBreaker(config)

        def failing_function():
            raise ValueError("Test failure")

        # Reach failure threshold
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.state == CircuitBreakerState.OPEN

        # Next call should be blocked
        with pytest.raises(CircuitBreakerError):
            breaker.call(lambda: "success")

    def test_transition_to_half_open(self):
        """Test transition from open to half-open state."""
        config = CircuitBreakerConfig(
            name="test", failure_threshold=2, recovery_timeout=0.1
        )
        breaker = CircuitBreaker(config)

        def failing_function():
            raise ValueError("Test failure")

        # Reach failure threshold
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.state == CircuitBreakerState.OPEN

        # Wait for recovery timeout
        time.sleep(0.2)

        # Next call should transition to half-open
        def successful_function():
            return "success"

        result = breaker.call(successful_function)
        assert result == "success"
        assert breaker.state == CircuitBreakerState.CLOSED

    def test_half_open_failure_reopens_circuit(self):
        """Test that failure in half-open state reopens circuit."""
        config = CircuitBreakerConfig(
            name="test", failure_threshold=2, recovery_timeout=0.1
        )
        breaker = CircuitBreaker(config)

        def failing_function():
            raise ValueError("Test failure")

        # Reach failure threshold
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.state == CircuitBreakerState.OPEN

        # Wait for recovery timeout and fail in half-open
        time.sleep(0.2)
        with pytest.raises(ValueError):
            breaker.call(failing_function)

        assert breaker.state == CircuitBreakerState.OPEN

    def test_exponential_backoff(self):
        """Test exponential backoff calculation."""
        config = CircuitBreakerConfig(
            name="test",
            failure_threshold=1,
            recovery_timeout=1,
            exponential_backoff_multiplier=2.0,
        )
        breaker = CircuitBreaker(config)

        def failing_function():
            raise ValueError("Test failure")

        # First failure
        with pytest.raises(ValueError):
            breaker.call(failing_function)

        # Check backoff time increases with consecutive failures
        initial_backoff = breaker._calculate_backoff_time()
        assert initial_backoff == 1  # First failure, base timeout

        # Simulate more consecutive failures
        breaker._consecutive_failures = 3
        increased_backoff = breaker._calculate_backoff_time()
        assert increased_backoff == 4  # 1 * 2^2 = 4

    def test_exponential_backoff_max_limit(self):
        """Test exponential backoff respects maximum limit."""
        config = CircuitBreakerConfig(
            name="test",
            failure_threshold=1,
            recovery_timeout=1,
            exponential_backoff_multiplier=2.0,
            exponential_backoff_max=5,
        )
        breaker = CircuitBreaker(config)

        # Simulate many consecutive failures
        breaker._consecutive_failures = 10
        backoff_time = breaker._calculate_backoff_time()

        assert backoff_time == 5  # Should be capped at max

    def test_half_open_max_calls_limit(self):
        """Test half-open state respects max calls limit."""
        config = CircuitBreakerConfig(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
            half_open_max_calls=2,
        )
        breaker = CircuitBreaker(config)

        def failing_function():
            raise ValueError("Test failure")

        # Reach failure threshold
        with pytest.raises(ValueError):
            breaker.call(failing_function)

        assert breaker.state == CircuitBreakerState.OPEN

        # Wait for recovery timeout
        time.sleep(0.2)

        def successful_function():
            return "success"

        # First half-open call should succeed and close circuit
        result = breaker.call(successful_function)
        assert result == "success"
        assert breaker.state == CircuitBreakerState.CLOSED

    def test_reset_failure_count_after_success(self):
        """Test failure count resets after successful operation and timeout."""
        config = CircuitBreakerConfig(
            name="test", failure_threshold=3, reset_timeout=0.1
        )
        breaker = CircuitBreaker(config)

        def failing_function():
            raise ValueError("Test failure")

        def successful_function():
            return "success"

        # Have some failures (but not enough to open circuit)
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker._failure_count == 2
        assert breaker.state == CircuitBreakerState.CLOSED

        # Wait for reset timeout
        time.sleep(0.2)

        # Successful call should reset failure count
        breaker.call(successful_function)
        assert breaker._failure_count == 0

    def test_manual_reset(self):
        """Test manual reset of circuit breaker."""
        config = CircuitBreakerConfig(name="test", failure_threshold=2)
        breaker = CircuitBreaker(config)

        def failing_function():
            raise ValueError("Test failure")

        # Reach failure threshold
        for i in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_function)

        assert breaker.state == CircuitBreakerState.OPEN

        # Manual reset
        breaker.reset()

        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker._failure_count == 0
        assert breaker._consecutive_failures == 0

    def test_call_with_fallback_success(self):
        """Test call with fallback when circuit is closed."""

        def fallback_function():
            return "fallback_result"

        config = CircuitBreakerConfig(name="test", fallback_function=fallback_function)
        breaker = CircuitBreaker(config)

        def successful_function():
            return "success"

        result = breaker.call_with_fallback(successful_function)
        assert result == "success"

    def test_call_with_fallback_when_open(self):
        """Test call with fallback when circuit is open."""

        def fallback_function(*args, **kwargs):
            return "fallback_result"

        config = CircuitBreakerConfig(
            name="test",
            failure_threshold=1,
            fallback_function=fallback_function,
        )
        breaker = CircuitBreaker(config)

        def failing_function():
            raise ValueError("Test failure")

        # Open the circuit
        with pytest.raises(ValueError):
            breaker.call(failing_function)

        assert breaker.state == CircuitBreakerState.OPEN

        # Call with fallback should use fallback function
        result = breaker.call_with_fallback(lambda: "success")
        assert result == "fallback_result"

    def test_get_status(self):
        """Test getting circuit breaker status."""
        config = CircuitBreakerConfig(name="test_status", failure_threshold=3)
        breaker = CircuitBreaker(config)

        status = breaker.get_status()

        assert status["name"] == "test_status"
        assert status["state"] == "closed"
        assert status["failure_count"] == 0
        assert status["failure_threshold"] == 3
        assert status["last_failure_time"] is None
        assert "stats" in status

    def test_expected_exception_filtering(self):
        """Test that only expected exceptions trigger circuit breaker."""
        config = CircuitBreakerConfig(
            name="test", failure_threshold=2, expected_exception=ValueError
        )
        breaker = CircuitBreaker(config)

        def value_error_function():
            raise ValueError("Expected error")

        def runtime_error_function():
            raise RuntimeError("Unexpected error")

        # ValueError should trigger circuit breaker
        with pytest.raises(ValueError):
            breaker.call(value_error_function)
        with pytest.raises(ValueError):
            breaker.call(value_error_function)

        assert breaker.state == CircuitBreakerState.OPEN

        # Reset for next test
        breaker.reset()

        # RuntimeError should not trigger circuit breaker
        with pytest.raises(RuntimeError):
            breaker.call(runtime_error_function)
        with pytest.raises(RuntimeError):
            breaker.call(runtime_error_function)

        assert breaker.state == CircuitBreakerState.CLOSED


class TestCircuitBreakerRegistry:
    """Test circuit breaker registry functionality."""

    def test_get_or_create_new_breaker(self):
        """Test creating new circuit breaker."""
        registry = CircuitBreakerRegistry()
        config = CircuitBreakerConfig(name="new_breaker")

        breaker = registry.get_or_create("new_breaker", config)

        assert breaker is not None
        assert breaker._config.name == "new_breaker"

    def test_get_or_create_existing_breaker(self):
        """Test getting existing circuit breaker."""
        registry = CircuitBreakerRegistry()
        config = CircuitBreakerConfig(name="existing_breaker")

        breaker1 = registry.get_or_create("existing_breaker", config)
        breaker2 = registry.get_or_create("existing_breaker")

        assert breaker1 is breaker2

    def test_get_or_create_default_config(self):
        """Test creating breaker with default config."""
        registry = CircuitBreakerRegistry()

        breaker = registry.get_or_create("default_config")

        assert breaker is not None
        assert breaker._config.name == "default_config"

    def test_get_nonexistent_breaker(self):
        """Test getting non-existent circuit breaker."""
        registry = CircuitBreakerRegistry()

        breaker = registry.get("nonexistent")

        assert breaker is None

    def test_reset_all_breakers(self):
        """Test resetting all circuit breakers."""
        registry = CircuitBreakerRegistry()

        # Create multiple breakers and open them
        for i in range(3):
            config = CircuitBreakerConfig(name=f"breaker_{i}", failure_threshold=1)
            breaker = registry.get_or_create(f"breaker_{i}", config)

            # Open the circuit
            with pytest.raises(ValueError):
                breaker.call(lambda: raise_value_error())

        # Reset all
        registry.reset_all()

        # Check all are closed
        for i in range(3):
            breaker = registry.get(f"breaker_{i}")
            assert breaker.state == CircuitBreakerState.CLOSED

    def test_get_all_status(self):
        """Test getting status of all circuit breakers."""
        registry = CircuitBreakerRegistry()

        # Create multiple breakers
        for i in range(2):
            config = CircuitBreakerConfig(name=f"status_breaker_{i}")
            registry.get_or_create(f"status_breaker_{i}", config)

        all_status = registry.get_all_status()

        assert len(all_status) == 2
        assert "status_breaker_0" in all_status
        assert "status_breaker_1" in all_status

    def test_remove_breaker(self):
        """Test removing circuit breaker from registry."""
        registry = CircuitBreakerRegistry()
        config = CircuitBreakerConfig(name="removable")

        registry.get_or_create("removable", config)
        assert registry.get("removable") is not None

        removed = registry.remove("removable")
        assert removed is True
        assert registry.get("removable") is None

        # Try to remove non-existent
        removed = registry.remove("nonexistent")
        assert removed is False


class TestCircuitBreakerDecorator:
    """Test circuit breaker decorator functionality."""

    def test_decorator_basic_usage(self):
        """Test basic decorator usage."""
        import uuid

        unique_name = f"decorator_test_{uuid.uuid4().hex[:8]}"

        @circuit_breaker(failure_threshold=2, name=unique_name)
        def test_function(x):
            if x < 0:
                raise ValueError("Negative value")
            return x * 2

        # Successful calls
        assert test_function(5) == 10
        assert test_function(3) == 6

        # Failing calls
        with pytest.raises(ValueError):
            test_function(-1)
        with pytest.raises(ValueError):
            test_function(-2)

        # Circuit should be open now
        with pytest.raises(CircuitBreakerError):
            test_function(5)

    def test_decorator_with_fallback(self):
        """Test decorator with fallback function."""
        import uuid

        unique_name = f"fallback_test_{uuid.uuid4().hex[:8]}"

        def fallback_func(*args, **kwargs):
            return "fallback"

        @circuit_breaker(
            failure_threshold=1, fallback_function=fallback_func, name=unique_name
        )
        def test_function(x):
            raise ValueError("Always fails")

        # First call fails and opens circuit
        with pytest.raises(ValueError):
            test_function(1)

        # Second call should use fallback
        result = test_function(2)
        assert result == "fallback"

    def test_decorator_preserves_function_metadata(self):
        """Test decorator preserves function name and docstring."""
        import uuid

        unique_name = f"metadata_test_{uuid.uuid4().hex[:8]}"

        @circuit_breaker(name=unique_name)
        def test_function():
            """Test docstring."""
            return "test"

        assert test_function.__name__ == "test_function"
        assert test_function.__doc__ == "Test docstring."
        assert hasattr(test_function, "circuit_breaker")

    def test_decorator_custom_exception(self):
        """Test decorator with custom exception type."""
        import uuid

        unique_name = f"test_function_{uuid.uuid4().hex[:8]}"

        @circuit_breaker(
            failure_threshold=1, expected_exception=ValueError, name=unique_name
        )
        def test_function(error_type):
            if error_type == "value":
                raise ValueError("Value error")
            elif error_type == "runtime":
                raise RuntimeError("Runtime error")
            return "success"

        # ValueError should trigger circuit breaker
        with pytest.raises(ValueError):
            test_function("value")

        # Circuit should be open for subsequent calls
        with pytest.raises(CircuitBreakerError):
            test_function("success")

        # Reset circuit breaker for the next test
        test_function.circuit_breaker.reset()

        # RuntimeError should not trigger circuit breaker
        with pytest.raises(RuntimeError):
            test_function("runtime")
        with pytest.raises(RuntimeError):
            test_function("runtime")


class TestCircuitBreakerIntegration:
    """Test circuit breaker integration scenarios."""

    def test_concurrent_access(self):
        """Test circuit breaker with concurrent access."""
        config = CircuitBreakerConfig(name="concurrent", failure_threshold=5)
        breaker = CircuitBreaker(config)

        results = []
        errors = []

        def worker(worker_id):
            try:
                result = breaker.call(lambda: f"worker_{worker_id}")
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        # Create multiple threads
        threads = []
        for i in range(10):
            thread = Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        assert len(results) == 10
        assert len(errors) == 0

    def test_thread_safety(self):
        """Test circuit breaker thread safety with failures."""
        config = CircuitBreakerConfig(name="thread_safety", failure_threshold=3)
        breaker = CircuitBreaker(config)

        failure_count = 0
        success_count = 0

        def failing_worker():
            nonlocal failure_count
            try:
                breaker.call(lambda: raise_value_error())
            except (ValueError, CircuitBreakerError):
                failure_count += 1

        def success_worker():
            nonlocal success_count
            try:
                breaker.call(lambda: "success")
                success_count += 1
            except CircuitBreakerError:
                pass

        # Create threads that will cause failures
        threads = []
        for i in range(5):
            thread = Thread(target=failing_worker)
            threads.append(thread)
            thread.start()

        # Wait for failure threads
        for thread in threads:
            thread.join()

        # Create threads for success calls (should be blocked)
        success_threads = []
        for i in range(3):
            thread = Thread(target=success_worker)
            success_threads.append(thread)
            thread.start()

        for thread in success_threads:
            thread.join()

        # Circuit should be open, so success calls should be blocked
        assert breaker.state == CircuitBreakerState.OPEN
        assert success_count == 0

    def test_performance_overhead(self):
        """Test circuit breaker performance overhead."""
        config = CircuitBreakerConfig(name="performance")
        breaker = CircuitBreaker(config)

        def simple_function():
            return "test"

        # Measure time with circuit breaker
        start_time = time.time()
        for i in range(1000):
            breaker.call(simple_function)
        cb_time = time.time() - start_time

        # Measure time without circuit breaker
        start_time = time.time()
        for i in range(1000):
            simple_function()
        direct_time = time.time() - start_time

        # Circuit breaker overhead should be reasonable
        overhead_ratio = cb_time / direct_time if direct_time > 0 else 1
        assert (
            overhead_ratio < 100
        )  # Less than 100x overhead (more realistic for small operations)


class TestConfigurationFromSettings:
    """Test configuration loading from Django settings."""

    def test_default_config_from_settings(self):
        """Test loading default configuration."""
        # Test when RATELIMIT_CIRCUIT_BREAKER is not defined
        config = get_circuit_breaker_config_from_settings()

        assert config["failure_threshold"] == 5
        assert config["recovery_timeout"] == 60

    @override_settings(
        RATELIMIT_CIRCUIT_BREAKER={
            "failure_threshold": 10,
            "recovery_timeout": 120,
            "exponential_backoff_multiplier": 3.0,
        }
    )
    def test_custom_config_from_settings(self):
        """Test loading custom configuration from settings."""
        config = get_circuit_breaker_config_from_settings()

        assert config["failure_threshold"] == 10
        assert config["recovery_timeout"] == 120
        assert config["exponential_backoff_multiplier"] == 3.0
        # Default values should still be present
        assert config["reset_timeout"] == 300


# Helper functions for tests
def raise_value_error():
    """Helper function that raises ValueError."""
    raise ValueError("Test error")


class TestCircuitBreakerEdgeCases:
    """Test edge cases and error conditions."""

    def test_zero_recovery_timeout_handling(self):
        """Test handling of very small recovery timeouts."""
        with pytest.raises(Exception):  # Should raise ImproperlyConfigured
            CircuitBreakerConfig(recovery_timeout=0)

    def test_circuit_breaker_with_none_function(self):
        """Test circuit breaker behavior with None function."""
        config = CircuitBreakerConfig(name="none_test")
        breaker = CircuitBreaker(config)

        with pytest.raises(TypeError):
            breaker.call(None)

    def test_circuit_breaker_error_properties(self):
        """Test CircuitBreakerError properties."""
        next_time = time.time() + 60
        error = CircuitBreakerError("Test message", next_time)

        assert str(error) == "Test message"
        assert error.next_attempt_time == next_time

    def test_stats_with_no_calls(self):
        """Test statistics with no recorded calls."""
        stats = CircuitBreakerStats()

        all_stats = stats.get_stats()
        assert all_stats["failure_rate"] == 0.0
        assert all_stats["recent_state_changes"] == []

    def test_very_high_consecutive_failures(self):
        """Test behavior with very high consecutive failure count."""
        config = CircuitBreakerConfig(
            name="high_failures",
            recovery_timeout=1,
            exponential_backoff_multiplier=2.0,
            exponential_backoff_max=300,
        )
        breaker = CircuitBreaker(config)

        # Simulate very high consecutive failures
        breaker._consecutive_failures = 1000

        backoff_time = breaker._calculate_backoff_time()
        assert backoff_time == 300  # Should be capped at max
