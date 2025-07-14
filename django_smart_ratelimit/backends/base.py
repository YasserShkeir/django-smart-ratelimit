"""
Base backend class for rate limiting storage.

This module defines the interface that all rate limiting backends
must implement.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


class BaseBackend(ABC):
    """
    Abstract base class for rate limiting backends.

    All backends must implement the incr and reset methods to provide
    atomic operations for rate limiting counters.
    """

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
