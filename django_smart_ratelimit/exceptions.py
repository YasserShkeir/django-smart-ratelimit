"""Custom exceptions for Django Smart Ratelimit."""

from typing import Optional

from .messages import ERROR_RATE_LIMIT_EXCEEDED


class RateLimitException(Exception):
    """Base exception for all rate limiting errors."""


class RateLimitExceeded(RateLimitException):
    """Raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str = ERROR_RATE_LIMIT_EXCEEDED,
        limit: Optional[str] = None,
        period: Optional[int] = None,
        retry_after: Optional[int] = None,
        key: Optional[str] = None,
    ):
        """Initialize exception."""
        self.limit = limit
        self.period = period
        self.retry_after = retry_after
        self.key = key
        super().__init__(message)


class BackendError(RateLimitException):
    """Raised when a backend operation fails."""

    def __init__(
        self,
        message: str,
        backend: Optional[str] = None,
        original_exception: Optional[Exception] = None,
    ):
        """Initialize BackendError."""
        super().__init__(message)
        self.backend = backend
        self.original_exception = original_exception


class BackendConnectionError(BackendError):
    """Raised when backend connection fails."""


class BackendTimeoutError(BackendError):
    """Raised when backend operation times out."""


class ConfigurationError(RateLimitException):
    """Raised when configuration is invalid."""


class CircuitBreakerError(RateLimitException):
    """Raised when circuit breaker is open."""

    def __init__(
        self,
        message: str = "Circuit breaker is open",
        breaker_name: Optional[str] = None,
        failure_count: Optional[int] = None,
        last_failure_time: Optional[float] = None,
        recovery_time: Optional[float] = None,
    ):
        """Initialize CircuitBreakerError."""
        super().__init__(message)
        self.breaker_name = breaker_name
        self.failure_count = failure_count
        self.last_failure_time = last_failure_time
        self.recovery_time = recovery_time

    def __str__(self) -> str:
        if self.recovery_time:
            return f"{self.args[0]} (retry in {self.recovery_time:.1f}s)"
        return self.args[0]


class CircuitBreakerOpen(CircuitBreakerError):
    """Legacy alias for CircuitBreakerError."""


class KeyGenerationError(RateLimitException):
    """Raised when rate limit key generation fails."""
