"""
Base algorithm interface for rate limiting algorithms.

This module defines the base interface that all rate limiting algorithms
must implement to ensure consistent behavior across different algorithms.
"""

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


class RateLimitAlgorithm(ABC):
    """
    Base class for rate limiting algorithms.

    All rate limiting algorithms must inherit from this class and implement
    the required abstract methods to provide consistent behavior.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the algorithm with configuration.

        Args:
            config: Optional configuration dictionary for algorithm-specific settings
        """
        self.config = config or {}

    @abstractmethod
    def is_allowed(
        self, _backend: Any, _key: str, _limit: int, _period: int, **_kwargs: Any
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if request is allowed and return metadata.

        Args:
            backend: Storage backend instance
            key: Rate limit key
            limit: Request limit
            period: Time period in seconds
            **kwargs: Additional algorithm-specific parameters

        Returns:
            Tuple of (is_allowed, metadata_dict) where metadata contains
            information about the current rate limit state
        """

    @abstractmethod
    def get_info(
        self, _backend: Any, _key: str, _limit: int, _period: int, **_kwargs: Any
    ) -> Dict[str, Any]:
        """
        Get current rate limit information without consuming tokens/requests.

        Args:
            backend: Storage backend instance
            key: Rate limit key
            limit: Request limit
            period: Time period in seconds
            **kwargs: Additional algorithm-specific parameters

        Returns:
            Dictionary with current state information (remaining requests,
            reset time, etc.)
        """

    def reset(self, backend: Any, key: str) -> bool:
        """
        Reset rate limit state for a given key.

        Args:
            backend: Storage backend instance
            key: Rate limit key to reset

        Returns:
            True if reset was successful, False otherwise
        """
        # Default implementation - backends can override for specific behavior
        try:
            if hasattr(backend, "delete"):
                return backend.delete(key)
            return False
        except Exception:
            return False

    def get_current_time(self) -> float:
        """
        Get current time in seconds.

        This method exists to allow easy mocking in tests.

        Returns:
            Current time as float seconds since epoch
        """
        return time.time()
