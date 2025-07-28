"""Database backend for Django Smart Ratelimit."""

import time
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any, Dict, Optional, Tuple

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ..models import RateLimitCounter, RateLimitEntry
from .base import BaseBackend
from .utils import (
    calculate_sliding_window_count,
    calculate_token_bucket_state,
    estimate_backend_memory_usage,
    format_token_bucket_metadata,
    log_backend_operation,
    normalize_key,
    serialize_data,
    validate_backend_config,
)


class DatabaseBackend(BaseBackend):
    """
    Database backend that stores rate limit data in Django models.

    This backend uses Django's ORM to store rate limit entries and counters
    in the database, making it suitable for deployments without Redis.
    """

    def __init__(
        self,
        enable_circuit_breaker: bool = True,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the database backend with optional configuration."""
        # Initialize parent class with circuit breaker
        super().__init__(enable_circuit_breaker, circuit_breaker_config)

        # Validate configuration
        validate_backend_config(kwargs, backend_type="database")

        self.cleanup_threshold = kwargs.get("cleanup_threshold", 1000)

        # Log initialization
        log_backend_operation(
            "database_init",
            f"Database backend initialized with "
            f"cleanup_threshold={self.cleanup_threshold}",
            level="info",
        )

    def _get_window_times(self, window_seconds: int) -> Tuple[datetime, datetime]:
        """
        Get the start and end times for a fixed window.

        Args:
            window_seconds: The window size in seconds

        Returns:
            Tuple of (window_start, window_end) as datetime objects
        """
        now = timezone.now()

        # Calculate the start of the current window
        # For example, if window is 3600 seconds (1 hour) and now is 14:30:00,
        # the window start should be 14:00:00
        seconds_since_epoch = int(now.timestamp())
        window_start_seconds = (seconds_since_epoch // window_seconds) * window_seconds
        window_start = datetime.fromtimestamp(window_start_seconds, tz=dt_timezone.utc)
        window_end = window_start + timedelta(seconds=window_seconds)

        return window_start, window_end

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
        Token bucket check using database storage.

        Note: This implementation is not fully atomic due to database limitations.
        For production use with high concurrency, consider Redis backend.

        Args:
            key: Rate limit key
            bucket_size: Maximum number of tokens in bucket
            refill_rate: Rate at which tokens are added (tokens per second)
            initial_tokens: Initial number of tokens when bucket is created
            tokens_requested: Number of tokens requested for this operation

        Returns:
            Tuple of (is_allowed, metadata_dict)
        """
        # Normalize key using utility
        bucket_key = normalize_key(f"{key}:token_bucket", prefix="")
        current_time = timezone.now()
        current_timestamp = current_time.timestamp()

        start_time = current_timestamp
        try:
            with transaction.atomic():
                # Get or create bucket data stored as JSON in the data field
                (
                    counter,
                    created,
                ) = RateLimitCounter.objects.select_for_update().get_or_create(
                    key=bucket_key,
                    defaults={
                        "count": 0,  # Not used for token bucket
                        "data": serialize_data(
                            {
                                "tokens": initial_tokens,
                                "last_refill": current_timestamp,
                                "bucket_size": bucket_size,
                                "refill_rate": refill_rate,
                            }
                        ),
                        "window_start": current_time,
                        "window_end": current_time + timedelta(days=365),  # Long expiry
                    },
                )

                # Parse bucket data from counter fields
                bucket_data = {
                    "tokens": float(counter.count),  # Use count as token storage
                    "last_refill": counter.updated_at.timestamp(),
                    "bucket_size": bucket_size,
                    "refill_rate": refill_rate,
                }

                # Use utility to calculate new token bucket state
                new_state = calculate_token_bucket_state(
                    current_tokens=bucket_data["tokens"],
                    last_refill=bucket_data["last_refill"],
                    current_time=current_timestamp,
                    bucket_size=bucket_size,
                    refill_rate=refill_rate,
                    tokens_requested=tokens_requested,
                )

                # Check if request can be served
                if new_state["is_allowed"]:
                    # Save token state to counter fields
                    counter.count = int(new_state["tokens_remaining"])
                    counter.save(update_fields=["count", "updated_at"])

                    # Format metadata using utility
                    metadata = format_token_bucket_metadata(
                        tokens_remaining=new_state["tokens_remaining"],
                        tokens_requested=tokens_requested,
                        bucket_size=bucket_size,
                        refill_rate=refill_rate,
                        time_to_refill=new_state["time_to_refill"],
                    )

                    log_backend_operation(
                        "database_token_bucket_check",
                        f"Token bucket check for key {key}: allowed=True",
                        duration=current_timestamp - start_time,
                    )

                    return True, metadata
                else:
                    # Request cannot be served - update last_refill time but
                    # don't consume tokens
                    counter.count = int(new_state["current_tokens"])
                    counter.save(update_fields=["count", "updated_at"])

                    # Format metadata using utility
                    metadata = format_token_bucket_metadata(
                        tokens_remaining=new_state["current_tokens"],
                        tokens_requested=tokens_requested,
                        bucket_size=bucket_size,
                        refill_rate=refill_rate,
                        time_to_refill=new_state["time_to_refill"],
                    )

                    log_backend_operation(
                        "database_token_bucket_check",
                        f"Token bucket check for key {key}: allowed=False",
                        duration=current_timestamp - start_time,
                    )

                    return False, metadata

        except Exception as e:
            log_backend_operation(
                "database_token_bucket_check_error",
                f"Token bucket database error for key {key}: {e}",
                duration=current_timestamp - start_time,
                level="error",
            )
            # Fall back to allowing the request
            return True, format_token_bucket_metadata(
                tokens_remaining=bucket_size,
                tokens_requested=tokens_requested,
                bucket_size=bucket_size,
                refill_rate=refill_rate,
                time_to_refill=0,
            )

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
        bucket_key = normalize_key(f"{key}:token_bucket", prefix="")
        current_time = timezone.now()
        current_timestamp = current_time.timestamp()

        try:
            counter = RateLimitCounter.objects.get(key=bucket_key)

            # Use counter fields instead of non-existent data field
            bucket_data = {
                "tokens": float(counter.count),  # Use count as token storage
                "last_refill": counter.updated_at.timestamp(),
            }

            # Use utility to calculate current state without consuming tokens
            state = calculate_token_bucket_state(
                current_tokens=bucket_data["tokens"],
                last_refill=bucket_data["last_refill"],
                current_time=current_timestamp,
                bucket_size=bucket_size,
                refill_rate=refill_rate,
                tokens_requested=0,  # Don't consume any tokens
            )

            return format_token_bucket_metadata(
                tokens_remaining=state["current_tokens"],
                bucket_size=bucket_size,
                refill_rate=refill_rate,
                time_to_refill=state["time_to_refill"],
                last_refill=bucket_data["last_refill"],
            )

        except RateLimitCounter.DoesNotExist:
            return format_token_bucket_metadata(
                tokens_remaining=bucket_size,
                bucket_size=bucket_size,
                refill_rate=refill_rate,
                time_to_refill=0.0,
                last_refill=current_timestamp,
            )

    # Generic storage methods for algorithm implementations

    def get(self, key: str) -> Any:
        """Get value for a key using database storage."""
        try:
            normalized_key = normalize_key(key, prefix="")
            counter = RateLimitCounter.objects.get(key=normalized_key)
            # Return simple value since we're using this for generic storage
            return counter.count
        except RateLimitCounter.DoesNotExist:
            return None
        except Exception as e:
            log_backend_operation(
                "database_get_error", f"Failed to get key {key}: {e}", level="error"
            )
            return None

    def set(self, key: str, value: Any, expiration: Optional[int] = None) -> bool:
        """Set value for a key with optional expiration using database storage."""
        try:
            normalized_key = normalize_key(key, prefix="")
            current_time = timezone.now()
            expires_at = (
                current_time + timedelta(seconds=expiration)
                if expiration
                else current_time + timedelta(days=365)
            )

            # Serialize value using utility
            serialized_value = serialize_data(value)

            counter, created = RateLimitCounter.objects.update_or_create(
                key=normalized_key,
                defaults={
                    "count": 0,
                    "data": serialized_value,
                    "window_start": current_time,
                    "window_end": expires_at,
                },
            )
            return True
        except Exception as e:
            log_backend_operation(
                "database_set_error", f"Failed to set key {key}: {e}", level="error"
            )
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from database storage."""
        try:
            normalized_key = normalize_key(key, prefix="")
            deleted_count, _ = RateLimitCounter.objects.filter(
                key=normalized_key
            ).delete()
            # Also delete from RateLimitEntry if it exists there
            RateLimitEntry.objects.filter(key=normalized_key).delete()

            log_backend_operation(
                "database_delete",
                f"Deleted key {key}",
            )

            return deleted_count > 0
        except Exception as e:
            log_backend_operation(
                "database_delete_error",
                f"Failed to delete key {key}: {e}",
                level="error",
            )
            return False

    def _incr_sliding_window(self, key: str, window_seconds: int) -> int:
        """
        Increment counter for sliding window algorithm.

        Args:
            key: The rate limit key
            window_seconds: The window size in seconds

        Returns:
            Current count in the window
        """
        normalized_key = normalize_key(key, prefix="")
        now = timezone.now()
        expires_at = now + timedelta(seconds=window_seconds)

        start_time = now.timestamp()
        try:
            with transaction.atomic():
                # Clean expired entries
                RateLimitEntry.objects.filter(
                    key=normalized_key, expires_at__lt=now
                ).delete()

                # Add new entry
                RateLimitEntry.objects.create(
                    key=normalized_key,
                    timestamp=now,
                    expires_at=expires_at,
                    algorithm="sliding_window",
                )

                # Count current entries in the window using utility
                entries = list(
                    RateLimitEntry.objects.filter(
                        key=normalized_key,
                        timestamp__gte=now - timedelta(seconds=window_seconds),
                    ).values_list("timestamp", "id")
                )

                count = calculate_sliding_window_count(
                    [(entry[0].timestamp(), str(entry[1])) for entry in entries],
                    window_seconds,
                    now.timestamp(),
                )

                log_backend_operation(
                    "database_incr_sliding_window",
                    f"Incremented sliding window for key {key} to count {count}",
                    duration=now.timestamp() - start_time,
                )

                return count

        except Exception as e:
            log_backend_operation(
                "database_incr_sliding_window_error",
                f"Failed to increment sliding window for key {key}: {e}",
                duration=now.timestamp() - start_time,
                level="error",
            )
            raise

    def _incr_fixed_window(self, key: str, window_seconds: int) -> int:
        """
        Increment counter for fixed window algorithm using atomic database operations.

        Args:
            key: The rate limit key
            window_seconds: The window size in seconds

        Returns:
            Current count in the window
        """
        normalized_key = normalize_key(key, prefix="")
        window_start, window_end = self._get_window_times(window_seconds)

        start_time = timezone.now().timestamp()
        try:
            with transaction.atomic():
                # Try to get existing counter for current window
                counter, created = RateLimitCounter.objects.get_or_create(
                    key=normalized_key,
                    defaults={
                        "count": 1,  # Start with 1 for new counter
                        "window_start": window_start,
                        "window_end": window_end,
                    },
                )

                if created:
                    # New counter created with count=1
                    log_backend_operation(
                        "database_incr_fixed_window",
                        f"Created new fixed window counter for key {key}: count=1",
                        duration=timezone.now().timestamp() - start_time,
                    )
                    return 1

                # Counter exists - check if it's from the current window
                if (
                    counter.window_start != window_start
                    or counter.window_end != window_end
                ):
                    # Reset counter for new window using atomic update
                    counter.count = 1
                    counter.window_start = window_start
                    counter.window_end = window_end
                    counter.save()

                    log_backend_operation(
                        "database_incr_fixed_window",
                        f"Reset fixed window counter for key {key}: count=1",
                        duration=timezone.now().timestamp() - start_time,
                    )
                    return 1
                else:
                    # Increment existing counter atomically using F() expression
                    RateLimitCounter.objects.filter(
                        key=normalized_key,
                        window_start=window_start,
                        window_end=window_end,
                    ).update(count=F("count") + 1)

                    # Refresh from database to get the updated count
                    counter.refresh_from_db()

                    log_backend_operation(
                        "database_incr_fixed_window",
                        f"Incremented fixed window counter for key {key}: "
                        f"count={counter.count}",
                        duration=timezone.now().timestamp() - start_time,
                    )
                    return counter.count

        except Exception as e:
            log_backend_operation(
                "database_incr_fixed_window_error",
                f"Failed to increment fixed window for key {key}: {e}",
                duration=timezone.now().timestamp() - start_time,
                level="error",
            )
            raise

    def incr(self, key: str, period: int) -> int:
        """
        Increment the counter for the given key within the time period.

        Args:
            key: The rate limit key
            period: Time period in seconds

        Returns:
            Current count after increment
        """
        # Use sliding window by default to match the base behavior
        return self._incr_sliding_window(key, period)

    def get_count(self, key: str) -> int:
        """
        Get the current count for the given key.

        Args:
            key: The rate limit key

        Returns:
            Current count (0 if key doesn't exist)
        """
        # For the base interface, we need to make assumptions about the window
        # We'll use a sliding window approach and check the last hour
        return self._get_count_sliding_window(key, 3600)

    def _get_count_sliding_window(self, key: str, window_seconds: int) -> int:
        """Get count for sliding window algorithm."""
        normalized_key = normalize_key(key, prefix="")
        now = timezone.now()
        window_start = now - timedelta(seconds=window_seconds)

        try:
            # Clean up expired entries
            RateLimitEntry.objects.filter(
                key=normalized_key, expires_at__lt=now
            ).delete()

            # Count current entries in the window
            count = RateLimitEntry.objects.filter(
                key=normalized_key, timestamp__gte=window_start
            ).count()

            return count
        except Exception as e:
            log_backend_operation(
                "database_get_count_sliding_window_error",
                f"Failed to get sliding window count for key {key}: {e}",
                level="error",
            )
            return 0

    def _get_count_fixed_window(self, key: str, window_seconds: int) -> int:
        """Get count for fixed window algorithm."""
        normalized_key = normalize_key(key, prefix="")
        window_start, window_end = self._get_window_times(window_seconds)

        try:
            counter = RateLimitCounter.objects.get(key=normalized_key)

            # Check if counter is from current window
            if (
                counter.window_start == window_start
                and counter.window_end == window_end
            ):
                return counter.count
            else:
                # Counter is from a different window, so count is 0
                return 0

        except RateLimitCounter.DoesNotExist:
            return 0
        except Exception as e:
            log_backend_operation(
                "database_get_count_fixed_window_error",
                f"Failed to get fixed window count for key {key}: {e}",
                level="error",
            )
            return 0

    def get_reset_time(self, key: str) -> Optional[int]:
        """
        Get the timestamp when the key will reset.

        Args:
            key: The rate limit key

        Returns:
            Unix timestamp when key expires, or None if key doesn't exist
        """
        # For the base interface, we need to make assumptions about the window
        # We'll use a sliding window approach and check the last hour
        return self._get_reset_time_sliding_window(key, 3600)

    def _get_reset_time_sliding_window(
        self, key: str, window_seconds: int
    ) -> Optional[int]:
        """Get reset time for sliding window algorithm."""
        # For sliding window, find the oldest entry
        oldest_entry = (
            RateLimitEntry.objects.filter(key=key).order_by("timestamp").first()
        )

        if oldest_entry:
            reset_time = oldest_entry.timestamp + timedelta(seconds=window_seconds)
            return int(reset_time.timestamp())

        return None

    def _get_reset_time_fixed_window(
        self, key: str, window_seconds: int
    ) -> Optional[int]:
        """Get reset time for fixed window algorithm."""
        try:
            counter = RateLimitCounter.objects.get(key=key)

            window_start, window_end = self._get_window_times(window_seconds)

            # Check if counter is from current window
            if (
                counter.window_start == window_start
                and counter.window_end == window_end
            ):
                return int(counter.window_end.timestamp())
            else:
                # Counter is from a different window, return None
                return None

        except RateLimitCounter.DoesNotExist:
            return None

    def reset(self, key: str) -> None:
        """
        Reset the counter for the given key.

        Args:
            key: The rate limit key to reset
        """
        normalized_key = normalize_key(key, prefix="")

        start_time = timezone.now().timestamp()
        try:
            # Reset both sliding window entries and fixed window counters
            deleted_entries = RateLimitEntry.objects.filter(
                key=normalized_key
            ).delete()[0]
            deleted_counters = RateLimitCounter.objects.filter(
                key=normalized_key
            ).delete()[0]

            log_backend_operation(
                "database_reset",
                f"Reset key {key}: deleted {deleted_entries} entries, "
                f"{deleted_counters} counters",
                duration=timezone.now().timestamp() - start_time,
            )
        except Exception as e:
            log_backend_operation(
                "database_reset_error",
                f"Failed to reset key {key}: {e}",
                duration=timezone.now().timestamp() - start_time,
                level="error",
            )
            raise

    # Extended methods for specific algorithms

    def incr_with_algorithm(
        self, key: str, window_seconds: int, algorithm: str = "sliding_window"
    ) -> int:
        """
        Increment the rate limit counter for a key with specific algorithm.

        Args:
            key: The rate limit key
            window_seconds: The window size in seconds
            algorithm: The algorithm to use ("sliding_window" or "fixed_window")

        Returns:
            Current count in the window
        """
        # Input validation
        if not key or not key.strip():
            raise ValueError("Key cannot be empty")

        if window_seconds <= 0:
            raise ValueError("Window seconds must be positive")

        if len(key) > 255:
            raise ValueError("Key length cannot exceed 255 characters")

        if algorithm == "fixed_window":
            return self._incr_fixed_window(key, window_seconds)
        else:
            # Default to sliding window for unknown algorithms
            return self._incr_sliding_window(key, window_seconds)

    def get_count_with_algorithm(
        self, key: str, window_seconds: int, algorithm: str = "sliding_window"
    ) -> int:
        """
        Get the current count for a key with specific algorithm.

        Args:
            key: The rate limit key
            window_seconds: The window size in seconds
            algorithm: The algorithm to use ("sliding_window" or "fixed_window")

        Returns:
            Current count in the window
        """
        # Input validation
        if not key or not key.strip():
            raise ValueError("Key cannot be empty")

        if window_seconds <= 0:
            raise ValueError("Window seconds must be positive")

        if len(key) > 255:
            raise ValueError("Key length cannot exceed 255 characters")

        if algorithm == "fixed_window":
            return self._get_count_fixed_window(key, window_seconds)
        else:
            return self._get_count_sliding_window(key, window_seconds)

    def get_reset_time_with_algorithm(
        self, key: str, window_seconds: int, algorithm: str = "sliding_window"
    ) -> Optional[int]:
        """
        Get the time when the rate limit will reset with specific algorithm.

        Args:
            key: The rate limit key
            window_seconds: The window size in seconds
            algorithm: The algorithm to use ("sliding_window" or "fixed_window")

        Returns:
            Unix timestamp when the limit resets, or None if no limit is set
        """
        if algorithm == "fixed_window":
            return self._get_reset_time_fixed_window(key, window_seconds)
        else:
            return self._get_reset_time_sliding_window(key, window_seconds)

    def reset_with_algorithm(
        self, key: str, _window_seconds: int, algorithm: str = "sliding_window"
    ) -> bool:
        """
        Reset the rate limit for a key with specific algorithm.

        Args:
            key: The rate limit key
            window_seconds: The window size in seconds
            algorithm: The algorithm to use ("sliding_window" or "fixed_window")

        Returns:
            True if reset was successful
        """
        if algorithm == "fixed_window":
            # Reset fixed window counter
            RateLimitCounter.objects.filter(key=key).delete()
        else:
            # Reset sliding window entries
            RateLimitEntry.objects.filter(key=key).delete()

        return True

    def cleanup_expired(self) -> int:
        """
        Clean up expired rate limit entries using backend utilities.

        Returns:
            Number of entries cleaned up
        """
        now = timezone.now()
        total_cleaned = 0

        start_time = now.timestamp()
        try:
            # Clean up expired sliding window entries
            sliding_entries = RateLimitEntry.objects.filter(expires_at__lt=now)
            sliding_count = sliding_entries.count()
            sliding_entries.delete()
            total_cleaned += sliding_count

            # Clean up expired fixed window counters
            fixed_counters = RateLimitCounter.objects.filter(window_end__lt=now)
            fixed_count = fixed_counters.count()
            fixed_counters.delete()
            total_cleaned += fixed_count

            log_backend_operation(
                "database_cleanup_expired",
                f"Cleaned up {total_cleaned} expired entries",
                duration=timezone.now().timestamp() - start_time,
            )

        except Exception as e:
            log_backend_operation(
                "database_cleanup_expired_error",
                f"Failed to cleanup expired entries: {e}",
                duration=timezone.now().timestamp() - start_time,
                level="error",
            )

        return total_cleaned

    def _cleanup_expired_entries(self, _force: bool = False) -> int:
        """
        Clean up expired entries. Alias for cleanup_expired method.

        Args:
            force: If True, force cleanup regardless of threshold

        Returns:
            Number of entries cleaned up
        """
        return self.cleanup_expired()

    def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the database backend using backend utilities.

        Returns:
            Dictionary with health status information
        """
        start_time = time.time()
        try:
            from django.db import connection

            # Test database connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")

            # Test table access
            entry_count = RateLimitEntry.objects.count()
            counter_count = RateLimitCounter.objects.count()

            # Test write operations
            test_key = f"__health_check_{int(time.time())}"
            self.incr(test_key, 60)
            self.reset(test_key)

            # Estimate memory usage using utility
            memory_data = {
                "entry_count": entry_count,
                "counter_count": counter_count,
                "total_records": entry_count + counter_count,
            }

            memory_usage = estimate_backend_memory_usage(
                memory_data, backend_type="database"
            )

            health_data = {
                "status": "healthy",
                "healthy": True,
                "backend": "database",
                "response_time": time.time() - start_time,
                "details": {
                    "database_connection": "OK",
                    "table_access": "OK",
                    "write_operations": "OK",
                    "entry_count": entry_count,
                    "counter_count": counter_count,
                    "total_records": entry_count + counter_count,
                    "estimated_memory_usage": memory_usage,
                    "cleanup_threshold": self.cleanup_threshold,
                },
            }

            response_time = time.time() - start_time
            log_backend_operation(
                "database_health_check",
                f"Health check successful: {health_data['status']}",
                duration=response_time,
            )

            return health_data

        except Exception as e:
            log_backend_operation(
                "database_health_check_error",
                f"Health check failed: {e}",
                duration=float(time.time() - start_time),
                level="error",
            )
            return {
                "status": "unhealthy",
                "healthy": False,
                "backend": "database",
                "error": str(e),
                "response_time": time.time() - start_time,
                "details": {
                    "database_connection": f"Failed: {e}",
                    "table_access": "Unknown",
                    "write_operations": "Unknown",
                },
            }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the rate limit storage.

        Returns:
            Dictionary with storage statistics
        """
        now = timezone.now()

        stats = {
            "backend": "database",
            "entries": {
                "total": RateLimitEntry.objects.count(),
                "expired": RateLimitEntry.objects.filter(expires_at__lt=now).count(),
                "active": RateLimitEntry.objects.filter(expires_at__gte=now).count(),
            },
            "counters": {
                "total": RateLimitCounter.objects.count(),
                "expired": RateLimitCounter.objects.filter(window_end__lt=now).count(),
                "active": RateLimitCounter.objects.filter(window_end__gte=now).count(),
            },
            "cleanup": {
                "threshold": self.cleanup_threshold,
                "last_cleanup": None,  # Could be implemented if needed
            },
        }

        return stats
