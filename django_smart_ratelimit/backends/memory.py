"""
In-memory backend for rate limiting.

This backend stores rate limiting data in memory using Python dictionaries
with thread-safe operations. It's ideal for development, testing, and
single-server deployments.
"""

import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from django.conf import settings

from .base import BaseBackend
from .utils import (
    calculate_sliding_window_count,
    calculate_token_bucket_state,
    clean_expired_entries,
    cleanup_memory_data,
    create_operation_timer,
    estimate_memory_usage,
    format_token_bucket_metadata,
    generate_expiry_timestamp,
    is_expired,
    log_backend_operation,
    normalize_key,
    validate_backend_config,
)


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
    - Token bucket algorithm support
    """

    def __init__(self, **config: Any) -> None:
        """Initialize the memory backend with enhanced utilities."""
        # Extract circuit breaker configuration before processing
        enable_circuit_breaker = config.pop("enable_circuit_breaker", True)
        circuit_breaker_config = config.pop("circuit_breaker_config", None)

        # Initialize parent class with circuit breaker
        super().__init__(enable_circuit_breaker, circuit_breaker_config)

        # Read Django settings first
        max_keys_setting = getattr(settings, "RATELIMIT_MEMORY_MAX_KEYS", 10000)
        cleanup_interval_setting = getattr(
            settings, "RATELIMIT_MEMORY_CLEANUP_INTERVAL", 300
        )

        # Validate and normalize configuration
        validated_config = validate_backend_config(config, "memory")

        # Dictionary to store rate limit data
        # Format: {key: (expiry_time, [(timestamp, unique_id), ...])}
        self._data: Dict[str, Tuple[float, List[Tuple[float, str]]]] = {}

        # Dictionary to store token bucket data
        # Format: {key: {'tokens': float, 'last_refill': float}}
        self._token_buckets: Dict[str, Dict[str, float]] = {}

        # Generic storage for algorithm implementations
        self._storage: Dict[str, Any] = {}

        # Lock for thread safety
        self._lock = threading.RLock()

        # Configuration from validated config and Django settings
        # Django settings take precedence over validated config defaults
        self._max_keys = validated_config.get("max_entries", max_keys_setting)
        self._cleanup_interval = validated_config.get(
            "cleanup_interval", cleanup_interval_setting
        )

        # Cleanup tracking
        self._last_cleanup = time.time()

        # Configuration
        self._algorithm = getattr(settings, "RATELIMIT_ALGORITHM", "sliding_window")
        self._key_prefix = getattr(settings, "RATELIMIT_KEY_PREFIX", "ratelimit:")

    def incr(self, key: str, period: int) -> int:
        """
        Increment the counter for the given key within the time period.

        Args:
            key: The rate limit key
            period: Time period in seconds

        Returns:
            Current count after increment
        """
        with create_operation_timer() as timer:
            try:
                # Normalize the key
                normalized_key = normalize_key(key, self._key_prefix)
                now = time.time()
                unique_id = f"{now}:{threading.current_thread().ident}"

                with self._lock:
                    # Perform cleanup if needed
                    self._cleanup_if_needed()

                    # Get or create entry
                    if normalized_key not in self._data:
                        self._data[normalized_key] = (now + period, [])

                    expiry_time, requests = self._data[normalized_key]

                    if self._algorithm == "sliding_window":
                        # Use utility function for sliding window calculation
                        cutoff_time = now - period
                        requests = [
                            (ts, uid) for ts, uid in requests if ts > cutoff_time
                        ]

                        # Add current request
                        requests.append((now, unique_id))

                        # Update expiry time for sliding window
                        expiry_time = now + period

                        self._data[normalized_key] = (expiry_time, requests)
                        result = len(requests)
                    else:
                        # Fixed window: reset if expired
                        if is_expired(expiry_time):
                            requests = [(now, unique_id)]
                            expiry_time = generate_expiry_timestamp(period)
                            result = 1
                        else:
                            requests.append((now, unique_id))
                            result = len(requests)

                        self._data[normalized_key] = (expiry_time, requests)

                log_backend_operation(
                    "incr", f"memory backend increment for key {key}", timer.elapsed_ms
                )
                return result

            except Exception as e:
                log_backend_operation(
                    "incr",
                    f"memory backend increment failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                raise

    def reset(self, key: str) -> None:
        """
        Reset the counter for the given key.

        Args:
            key: The rate limit key to reset
        """
        with create_operation_timer() as timer:
            try:
                normalized_key = normalize_key(key, self._key_prefix)

                with self._lock:
                    if normalized_key in self._data:
                        del self._data[normalized_key]
                    if normalized_key in self._token_buckets:
                        del self._token_buckets[normalized_key]

                log_backend_operation(
                    "reset", f"memory backend reset for key {key}", timer.elapsed_ms
                )

            except Exception as e:
                log_backend_operation(
                    "reset",
                    f"memory backend reset failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                raise

    def get_count(self, key: str) -> int:
        """
        Get the current count for the given key.

        Args:
            key: The rate limit key

        Returns:
            Current count (0 if key doesn't exist)
        """
        with create_operation_timer() as timer:
            try:
                normalized_key = normalize_key(key, self._key_prefix)
                now = time.time()

                with self._lock:
                    if normalized_key not in self._data:
                        result = 0
                    else:
                        expiry_time, requests = self._data[normalized_key]

                        if self._algorithm == "sliding_window":
                            # Use utility function for sliding window calculation
                            # Use a default period of 60 seconds for sliding window
                            # This is a limitation of the get_count method - we don't
                            # know the exact period
                            period = 60
                            result = calculate_sliding_window_count(
                                requests, period, now
                            )
                        else:
                            # Fixed window
                            if is_expired(expiry_time):
                                result = 0
                            else:
                                result = len(requests)

                log_backend_operation(
                    "get_count",
                    f"memory backend get_count for key {key}",
                    timer.elapsed_ms,
                )
                return result

            except Exception as e:
                log_backend_operation(
                    "get_count",
                    f"memory backend get_count failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                raise

    def get_reset_time(self, key: str) -> Optional[int]:
        """
        Get the timestamp when the key will reset.

        Args:
            key: The rate limit key

        Returns:
            Unix timestamp when key expires, or None if key doesn't exist
        """
        with self._lock:
            # Normalize the key to match how it's stored
            normalized_key = normalize_key(key, self._key_prefix)

            if normalized_key not in self._data:
                return None

            expiry_time, _ = self._data[normalized_key]
            return int(expiry_time)

    # Token Bucket Algorithm Implementation

    def token_bucket_check(
        self,
        key: str,
        bucket_size: int,
        refill_rate: float,
        initial_tokens: int,
        tokens_requested: int,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Thread-safe token bucket check using enhanced utilities.

        Args:
            key: Rate limit key
            bucket_size: Maximum number of tokens in bucket
            refill_rate: Rate at which tokens are added (tokens per second)
            initial_tokens: Initial number of tokens when bucket is created
            tokens_requested: Number of tokens requested for this operation

        Returns:
            Tuple of (is_allowed, metadata_dict)
        """
        with create_operation_timer() as timer:
            try:
                normalized_key = normalize_key(key, self._key_prefix)
                current_time = time.time()
                bucket_key = f"{normalized_key}:token_bucket"

                # Handle edge case: zero bucket size means no requests allowed
                if bucket_size <= 0:
                    metadata = format_token_bucket_metadata(
                        0, bucket_size, refill_rate, float("inf")
                    )
                    metadata.update({"tokens_requested": tokens_requested})
                    log_backend_operation(
                        "token_bucket_check",
                        f"memory backend token bucket check for key {key}",
                        timer.elapsed_ms,
                    )
                    return False, metadata

                with self._lock:
                    # Perform cleanup if needed
                    self._cleanup_if_needed()

                    # Get current bucket state
                    if bucket_key not in self._token_buckets:
                        self._token_buckets[bucket_key] = {
                            "tokens": initial_tokens,
                            "last_refill": current_time,
                        }

                    bucket_data = self._token_buckets[bucket_key]

                    # Use utility function to calculate token bucket state
                    bucket_state = calculate_token_bucket_state(
                        bucket_data["tokens"],
                        bucket_data["last_refill"],
                        current_time,
                        bucket_size,
                        refill_rate,
                        tokens_requested,
                    )

                    current_tokens = bucket_state["current_tokens"]

                    # Check if request can be served
                    if bucket_state["is_allowed"]:
                        # Consume tokens
                        remaining_tokens = bucket_state["tokens_remaining"]
                        self._token_buckets[bucket_key] = {
                            "tokens": remaining_tokens,
                            "last_refill": current_time,
                        }

                        # Use utility function to format metadata
                        metadata = format_token_bucket_metadata(
                            remaining_tokens,
                            bucket_size,
                            refill_rate,
                            bucket_state["time_to_refill"],
                        )
                        metadata.update({"tokens_requested": tokens_requested})

                        log_backend_operation(
                            "token_bucket_check",
                            f"memory backend token bucket check success for key {key}",
                            timer.elapsed_ms,
                        )
                        return True, metadata
                    else:
                        # Request cannot be served - update last_refill time
                        # but don't consume tokens
                        self._token_buckets[bucket_key] = {
                            "tokens": current_tokens,
                            "last_refill": current_time,
                        }

                        metadata = format_token_bucket_metadata(
                            current_tokens,
                            bucket_size,
                            refill_rate,
                            bucket_state["time_to_refill"],
                        )
                        metadata.update({"tokens_requested": tokens_requested})

                        log_backend_operation(
                            "token_bucket_check",
                            f"memory backend token bucket check rejected for key {key}",
                            timer.elapsed_ms,
                        )
                        return False, metadata

            except Exception as e:
                log_backend_operation(
                    "token_bucket_check",
                    f"memory backend token bucket check failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                raise

    def token_bucket_info(
        self, key: str, bucket_size: int, refill_rate: float
    ) -> Dict[str, Any]:
        """
        Get token bucket information without consuming tokens.

        Args:
            key: Rate limit key
            bucket_size: Maximum number of tokens in bucket
            refill_rate: Rate at which tokens are added (tokens per second)

        Returns:
            Dictionary with current bucket state
        """
        current_time = time.time()
        bucket_key = f"{key}:token_bucket"

        with self._lock:
            # Get current bucket state
            if bucket_key not in self._token_buckets:
                return {
                    "tokens_remaining": bucket_size,
                    "bucket_size": bucket_size,
                    "refill_rate": refill_rate,
                    "time_to_refill": 0.0,
                    "last_refill": current_time,
                }

            bucket_data = self._token_buckets[bucket_key]

            # Calculate current tokens without updating state
            time_elapsed = current_time - bucket_data["last_refill"]
            tokens_to_add = time_elapsed * refill_rate
            current_tokens = min(bucket_size, bucket_data["tokens"] + tokens_to_add)

            return {
                "tokens_remaining": current_tokens,
                "bucket_size": bucket_size,
                "refill_rate": refill_rate,
                "time_to_refill": (
                    max(0, (bucket_size - current_tokens) / refill_rate)
                    if refill_rate > 0
                    else 0
                ),
                "last_refill": bucket_data["last_refill"],
            }

    # Generic storage methods for algorithm implementations

    def get(self, key: str) -> Any:
        """Get value for a key."""
        with self._lock:
            return self._storage.get(key)

    def set(self, key: str, value: Any, expiration: Optional[int] = None) -> bool:
        """Set value for a key with optional expiration."""
        with self._lock:
            try:
                # Perform cleanup if needed
                self._cleanup_if_needed()

                if expiration:
                    # Store with expiration time
                    self._storage[key] = {
                        "value": value,
                        "expires_at": time.time() + expiration,
                    }
                else:
                    # Store without expiration
                    self._storage[key] = {"value": value, "expires_at": None}
                return True
            except Exception:
                return False

    def delete(self, key: str) -> bool:
        """Delete a key."""
        with self._lock:
            # Delete from all storage locations
            deleted = False

            if key in self._storage:
                del self._storage[key]
                deleted = True

            if key in self._data:
                del self._data[key]
                deleted = True

            if key in self._token_buckets:
                del self._token_buckets[key]
                deleted = True

            return deleted

    def _cleanup_if_needed(self) -> None:
        """
        Perform cleanup of expired keys if needed using utility functions.

        This method is called internally and should be called with the lock held.
        """
        now = time.time()

        # Check if cleanup is needed (but always cleanup if we're over the limit)
        total_keys = len(self._data) + len(self._token_buckets) + len(self._storage)
        if (
            now - self._last_cleanup < self._cleanup_interval
            and total_keys <= self._max_keys
        ):
            return

        # Use utility function to clean expired entries from generic storage
        self._storage = clean_expired_entries(self._storage, now)

        # Cleanup expired keys from rate limit data
        expired_keys = []
        for key, (expiry_time, requests) in self._data.items():
            if self._algorithm != "sliding_window" and is_expired(expiry_time):
                expired_keys.append(key)

        for key in expired_keys:
            del self._data[key]

        # If we have too many keys, use utility function for cleanup
        total_keys = len(self._data) + len(self._token_buckets) + len(self._storage)
        if total_keys > self._max_keys:
            # First, cleanup token buckets using utility function
            if self._token_buckets:
                # Add last_access timestamps for LRU cleanup
                token_data_with_access = {}
                for key, data in self._token_buckets.items():
                    token_data_with_access[key] = {
                        **data,
                        "last_access": data.get("last_refill", 0),
                    }

                cleaned_buckets = cleanup_memory_data(
                    token_data_with_access,
                    max_size=min(len(self._token_buckets), self._max_keys // 2),
                    cleanup_strategy="lru",
                )

                # Remove last_access timestamps
                self._token_buckets = {
                    key: {k: v for k, v in data.items() if k != "last_access"}
                    for key, data in cleaned_buckets.items()
                }

            # If still too many keys, cleanup rate limit data using LRU
            total_keys = len(self._data) + len(self._token_buckets) + len(self._storage)
            if total_keys > self._max_keys:
                # Convert _data to have timestamps for LRU cleanup
                data_with_timestamps = {}
                for key, (expiry_time, requests) in self._data.items():
                    # Use the most recent request timestamp as last_access
                    last_access = (
                        max((ts for ts, _ in requests), default=0) if requests else 0
                    )
                    data_with_timestamps[key] = {
                        "expiry_time": expiry_time,
                        "requests": requests,
                        "last_access": last_access,
                    }

                max_data_keys = (
                    self._max_keys - len(self._token_buckets) - len(self._storage)
                )
                if max_data_keys > 0:
                    cleaned_data = cleanup_memory_data(
                        data_with_timestamps,
                        max_size=max_data_keys,
                        cleanup_strategy="lru",
                    )

                    # Convert back to original format
                    self._data = {
                        key: (data["expiry_time"], data["requests"])
                        for key, data in cleaned_data.items()
                    }
                else:
                    # No room for any data keys
                    self._data.clear()

        self._last_cleanup = now

    def clear_all(self) -> None:
        """
        Clear all rate limiting data.

        This method is primarily for testing purposes.
        """
        with self._lock:
            self._data.clear()
            self._token_buckets.clear()
            self._storage.clear()

    def get_stats(self) -> Dict[str, Union[int, str, float]]:
        """
        Get enhanced statistics about the memory backend using utilities.

        Returns:
            Dictionary containing comprehensive backend statistics
        """
        with self._lock:
            active_keys = 0
            total_requests = 0

            for key, (expiry_time, requests) in self._data.items():
                if self._algorithm == "sliding_window" or not is_expired(expiry_time):
                    active_keys += 1
                    total_requests += len(requests)

            # Use utility function to estimate memory usage
            total_memory = (
                estimate_memory_usage(self._data)
                + estimate_memory_usage(self._token_buckets)
                + estimate_memory_usage(self._storage)
            )

            return {
                "total_keys": len(self._data),
                "active_keys": active_keys,
                "total_requests": total_requests,
                "token_buckets": len(self._token_buckets),
                "storage_items": len(self._storage),
                "max_keys": self._max_keys,
                "cleanup_interval": self._cleanup_interval,
                "last_cleanup": int(self._last_cleanup),
                "algorithm": self._algorithm,
                "estimated_memory_bytes": total_memory,
                "estimated_memory_mb": round(total_memory / (1024 * 1024), 2),
                "memory_utilization_percent": round(
                    (
                        (
                            len(self._data)
                            + len(self._token_buckets)
                            + len(self._storage)
                        )
                        / self._max_keys
                        * 100
                    ),
                    2,
                ),
            }
