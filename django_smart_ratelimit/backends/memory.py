"""
In-memory backend for rate limiting.

This backend stores rate limiting data in memory using Python dictionaries
with thread-safe operations. It's ideal for development, testing, and
single-server deployments.
"""

import threading
from collections import OrderedDict, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from ..exceptions import BackendError
from ..messages import ERROR_BACKEND_UNAVAILABLE
from .base import BaseBackend
from .utils import (
    calculate_expiry,
    calculate_sliding_window_count,
    calculate_token_bucket_state,
    clean_expired_entries,
    create_operation_timer,
    filter_sliding_window_requests,
    format_token_bucket_metadata,
    generate_expiry_timestamp,
    get_current_timestamp,
    is_expired,
    log_backend_operation,
    normalize_key,
    validate_backend_config,
)


@dataclass
class TokenBucketState:
    """State for token bucket algorithm."""

    __slots__ = ("tokens", "last_refill")

    tokens: float
    last_refill: float


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
        # Read Django settings first
        from django_smart_ratelimit.config import get_settings

        settings = get_settings()

        # Extract circuit breaker configuration before processing
        enable_circuit_breaker = config.pop("enable_circuit_breaker", True)
        circuit_breaker_config = config.pop("circuit_breaker_config", None)
        fail_open = config.pop("fail_open", settings.fail_open)
        enable_background_cleanup = config.pop("enable_background_cleanup", True)

        # Initialize parent class with circuit breaker
        super().__init__(
            enable_circuit_breaker=enable_circuit_breaker,
            circuit_breaker_config=circuit_breaker_config,
            fail_open=fail_open,
            **config,
        )

        # Check backend options first, then explicit settings
        max_keys_setting = (
            config.get("max_keys")
            or settings.backend_options.get("max_keys")
            or settings.memory_max_keys
        )
        cleanup_interval_setting = (
            config.get("cleanup_interval")
            or settings.backend_options.get("cleanup_interval")
            or settings.memory_cleanup_interval
        )

        # Validate and normalize configuration
        validated_config = validate_backend_config(config, "memory")

        # Dictionary to store rate limit data
        # Format: {key: (expiry_time, [(timestamp, unique_id), ...])}
        self._data: OrderedDict[str, Tuple[float, List[Tuple[float, str]]]] = (
            OrderedDict()
        )

        # Partition index for expiration cleanup
        # Key: partition_id (timestamp // cleanup_interval), Value: Set[key]
        self._partitions: Dict[int, Set[str]] = defaultdict(set)
        # Store partition_id for each key for quick updates
        self._key_partition: Dict[str, int] = {}

        # Dictionary to store token bucket data
        # Format: {key: TokenBucketState}
        self._token_buckets: OrderedDict[str, TokenBucketState] = OrderedDict()

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
        self._last_cleanup = get_current_timestamp()

        # Background cleanup thread
        self._shutdown_event = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None

        if enable_background_cleanup:
            self._start_cleanup_thread()

        # Configuration
        self._algorithm = settings.default_algorithm
        self._key_prefix = settings.key_prefix

    def _start_cleanup_thread(self) -> None:
        """Start background cleanup thread."""
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="ratelimit-cleanup",
        )
        self._cleanup_thread.start()

    def _get_partition_id(self, expiry_time: float) -> int:
        """Get partition ID for an expiry time."""
        return int(expiry_time // self._cleanup_interval)

    def _update_partition(self, key: str, expiry_time: float) -> None:
        """
        Update the time partition for a key.
        Must be called with lock held.
        """
        new_partition = self._get_partition_id(expiry_time)
        old_partition = self._key_partition.get(key)

        if old_partition != new_partition:
            if old_partition is not None:
                if old_partition in self._partitions:
                    self._partitions[old_partition].discard(key)
                    if not self._partitions[old_partition]:
                        del self._partitions[old_partition]

            self._partitions[new_partition].add(key)
            self._key_partition[key] = new_partition

    def _remove_from_partition(self, key: str) -> None:
        """
        Remove a key from its partition.
        Must be called with lock held.
        """
        partition_id = self._key_partition.pop(key, None)
        if partition_id is not None and partition_id in self._partitions:
            self._partitions[partition_id].discard(key)
            if not self._partitions[partition_id]:
                del self._partitions[partition_id]

    def _cleanup_loop(self) -> None:
        """Background cleanup loop."""
        import time

        from .utils import log_backend_operation

        while not self._shutdown_event.is_set():
            time.sleep(self._cleanup_interval)
            if self._shutdown_event.is_set():
                break
            try:
                with self._lock:
                    self._cleanup_if_needed()
            except Exception as e:
                # Log error but keep thread running
                log_backend_operation("cleanup_error", str(e), level="error")

    def shutdown(self) -> None:
        """Stop background cleanup thread."""
        self._shutdown_event.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=1.0)

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
                now = get_current_timestamp()
                unique_id = f"{now}:{threading.current_thread().ident}"

                with self._lock:
                    # Get or create entry
                    if normalized_key not in self._data:
                        self._data[normalized_key] = (calculate_expiry(period, now), [])
                    else:
                        self._data.move_to_end(normalized_key)

                    expiry_time, requests = self._data[normalized_key]

                    if self._algorithm == "sliding_window":
                        # Use utility function for sliding window calculation
                        requests = filter_sliding_window_requests(requests, period, now)

                        # Add current request
                        requests.append((now, unique_id))

                        # Update expiry time for sliding window
                        expiry_time = calculate_expiry(period, now)

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

                    # Update partition for optimized cleanup
                    self._update_partition(normalized_key, expiry_time)

                    self._cleanup_if_needed()

                log_backend_operation(
                    "incr",
                    f"memory backend increment for key {key}",
                    timer.elapsed_ms,
                )
                return result

            except Exception as e:
                log_backend_operation(
                    "incr",
                    f"memory backend increment failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                allowed, meta = self._handle_backend_error("incr", key, e)
                return 0 if allowed else 9999

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
                        self._remove_from_partition(normalized_key)

                    if normalized_key in self._token_buckets:
                        del self._token_buckets[normalized_key]

                log_backend_operation(
                    "reset",
                    f"memory backend reset for key {key}",
                    timer.elapsed_ms,
                )

            except Exception as e:
                log_backend_operation(
                    "reset",
                    f"memory backend reset failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                allowed, meta = self._handle_backend_error("reset", key, e)
                if not allowed:
                    raise BackendError(ERROR_BACKEND_UNAVAILABLE) from e

    def get_count(self, key: str, period: int = 60) -> int:
        """
        Get the current count for the given key.

        Args:
            key: The rate limit key
            period: Time period in seconds (default: 60)

        Returns:
            Current count (0 if key doesn't exist)
        """
        with create_operation_timer() as timer:
            try:
                normalized_key = normalize_key(key, self._key_prefix)
                now = get_current_timestamp()

                with self._lock:
                    if normalized_key not in self._data:
                        result = 0
                    else:
                        expiry_time, requests = self._data[normalized_key]

                        if self._algorithm == "sliding_window":
                            # Use utility function for sliding window calc
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
                allowed, meta = self._handle_backend_error("get_count", key, e)
                return 0 if allowed else 9999

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

            expiry_time, requests = self._data[normalized_key]

            if self._algorithm == "sliding_window":
                if not requests:
                    return None

                # Calculate period from the last request and expiry time
                # expiry_time = last_request_time + period
                # period = expiry_time - last_request_time
                last_ts = requests[-1][0]
                period = expiry_time - last_ts

                # Reset time is when the oldest request expires
                # oldest_request_expiry = oldest_ts + period
                oldest_ts = requests[0][0]
                return int(oldest_ts + period)

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
                current_time = get_current_timestamp()
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
                    # Get current bucket state
                    if bucket_key not in self._token_buckets:
                        self._token_buckets[bucket_key] = TokenBucketState(
                            tokens=initial_tokens,
                            last_refill=current_time,
                        )
                    else:
                        self._token_buckets.move_to_end(bucket_key)

                    bucket_data = self._token_buckets[bucket_key]

                    # Use utility function to calculate token bucket state
                    bucket_state = calculate_token_bucket_state(
                        bucket_data.tokens,
                        bucket_data.last_refill,
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
                        self._token_buckets[bucket_key] = TokenBucketState(
                            tokens=remaining_tokens,
                            last_refill=current_time,
                        )

                        # Use utility function to format metadata
                        metadata = format_token_bucket_metadata(
                            remaining_tokens,
                            bucket_size,
                            refill_rate,
                            bucket_state["time_to_refill"],
                        )
                        metadata.update({"tokens_requested": tokens_requested})

                        self._cleanup_if_needed()

                        log_backend_operation(
                            "token_bucket_check",
                            f"memory backend token bucket check success for key {key}",
                            timer.elapsed_ms,
                        )
                        return True, metadata
                    else:
                        # Request cannot be served - update last_refill time
                        # but don't consume tokens
                        self._token_buckets[bucket_key] = TokenBucketState(
                            tokens=current_tokens,
                            last_refill=current_time,
                        )

                        metadata = format_token_bucket_metadata(
                            current_tokens,
                            bucket_size,
                            refill_rate,
                            bucket_state["time_to_refill"],
                        )
                        metadata.update({"tokens_requested": tokens_requested})

                        self._cleanup_if_needed()

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
                if self.fail_open:
                    # In fail-open mode, we allow the request
                    metadata = format_token_bucket_metadata(
                        bucket_size, bucket_size, refill_rate, 0.0
                    )
                    metadata.update({"tokens_requested": tokens_requested})
                    return True, metadata
                raise BackendError(
                    f"Memory backend token bucket check failed: {str(e)}"
                ) from e

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
        with create_operation_timer() as timer:
            try:
                normalized_key = normalize_key(key, self._key_prefix)
                current_time = get_current_timestamp()
                bucket_key = f"{normalized_key}:token_bucket"

                with self._lock:
                    # Get current bucket state
                    if bucket_key not in self._token_buckets:
                        result = {
                            "tokens_remaining": bucket_size,
                            "bucket_size": bucket_size,
                            "refill_rate": refill_rate,
                            "time_to_refill": 0.0,
                            "last_refill": current_time,
                        }
                    else:
                        bucket_data = self._token_buckets[bucket_key]

                        # Calculate current tokens without updating state
                        time_elapsed = current_time - bucket_data.last_refill
                        tokens_to_add = time_elapsed * refill_rate
                        current_tokens = min(
                            bucket_size, bucket_data.tokens + tokens_to_add
                        )

                        result = {
                            "tokens_remaining": current_tokens,
                            "bucket_size": bucket_size,
                            "refill_rate": refill_rate,
                            "time_to_refill": (
                                max(0, (bucket_size - current_tokens) / refill_rate)
                                if refill_rate > 0
                                else 0
                            ),
                            "last_refill": bucket_data.last_refill,
                        }

                log_backend_operation(
                    "token_bucket_info",
                    f"memory backend token bucket info for key {key}",
                    timer.elapsed_ms,
                )
                return result

            except Exception as e:
                log_backend_operation(
                    "token_bucket_info",
                    f"memory backend token bucket info failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                if self.fail_open:
                    return {
                        "tokens_remaining": bucket_size,
                        "bucket_size": bucket_size,
                        "refill_rate": refill_rate,
                        "time_to_refill": 0.0,
                        "last_refill": get_current_timestamp(),
                    }
                raise BackendError(
                    f"Memory backend token bucket info failed: {str(e)}"
                ) from e

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
                        "expires_at": calculate_expiry(expiration),
                    }
                else:
                    # Store without expiration
                    self._storage[key] = {"value": value, "expires_at": None}
                return True
            except Exception as e:
                log_backend_operation(
                    "set",
                    f"Failed to set key {key} in memory backend: {e}",
                    level="warning",
                )
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
                self._remove_from_partition(key)
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
        now = get_current_timestamp()

        # Check if cleanup is needed (but always cleanup if we're over the limit)
        total_keys = len(self._data) + len(self._token_buckets) + len(self._storage)
        if (
            now - self._last_cleanup < self._cleanup_interval
            and total_keys <= self._max_keys
        ):
            return

        # Use utility function to clean expired entries from generic storage
        self._storage = clean_expired_entries(self._storage, now)

        # Cleanup expired keys from rate limit data using partitions
        # This avoids iterating through all keys
        current_partition = self._get_partition_id(now)

        # Find partitions that are strictly older than current
        # We process keys so we don't modify dict while iterating
        expired_partitions = [
            p for p in self._partitions.keys() if p < current_partition
        ]

        for p_id in expired_partitions:
            # Remove all keys in this partition
            if p_id in self._partitions:
                partition_keys = list(self._partitions[p_id])
                for key in partition_keys:
                    # Remove from data
                    if key in self._data:
                        del self._data[key]

                    # Remove from key map
                    if key in self._key_partition:
                        del self._key_partition[key]

                # Remove partition
                del self._partitions[p_id]

        # If we have too many keys, use LRU cleanup
        # Since we use OrderedDict, we can efficiently pop the oldest items
        total_keys = len(self._data) + len(self._token_buckets) + len(self._storage)

        while total_keys > self._max_keys:
            d_len = len(self._data)
            t_len = len(self._token_buckets)
            s_len = len(self._storage)

            # Heuristic: Evict from the largest collection first, preferring _data
            if d_len > 0 and (d_len >= t_len or t_len == 0):
                key, _ = self._data.popitem(last=False)
                self._remove_from_partition(key)
            elif t_len > 0:
                self._token_buckets.popitem(last=False)
            elif s_len > 0:
                # _storage is treated as unordered, evict arbitrary
                key = next(iter(self._storage))
                del self._storage[key]
            else:
                break

            total_keys = len(self._data) + len(self._token_buckets) + len(self._storage)

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
            self._partitions.clear()
            self._key_partition.clear()

    def get_stats(self) -> Dict[str, Union[int, str, float]]:
        """
        Get enhanced statistics about the memory backend using utilities.

        Returns:
            Dictionary containing comprehensive backend statistics
        """
        from .utils import estimate_backend_memory_usage

        with self._lock:
            active_keys = 0
            total_requests = 0

            for key, (expiry_time, requests) in self._data.items():
                if self._algorithm == "sliding_window" or not is_expired(expiry_time):
                    active_keys += 1
                    total_requests += len(requests)

            # Use utility function to estimate memory usage
            # Estimate for main data
            mem_data = estimate_backend_memory_usage(self._data, "memory")
            total_memory = mem_data["estimated_bytes"]

            # Estimate for token buckets
            # We need to convert dataclasses to dicts for JSON serialization estimate
            token_buckets_dict = {k: asdict(v) for k, v in self._token_buckets.items()}
            mem_tokens = estimate_backend_memory_usage(token_buckets_dict, "memory")
            total_memory += mem_tokens["estimated_bytes"]

            # Estimate for generic storage
            mem_storage = estimate_backend_memory_usage(self._storage, "memory")
            total_memory += mem_storage["estimated_bytes"]

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
                "estimated_memory_mb": 0.0,
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

    def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the Memory backend.

        Returns:
            Dictionary with health status information
        """
        start_time = get_current_timestamp()

        # Memory backend is always healthy if we can run code
        # But we can check memory usage

        total_keys = len(self._data) + len(self._token_buckets) + len(self._storage)

        response_time = get_current_timestamp() - start_time

        return {
            "status": "healthy",
            "response_time": response_time,
            "total_keys": total_keys,
            "max_keys": self._max_keys,
            "cleanup_interval": self._cleanup_interval,
            "algorithm": self._algorithm,
        }
