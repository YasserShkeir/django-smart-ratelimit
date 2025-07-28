"""
Circuit Breaker Pattern implementation for Django Smart Ratelimit.

This module provides circuit breaker functionality to prevent cascading failures
when backends become unavailable or unreliable. The circuit breaker monitors
backend health and automatically switches between CLOSED, OPEN, and HALF_OPEN
states based on failure rates and recovery attempts.
"""

import logging
import time
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, Optional, TypeVar

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Backend failed, requests blocked
    HALF_OPEN = "half_open"  # Testing if backend recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is in OPEN state."""

    def __init__(self, message: str, next_attempt_time: Optional[float] = None):
        """Initialize CircuitBreakerError with message and optional next attempt time."""
        super().__init__(message)
        self.next_attempt_time = next_attempt_time


class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type[Exception] = Exception,
        name: Optional[str] = None,
        fallback_function: Optional[Callable] = None,
        reset_timeout: int = 300,
        half_open_max_calls: int = 1,
        exponential_backoff_multiplier: float = 2.0,
        exponential_backoff_max: int = 300,
    ):
        """
        Initialize circuit breaker configuration.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Time to wait before trying HALF_OPEN state (seconds)
            expected_exception: Exception type that triggers circuit breaker
            name: Name for this circuit breaker (for logging)
            fallback_function: Function to call when circuit is open
            reset_timeout: Time to reset failure count after successful operation
            half_open_max_calls: Max calls allowed in HALF_OPEN state before decision
            exponential_backoff_multiplier: Multiplier for exponential backoff
            exponential_backoff_max: Maximum backoff time (seconds)
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name or "circuit_breaker"
        self.fallback_function = fallback_function
        self.reset_timeout = reset_timeout
        self.half_open_max_calls = half_open_max_calls
        self.exponential_backoff_multiplier = exponential_backoff_multiplier
        self.exponential_backoff_max = exponential_backoff_max

        # Validate configuration
        if failure_threshold <= 0:
            raise ImproperlyConfigured("failure_threshold must be positive")
        if recovery_timeout <= 0:
            raise ImproperlyConfigured("recovery_timeout must be positive")
        if reset_timeout <= 0:
            raise ImproperlyConfigured("reset_timeout must be positive")


class CircuitBreakerStats:
    """Statistics tracking for circuit breaker."""

    def __init__(self) -> None:
        """Initialize circuit breaker statistics tracking."""
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.state_changes = 0
        self.last_failure_time: Optional[float] = None
        self.last_success_time: Optional[float] = None
        self.state_change_history: list = []

    def record_success(self) -> None:
        """Record a successful call."""
        self.total_calls += 1
        self.successful_calls += 1
        self.last_success_time = time.time()

    def record_failure(self) -> None:
        """Record a failed call."""
        self.total_calls += 1
        self.failed_calls += 1
        self.last_failure_time = time.time()

    def record_state_change(
        self, old_state: CircuitBreakerState, new_state: CircuitBreakerState
    ) -> None:
        """Record a state change."""
        self.state_changes += 1
        change_record = {
            "timestamp": time.time(),
            "from_state": old_state.value,
            "to_state": new_state.value,
        }
        self.state_change_history.append(change_record)

        # Keep only last 100 state changes
        if len(self.state_change_history) > 100:
            self.state_change_history.pop(0)

    def get_failure_rate(self) -> float:
        """Get the current failure rate."""
        if self.total_calls == 0:
            return 0.0
        return self.failed_calls / self.total_calls

    def get_stats(self) -> Dict[str, Any]:
        """Get all statistics as a dictionary."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "failure_rate": self.get_failure_rate(),
            "state_changes": self.state_changes,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "recent_state_changes": (
                self.state_change_history[-10:] if self.state_change_history else []
            ),
        }


class CircuitBreaker:
    """
    Circuit breaker implementation with exponential backoff.

    The circuit breaker monitors function calls and automatically
    prevents calls when failure rate exceeds threshold.
    """

    def __init__(self, config: CircuitBreakerConfig):
        """Initialize circuit breaker with configuration."""
        self._config = config
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._last_state_change: float = time.time()
        self._half_open_calls = 0
        self._consecutive_failures = 0
        self._lock = Lock()
        self._stats = CircuitBreakerStats()

        logger.info(
            f"Circuit breaker '{self._config.name}' initialized with "
            f"failure_threshold={self._config.failure_threshold}, "
            f"recovery_timeout={self._config.recovery_timeout}"
        )

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        return self._stats

    def _calculate_backoff_time(self) -> float:
        """Calculate exponential backoff time based on consecutive failures."""
        if self._consecutive_failures <= 1:
            return self._config.recovery_timeout

        backoff = self._config.recovery_timeout * (
            self._config.exponential_backoff_multiplier
            ** (self._consecutive_failures - 1)
        )
        return min(backoff, self._config.exponential_backoff_max)

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt circuit reset."""
        if not self._last_failure_time:
            return True

        current_time = time.time()
        backoff_time = self._calculate_backoff_time()

        return current_time - self._last_failure_time >= backoff_time

    def _change_state(self, new_state: CircuitBreakerState) -> None:
        """Change circuit breaker state and log the change."""
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()
        self._stats.record_state_change(old_state, new_state)

        logger.info(
            f"Circuit breaker '{self._config.name}' state changed: "
            f"{old_state.value} -> {new_state.value}"
        )

        if new_state == CircuitBreakerState.HALF_OPEN:
            self._half_open_calls = 0

    def _handle_success(self) -> None:
        """Handle successful operation."""
        with self._lock:
            self._stats.record_success()

            if self._state == CircuitBreakerState.HALF_OPEN:
                # Successful call in HALF_OPEN, reset to CLOSED
                self._change_state(CircuitBreakerState.CLOSED)
                self._failure_count = 0
                self._consecutive_failures = 0
                logger.info(
                    f"Circuit breaker '{self._config.name}' recovered successfully"
                )
            elif self._state == CircuitBreakerState.CLOSED:
                # Reset failure count after successful operation
                current_time = time.time()
                if (
                    self._last_failure_time
                    and current_time - self._last_failure_time
                    >= self._config.reset_timeout
                ):
                    self._failure_count = 0
                    self._consecutive_failures = 0

    def _handle_failure(self, exception: Exception) -> None:
        """Handle failed operation."""
        with self._lock:
            self._stats.record_failure()
            current_time = time.time()

            if self._state == CircuitBreakerState.CLOSED:
                self._failure_count += 1
                self._consecutive_failures += 1
                self._last_failure_time = current_time

                if self._failure_count >= self._config.failure_threshold:
                    self._change_state(CircuitBreakerState.OPEN)
                    logger.warning(
                        f"Circuit breaker '{self._config.name}' opened due to "
                        f"{self._failure_count} failures. Exception: {exception}"
                    )

            elif self._state == CircuitBreakerState.HALF_OPEN:
                # Failure in HALF_OPEN, go back to OPEN
                self._consecutive_failures += 1
                self._last_failure_time = current_time
                self._change_state(CircuitBreakerState.OPEN)
                logger.warning(
                    f"Circuit breaker '{self._config.name}' failed recovery attempt"
                )

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Call function through circuit breaker.

        Args:
            func: Function to call
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Function result

        Raises:
            CircuitBreakerError: When circuit is open
            Any exception raised by the function
        """
        with self._lock:
            current_time = time.time()

            # Check if we should transition from OPEN to HALF_OPEN
            if self._state == CircuitBreakerState.OPEN and self._should_attempt_reset():
                self._change_state(CircuitBreakerState.HALF_OPEN)

            # Block calls if circuit is OPEN
            if self._state == CircuitBreakerState.OPEN:
                backoff_time = self._calculate_backoff_time()
                next_attempt = (self._last_failure_time or current_time) + backoff_time

                raise CircuitBreakerError(
                    f"Circuit breaker '{self._config.name}' is OPEN. "
                    f"Next attempt allowed at {time.ctime(next_attempt)}",
                    next_attempt_time=next_attempt,
                )

            # Limit calls in HALF_OPEN state
            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_calls >= self._config.half_open_max_calls:
                    raise CircuitBreakerError(
                        f"Circuit breaker '{self._config.name}' is in HALF_OPEN state "
                        f"and max calls ({self._config.half_open_max_calls}) exceeded"
                    )
                self._half_open_calls += 1

        # Execute the function
        try:
            result = func(*args, **kwargs)
            self._handle_success()
            return result
        except self._config.expected_exception as e:
            self._handle_failure(e)
            raise

    def call_with_fallback(
        self, func: Callable[..., T], *args: Any, **kwargs: Any
    ) -> T:
        """
        Call function with fallback support.

        Args:
            func: Primary function to call
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Function result or fallback result
        """
        try:
            return self.call(func, *args, **kwargs)
        except CircuitBreakerError:
            if self._config.fallback_function:
                logger.info(
                    f"Circuit breaker '{self._config.name}' using fallback function"
                )
                return self._config.fallback_function(*args, **kwargs)
            raise

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        with self._lock:
            old_state = self._state
            self._change_state(CircuitBreakerState.CLOSED)
            self._failure_count = 0
            self._consecutive_failures = 0
            self._half_open_calls = 0
            self._last_failure_time = None

            logger.info(
                f"Circuit breaker '{self._config.name}' manually reset from {old_state.value}"
            )

    def get_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status."""
        current_time = time.time()
        backoff_time = self._calculate_backoff_time()
        next_attempt_time = None

        if self._state == CircuitBreakerState.OPEN and self._last_failure_time:
            next_attempt_time = self._last_failure_time + backoff_time

        return {
            "name": self._config.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "consecutive_failures": self._consecutive_failures,
            "failure_threshold": self._config.failure_threshold,
            "last_failure_time": self._last_failure_time,
            "time_since_last_failure": (
                current_time - self._last_failure_time
                if self._last_failure_time
                else None
            ),
            "next_attempt_time": next_attempt_time,
            "backoff_time": backoff_time,
            "half_open_calls": self._half_open_calls,
            "stats": self._stats.get_stats(),
        }


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    def __init__(self) -> None:
        """Initialize the circuit breaker registry."""
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = Lock()

    def get_or_create(
        self, name: str, config: Optional[CircuitBreakerConfig] = None
    ) -> CircuitBreaker:
        """
        Get existing circuit breaker or create new one.

        Args:
            name: Circuit breaker name
            config: Configuration for new circuit breaker

        Returns:
            CircuitBreaker instance
        """
        if name in self._breakers:
            return self._breakers[name]

        with self._lock:
            # Double-check pattern
            if name in self._breakers:
                return self._breakers[name]

            if config is None:
                config = CircuitBreakerConfig(name=name)

            breaker = CircuitBreaker(config)
            self._breakers[name] = breaker
            return breaker

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name."""
        return self._breakers.get(name)

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for breaker in self._breakers.values():
            breaker.reset()

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all circuit breakers."""
        return {name: breaker.get_status() for name, breaker in self._breakers.items()}

    def remove(self, name: str) -> bool:
        """Remove circuit breaker from registry."""
        with self._lock:
            if name in self._breakers:
                del self._breakers[name]
                return True
            return False


# Global circuit breaker registry
circuit_breaker_registry = CircuitBreakerRegistry()


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    expected_exception: type[Exception] = Exception,
    name: Optional[str] = None,
    fallback_function: Optional[Callable] = None,
) -> Callable:
    """
    Decorator for applying circuit breaker pattern to functions.

    Args:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Time to wait before trying HALF_OPEN state
        expected_exception: Exception type that triggers circuit breaker
        name: Name for circuit breaker (defaults to function name)
        fallback_function: Function to call when circuit is open

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        breaker_name = name or f"{func.__module__}.{func.__name__}"
        config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=expected_exception,
            name=breaker_name,
            fallback_function=fallback_function,
        )
        breaker = circuit_breaker_registry.get_or_create(breaker_name, config)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if fallback_function:
                return breaker.call_with_fallback(func, *args, **kwargs)
            else:
                return breaker.call(func, *args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        wrapper.circuit_breaker = breaker  # type: ignore[attr-defined]
        return wrapper

    return decorator


def get_circuit_breaker_config_from_settings() -> Dict[str, Any]:
    """Get circuit breaker configuration from Django settings."""
    default_config = {
        "failure_threshold": 5,
        "recovery_timeout": 60,
        "reset_timeout": 300,
        "half_open_max_calls": 1,
        "exponential_backoff_multiplier": 2.0,
        "exponential_backoff_max": 300,
    }

    # Check for Django settings
    if hasattr(settings, "RATELIMIT_CIRCUIT_BREAKER"):
        config = getattr(settings, "RATELIMIT_CIRCUIT_BREAKER", {})
        default_config.update(config)

    return default_config
