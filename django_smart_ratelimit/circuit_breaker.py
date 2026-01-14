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

from django.core.exceptions import ImproperlyConfigured

from .circuit_breaker_state import (
    CircuitBreakerStateStorage,
    MemoryCircuitBreakerState,
    RedisCircuitBreakerState,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Backend failed, requests blocked
    HALF_OPEN = "half_open"  # Testing if backend recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker prevents operation."""

    def __init__(
        self,
        message: str = "Circuit breaker is open",
        next_attempt_time: Optional[float] = None,
        breaker_name: Optional[str] = None,
        failure_count: Optional[int] = None,
        last_failure_time: Optional[float] = None,
        recovery_time: Optional[float] = None,
    ):
        """
        Initialize CircuitBreakerError with context.

        Args:
            message: Error message
            next_attempt_time: Timestamp when next attempt is allowed (legacy)
            breaker_name: Name of the circuit breaker
            failure_count: Number of failures that tripped the breaker
            last_failure_time: Timestamp of the last failure
            recovery_time: Seconds until recovery attempt allowed
        """
        super().__init__(message)
        self.next_attempt_time = next_attempt_time
        self.breaker_name = breaker_name
        self.failure_count = failure_count
        self.last_failure_time = last_failure_time
        self.recovery_time = recovery_time
        self.next_attempt_time = next_attempt_time

    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.recovery_time:
            return f"{self.args[0]} (retry in {self.recovery_time:.1f}s)"
        return self.args[0]


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
        state_backend: str = "memory",
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
            state_backend: Backend for state storage ("memory" or "redis")
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
        self.state_backend = state_backend

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

    def __init__(
        self, config: CircuitBreakerConfig, redis_client: Optional[Any] = None
    ):
        """Initialize circuit breaker with configuration."""
        self._config = config
        self._redis_client = redis_client
        self._stats = CircuitBreakerStats()
        self._lock = Lock()

        # Initialize state storage
        self._storage: CircuitBreakerStateStorage
        if config.state_backend == "redis" and redis_client:
            self._storage = RedisCircuitBreakerState(redis_client)
        else:
            self._storage = MemoryCircuitBreakerState()
            if config.state_backend == "redis":
                logger.warning(
                    f"Circuit breaker '{config.name}' configured for Redis state "
                    "but no redis_client provided. Falling back to memory."
                )

        logger.info(
            f"Circuit breaker '{self._config.name}' initialized with "
            f"failure_threshold={self._config.failure_threshold}, "
            f"recovery_timeout={self._config.recovery_timeout}"
        )

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        state_str = self._storage.get_state(self._config.name or "default")
        try:
            return CircuitBreakerState(state_str)
        except ValueError:
            return CircuitBreakerState.CLOSED

    @property
    def stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        return self._stats

    @property
    def _failure_count_prop(self) -> int:
        """Get failure count from storage."""
        return self._storage.get_failure_count(self._config.name or "default")

    @property
    def _last_failure_time(self) -> Optional[float]:
        """Get last failure time from storage."""
        return self._storage.get_last_failure_time(self._config.name or "default")

    def _calculate_backoff_time(self) -> float:
        """Calculate exponential backoff time based on consecutive failures."""
        count = self._failure_count_prop
        if count <= self._config.failure_threshold:
            return self._config.recovery_timeout

        extra_failures = count - self._config.failure_threshold
        backoff = self._config.recovery_timeout * (
            self._config.exponential_backoff_multiplier**extra_failures
        )
        return min(backoff, self._config.exponential_backoff_max)

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt circuit reset."""
        last_failure = self._last_failure_time
        if not last_failure:
            return True

        current_time = time.time()
        backoff_time = self._calculate_backoff_time()

        return current_time - last_failure >= backoff_time

    def _change_state(self, new_state: CircuitBreakerState) -> None:
        """Transition circuit breaker to new state."""
        old_state_str = self._storage.get_state(self._config.name or "default")
        try:
            old_state = CircuitBreakerState(old_state_str)
        except ValueError:
            old_state = CircuitBreakerState.CLOSED

        if old_state != new_state:
            name = self._config.name or "default"
            # Set state in storage
            # Add a small buffer to TTL for cache expiration
            ttl = None
            if new_state == CircuitBreakerState.OPEN:
                ttl = int(
                    self._config.recovery_timeout * 2
                    + self._config.exponential_backoff_max
                )
            elif new_state == CircuitBreakerState.HALF_OPEN:
                # Reset half-open calls when entering HALF_OPEN
                self._storage.reset_half_open_calls(name)

            self._storage.set_state(name, new_state.value, ttl=ttl)

            self._stats.record_state_change(old_state, new_state)

            logger.info(
                f"Circuit breaker '{self._config.name}' changed state: "
                f"{old_state.value} -> {new_state.value}"
            )

    def _check_reset_timeout(self) -> None:
        """Reset failure count if reset_timeout passed since last failure."""
        if self.state != CircuitBreakerState.CLOSED:
            return

        last_fail = self._last_failure_time
        if not last_fail:
            return

        if time.time() - last_fail > self._config.reset_timeout:
            self._storage.reset_failures(self._config.name or "default")

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute function within circuit breaker context.

        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of the function execution

        Raises:
            CircuitBreakerError: If circuit is open
            Exception: Original exception from function if not caught
        """
        self._check_reset_timeout()
        if not self.is_allowed():
            self._stats.record_failure()

            # Calculate when retry is allowed
            last_fail = self._last_failure_time or time.time()
            backoff = self._calculate_backoff_time()
            next_attempt = last_fail + backoff

            raise CircuitBreakerError(
                message=f"Circuit breaker '{self._config.name}' is open",
                breaker_name=self._config.name,
                failure_count=self._failure_count_prop,
                last_failure_time=last_fail,
                recovery_time=max(0, next_attempt - time.time()),
            )

        try:
            result = func(*args, **kwargs)
            self.report_success()
            return result
        except Exception as e:
            # Check if this exception should trigger circuit breaker
            if isinstance(e, self._config.expected_exception):
                self.report_failure()
            raise

    def is_allowed(self) -> bool:
        """
        Check if request is allowed by circuit breaker.

        Returns:
            True if allowed, False otherwise
        """
        current_state = self.state

        if current_state == CircuitBreakerState.CLOSED:
            return True

        if current_state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                self._change_state(CircuitBreakerState.HALF_OPEN)
                return True
            return False

        if current_state == CircuitBreakerState.HALF_OPEN:
            # Check if we exceeded max calls in half-open state
            name = self._config.name or "default"
            # We increment first to reserve the spot
            count = self._storage.increment_half_open_calls(name)
            if count > self._config.half_open_max_calls:
                return False
            return True

        return False

    def report_success(self) -> None:
        """Report successful execution."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            # Success in HALF_OPEN -> reset to CLOSED
            self._change_state(CircuitBreakerState.CLOSED)
            self._storage.reset_failures(self._config.name or "default")

        self._stats.record_success()

    def report_failure(self) -> None:
        """Report failed execution."""
        self._stats.record_failure()
        name = self._config.name or "default"

        # Increment failures in storage
        new_count = self._storage.increment_failure(name)

        # Check threshold
        if new_count >= self._config.failure_threshold:
            if self.state != CircuitBreakerState.OPEN:
                self._change_state(CircuitBreakerState.OPEN)

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

    def __enter__(self) -> "CircuitBreaker":
        """Context manager entry."""
        if not self.is_allowed():
            self._stats.record_failure()
            # Calculate when retry is allowed
            last_fail = self._last_failure_time or time.time()
            backoff = self._calculate_backoff_time()
            next_attempt = last_fail + backoff

            raise CircuitBreakerError(
                message=f"Circuit breaker '{self._config.name}' is open",
                breaker_name=self._config.name,
                failure_count=self._failure_count_prop,
                last_failure_time=last_fail,
                recovery_time=max(0, next_attempt - time.time()),
            )
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[Exception],
        _exc_tb: Optional[Any],
    ) -> None:
        """Context manager exit."""
        if exc_type is None:
            self.report_success()
        elif issubclass(exc_type, self._config.expected_exception) and exc_val:
            self.report_failure()
            # Don't suppress exception

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        self._change_state(CircuitBreakerState.CLOSED)
        self._storage.reset_failures(self._config.name or "default")
        logger.info(f"Circuit breaker '{self._config.name}' manually reset to CLOSED")

    def get_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status."""
        current_time = time.time()
        backoff_time = self._calculate_backoff_time()
        next_attempt_time = None

        last_failure = self._last_failure_time

        if self.state == CircuitBreakerState.OPEN and last_failure:
            next_attempt_time = last_failure + backoff_time

        return {
            "name": self._config.name,
            "state": self.state.value,
            "failure_count": self._failure_count_prop,
            "consecutive_failures": max(
                0, self._failure_count_prop - self._config.failure_threshold
            ),
            "failure_threshold": self._config.failure_threshold,
            "last_failure_time": last_failure,
            "time_since_last_failure": (
                current_time - last_failure if last_failure else None
            ),
            "next_attempt_time": next_attempt_time,
            "backoff_time": backoff_time,
            "half_open_calls": 0,
            "stats": self._stats.get_stats(),
        }


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    def __init__(self) -> None:
        """Initialize the circuit breaker registry."""
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = Lock()

    def get_or_create(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        redis_client: Optional[Any] = None,
    ) -> CircuitBreaker:
        """
        Get existing circuit breaker or create new one.

        Args:
            name: Circuit breaker name
            config: Configuration for new circuit breaker
            redis_client: Optional Redis client for distributed state

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

            breaker = CircuitBreaker(config, redis_client=redis_client)
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
    Decorate function with circuit breaker pattern.

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
        # Import inside function to avoid circular imports
        from django_smart_ratelimit.config import get_settings

        settings = get_settings()

        breaker_name = name or f"{func.__module__}.{func.__name__}"
        config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=expected_exception,
            name=breaker_name,
            fallback_function=fallback_function,
            state_backend=settings.circuit_breaker_storage,
        )

        # Configure Redis client if needed
        redis_client = None
        if (
            settings.circuit_breaker_storage == "redis"
            and settings.circuit_breaker_redis_url
        ):
            try:
                import redis

                redis_client = redis.from_url(settings.circuit_breaker_redis_url)
            except ImportError:
                logger.error(
                    "Redis configured for circuit breaker but redis-py not installed."
                )
            except Exception as e:
                logger.error(f"Failed to connect to Redis for circuit breaker: {e}")

        breaker = circuit_breaker_registry.get_or_create(
            breaker_name, config, redis_client=redis_client
        )

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
    from django_smart_ratelimit.config import get_settings

    settings = get_settings()

    default_config = {
        "failure_threshold": 5,
        "recovery_timeout": 60,
        "reset_timeout": 300,
        "half_open_max_calls": 1,
        "exponential_backoff_multiplier": 2.0,
        "exponential_backoff_max": 300,
    }

    if settings.circuit_breaker_config:
        default_config.update(settings.circuit_breaker_config)

    return default_config
