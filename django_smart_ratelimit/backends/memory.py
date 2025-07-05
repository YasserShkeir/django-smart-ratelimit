"""
In-memory backend for rate limiting.

This backend stores rate limiting data in memory using Python dictionaries
with thread-safe operations. It's ideal for development, testing, and
single-server deployments.
"""

import threading
import time
from typing import Dict, List, Optional, Tuple, Union

from django.conf import settings

from .base import BaseBackend


class MemoryBackend(BaseBackend):
    """
    In-memory backend implementation using sliding window algorithm.

    This backend stores rate limiting data in memory with automatic cleanup
    of expired entries. It's thread-safe and suitable for development and
    single-server deployments.

    Features:
    - Thread-safe operations using locks
    - Automatic cleanup of expired entries
    - Configurable memory limits
    - Sliding window algorithm support
    """

    def __init__(self) -> None:
        """Initialize the memory backend."""
        # Dictionary to store rate limit data
        # Format: {key: (expiry_time, [(timestamp, unique_id), ...])}
        self._data: Dict[str, Tuple[float, List[Tuple[float, str]]]] = {}

        # Lock for thread safety
        self._lock = threading.RLock()

        # Configuration
        self._max_keys = getattr(settings, "RATELIMIT_MEMORY_MAX_KEYS", 10000)
        self._cleanup_interval = getattr(
            settings, "RATELIMIT_MEMORY_CLEANUP_INTERVAL", 300
        )  # 5 minutes

        # Cleanup tracking
        self._last_cleanup = time.time()

        # Configuration
        self._algorithm = getattr(settings, "RATELIMIT_ALGORITHM", "sliding_window")

    def incr(self, key: str, period: int) -> int:
        """
        Increment the counter for the given key within the time period.

        Args:
            key: The rate limit key
            period: Time period in seconds

        Returns:
            Current count after increment
        """
        now = time.time()
        unique_id = f"{now}:{threading.current_thread().ident}"

        with self._lock:
            # Perform cleanup if needed
            self._cleanup_if_needed()

            # Get or create entry
            if key not in self._data:
                self._data[key] = (now + period, [])

            expiry_time, requests = self._data[key]

            if self._algorithm == "sliding_window":
                # Sliding window: remove old requests
                cutoff_time = now - period
                requests = [(ts, uid) for ts, uid in requests if ts > cutoff_time]

                # Add current request
                requests.append((now, unique_id))

                # Update expiry time for sliding window
                expiry_time = now + period

                self._data[key] = (expiry_time, requests)
                return len(requests)
            else:
                # Fixed window: reset if expired (default for unknown algorithms)
                if now >= expiry_time:
                    requests = [(now, unique_id)]
                    expiry_time = now + period
                    self._data[key] = (expiry_time, requests)
                    return 1
                else:
                    requests.append((now, unique_id))
                    self._data[key] = (expiry_time, requests)
                    return len(requests)

    def reset(self, key: str) -> None:
        """
        Reset the counter for the given key.

        Args:
            key: The rate limit key to reset
        """
        with self._lock:
            if key in self._data:
                del self._data[key]

    def get_count(self, key: str) -> int:
        """
        Get the current count for the given key.

        Args:
            key: The rate limit key

        Returns:
            Current count (0 if key doesn't exist)
        """
        now = time.time()

        with self._lock:
            if key not in self._data:
                return 0

            expiry_time, requests = self._data[key]

            if self._algorithm == "sliding_window":
                # Count requests in sliding window
                # We need to estimate the period from the data
                if not requests:
                    return 0

                # Use a default period of 60 seconds for sliding window count
                # This is a limitation of the get_count method - we don't know
                # the period
                period = 60
                cutoff_time = now - period
                return len([req for req in requests if req[0] > cutoff_time])
            else:
                # Fixed window: check if expired
                if now >= expiry_time:
                    return 0
                return len(requests)

    def get_reset_time(self, key: str) -> Optional[int]:
        """
        Get the timestamp when the key will reset.

        Args:
            key: The rate limit key

        Returns:
            Unix timestamp when key expires, or None if key doesn't exist
        """
        with self._lock:
            if key not in self._data:
                return None

            expiry_time, _ = self._data[key]
            return int(expiry_time)

    def _cleanup_if_needed(self) -> None:
        """
        Perform cleanup of expired keys if needed.

        This method is called internally and should be called with the lock held.
        """
        now = time.time()

        # Check if cleanup is needed (but always cleanup if we're over the limit)
        if (
            now - self._last_cleanup < self._cleanup_interval
            and len(self._data) <= self._max_keys
        ):
            return

        # Cleanup expired keys
        expired_keys = []
        for key, (expiry_time, requests) in self._data.items():
            if self._algorithm == "sliding_window":
                # For sliding window, we can't easily determine if a key is expired
                # without knowing the period, so we keep all keys
                continue
            else:
                # Fixed window: remove expired keys
                if now >= expiry_time:
                    expired_keys.append(key)

        for key in expired_keys:
            del self._data[key]

        # If we have too many keys, remove the oldest ones
        if len(self._data) > self._max_keys:
            # Sort by expiry time and remove oldest
            sorted_keys = sorted(self._data.keys(), key=lambda k: self._data[k][0])
            keys_to_remove = sorted_keys[: len(self._data) - self._max_keys]
            for key in keys_to_remove:
                del self._data[key]

        self._last_cleanup = now

    def clear_all(self) -> None:
        """
        Clear all rate limiting data.

        This method is primarily for testing purposes.
        """
        with self._lock:
            self._data.clear()

    def get_stats(self) -> Dict[str, Union[int, str]]:
        """
        Get statistics about the memory backend.

        Returns:
            Dictionary containing backend statistics
        """
        with self._lock:
            now = time.time()
            active_keys = 0
            total_requests = 0

            for key, (expiry_time, requests) in self._data.items():
                if self._algorithm == "sliding_window" or now < expiry_time:
                    active_keys += 1
                    total_requests += len(requests)

            return {
                "total_keys": len(self._data),
                "active_keys": active_keys,
                "total_requests": total_requests,
                "max_keys": self._max_keys,
                "cleanup_interval": self._cleanup_interval,
                "last_cleanup": int(self._last_cleanup),
                "algorithm": self._algorithm,
            }
