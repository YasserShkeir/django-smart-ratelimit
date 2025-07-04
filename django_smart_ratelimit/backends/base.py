"""
Base backend class for rate limiting storage.

This module defines the interface that all rate limiting backends
must implement.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseBackend(ABC):
    """
    Abstract base class for rate limiting backends.

    All backends must implement the incr and reset methods to provide
    atomic operations for rate limiting counters.
    """

    @abstractmethod
    def incr(self, key: str, period: int) -> int:
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
        pass

    @abstractmethod
    def reset(self, key: str) -> None:
        """
        Reset the counter for the given key.

        Args:
            key: The rate limit key to reset
        """
        pass

    @abstractmethod
    def get_count(self, key: str) -> int:
        """
        Get the current count for the given key.

        Args:
            key: The rate limit key

        Returns:
            Current count (0 if key doesn't exist)
        """
        pass

    @abstractmethod
    def get_reset_time(self, key: str) -> Optional[int]:
        """
        Get the timestamp when the key will reset.

        Args:
            key: The rate limit key

        Returns:
            Unix timestamp when key expires, or None if key doesn't exist
        """
        pass
