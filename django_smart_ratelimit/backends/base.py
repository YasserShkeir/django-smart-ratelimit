"""
Base backend class for rate limiting storage.

This module defines the interface that all rate limiting backends
must implement.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

try:
    from ..circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerConfig,
        circuit_breaker_registry,
        get_circuit_breaker_config_from_settings,
    )

    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False


class BaseBackend(ABC):
    """
    Abstract base class for rate limiting backends.

    All backends must implement the incr and reset methods to provide
    atomic operations for rate limiting counters.
    """

    def __init__(
        self,
        enable_circuit_breaker: bool = True,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize backend with optional circuit breaker.

        Args:
            enable_circuit_breaker: Whether to enable circuit breaker protection
            circuit_breaker_config: Custom circuit breaker configuration
        """
        self._circuit_breaker: Optional[CircuitBreaker] = None

        if enable_circuit_breaker and CIRCUIT_BREAKER_AVAILABLE:
            self._setup_circuit_breaker(circuit_breaker_config)

    def _setup_circuit_breaker(
        self, custom_config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Set up circuit breaker for this backend."""
        # Get default configuration from settings
        config_dict = get_circuit_breaker_config_from_settings()

        # Override with custom configuration if provided
        if custom_config:
            config_dict.update(custom_config)

        # Set backend-specific name with instance ID for uniqueness
        backend_name = (
            f"{self.__class__.__module__}.{self.__class__.__name__}_{id(self)}"
        )
        config_dict["name"] = backend_name

        # Create circuit breaker configuration
        config = CircuitBreakerConfig(**config_dict)

        # Get or create circuit breaker from registry
        self._circuit_breaker = circuit_breaker_registry.get_or_create(
            backend_name, config
        )

    def _call_with_circuit_breaker(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Call function with circuit breaker protection.

        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerError: When circuit breaker is open
            Any exception raised by the function
        """
        if self._circuit_breaker:
            return self._circuit_breaker.call(func, *args, **kwargs)
        else:
            return func(*args, **kwargs)

    def get_circuit_breaker_status(self) -> Optional[Dict[str, Any]]:
        """Get circuit breaker status for this backend."""
        if self._circuit_breaker:
            return self._circuit_breaker.get_status()
        return None

    def reset_circuit_breaker(self) -> None:
        """Manually reset circuit breaker for this backend."""
        if self._circuit_breaker:
            self._circuit_breaker.reset()

    @abstractmethod
    def incr(self, _key: str, _period: int) -> int:
        """
        Increment the counter for the given key within the time period.

        This method should atomically:
        1. Increment the counter for the key
        2. Set expiration if this is the first increment
        3. Return the current count

        Args:
            key: The rate limit key
            period: Time period in seconds

        Returns:
            Current count after increment
        """

    @abstractmethod
    def reset(self, _key: str) -> None:
        """
        Reset the counter for the given key.

        Args:
            key: The rate limit key to reset
        """

    @abstractmethod
    def get_count(self, _key: str) -> int:
        """
        Get the current count for the given key.

        Args:
            key: The rate limit key

        Returns:
            Current count (0 if key doesn't exist)
        """

    @abstractmethod
    def get_reset_time(self, _key: str) -> Optional[int]:
        """
        Get the timestamp when the key will reset.

        Args:
            key: The rate limit key

        Returns:
            Unix timestamp when key expires, or None if key doesn't exist
        """

    # Token Bucket Algorithm Support

    def token_bucket_check(
        self,
        _key: str,
        _bucket_size: int,
        _refill_rate: float,
        _initial_tokens: int,
        _tokens_requested: int,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Token bucket rate limit check.

        This method should atomically:
        1. Calculate current tokens based on refill rate and time elapsed
        2. Check if enough tokens are available for the request
        3. Consume tokens if available
        4. Return availability status and metadata

        Args:
            key: The rate limit key
            bucket_size: Maximum number of tokens in the bucket
            refill_rate: Rate at which tokens are added (tokens per second)
            initial_tokens: Initial number of tokens when bucket is created
            tokens_requested: Number of tokens requested for this operation

        Returns:
            Tuple of (is_allowed, metadata_dict) where metadata contains:
            - tokens_remaining: Current tokens after operation
            - tokens_requested: Number of tokens requested
            - bucket_size: Maximum bucket capacity
            - refill_rate: Rate of token refill
            - time_to_refill: Time until bucket is full (if applicable)

        Note:
            Backends should implement this method for atomic token bucket operations.
            If not implemented, the algorithm will fall back to a generic
            implementation.
        """
        raise NotImplementedError(
            "Token bucket operations not implemented for this backend"
        )

    def token_bucket_info(
        self, _key: str, _bucket_size: int, _refill_rate: float
    ) -> Dict[str, Any]:
        """
        Get token bucket information without consuming tokens.

        Args:
            key: The rate limit key
            bucket_size: Maximum number of tokens in the bucket
            refill_rate: Rate at which tokens are added (tokens per second)

        Returns:
            Dictionary with current bucket state:
            - tokens_remaining: Current available tokens
            - bucket_size: Maximum bucket capacity
            - refill_rate: Rate of token refill
            - time_to_refill: Time until bucket is full
            - last_refill: Timestamp of last refill calculation
        """
        raise NotImplementedError("Token bucket info not implemented for this backend")

    # Generic storage methods for algorithm implementations

    def get(self, _key: str) -> Any:
        """
        Get value for a key.

        Args:
            key: Storage key

        Returns:
            Value associated with key, or None if not found
        """
        raise NotImplementedError("Generic get not implemented for this backend")

    def set(self, _key: str, _value: Any, _expiration: Optional[int] = None) -> bool:
        """
        Set value for a key with optional expiration.

        Args:
            key: Storage key
            value: Value to store
            expiration: Optional expiration time in seconds

        Returns:
            True if successful, False otherwise
        """
        raise NotImplementedError("Generic set not implemented for this backend")

    def delete(self, _key: str) -> bool:
        """
        Delete a key.

        Args:
            key: Storage key to delete

        Returns:
            True if key was deleted, False if key didn't exist
        """
        raise NotImplementedError("Generic delete not implemented for this backend")

    # Circuit breaker enhanced methods
    # These methods provide circuit breaker protection for the abstract methods

    def incr_with_circuit_breaker(self, key: str, period: int) -> int:
        """
        Increment counter with circuit breaker protection.

        Args:
            key: The rate limit key
            period: Time period in seconds

        Returns:
            Current count after increment

        Raises:
            CircuitBreakerError: When circuit breaker is open
        """
        return self._call_with_circuit_breaker(self.incr, key, period)

    def reset_with_circuit_breaker(self, key: str) -> None:
        """
        Reset counter with circuit breaker protection.

        Args:
            key: The rate limit key to reset

        Raises:
            CircuitBreakerError: When circuit breaker is open
        """
        return self._call_with_circuit_breaker(self.reset, key)

    def get_count_with_circuit_breaker(self, key: str) -> int:
        """
        Get count with circuit breaker protection.

        Args:
            key: The rate limit key

        Returns:
            Current count (0 if key doesn't exist)

        Raises:
            CircuitBreakerError: When circuit breaker is open
        """
        return self._call_with_circuit_breaker(self.get_count, key)

    def get_reset_time_with_circuit_breaker(self, key: str) -> Optional[int]:
        """
        Get reset time with circuit breaker protection.

        Args:
            key: The rate limit key

        Returns:
            Unix timestamp when key expires, or None if key doesn't exist

        Raises:
            CircuitBreakerError: When circuit breaker is open
        """
        return self._call_with_circuit_breaker(self.get_reset_time, key)

    def token_bucket_check_with_circuit_breaker(
        self,
        key: str,
        bucket_size: int,
        refill_rate: float,
        initial_tokens: int,
        tokens_requested: int,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Token bucket check with circuit breaker protection.

        Args:
            key: The rate limit key
            bucket_size: Maximum number of tokens in the bucket
            refill_rate: Rate at which tokens are added (tokens per second)
            initial_tokens: Initial number of tokens when bucket is created
            tokens_requested: Number of tokens requested for this operation

        Returns:
            Tuple of (is_allowed, metadata_dict)

        Raises:
            CircuitBreakerError: When circuit breaker is open
        """
        return self._call_with_circuit_breaker(
            self.token_bucket_check,
            key,
            bucket_size,
            refill_rate,
            initial_tokens,
            tokens_requested,
        )

    def is_circuit_breaker_enabled(self) -> bool:
        """Check if circuit breaker is enabled for this backend."""
        return self._circuit_breaker is not None

    def get_backend_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status for this backend.

        Returns:
            Dictionary containing backend and circuit breaker status
        """
        status = {
            "backend_class": f"{self.__class__.__module__}.{self.__class__.__name__}",
            "circuit_breaker_enabled": self.is_circuit_breaker_enabled(),
            "circuit_breaker_available": CIRCUIT_BREAKER_AVAILABLE,
        }

        # Add circuit breaker status if available
        cb_status = self.get_circuit_breaker_status()
        if cb_status:
            status["circuit_breaker"] = cb_status

        return status
