"""
SQL database backend for rate limiting.

This backend stores rate limiting data in a SQL database using Django's ORM.
It supports PostgreSQL, MySQL, and SQLite with database-specific optimizations
for atomic operations.

Features:
- Atomic operations using database transactions
- Support for fixed window, sliding window, and token bucket algorithms
- Automatic cleanup of expired entries
- Database-specific optimizations for performance
- Integration with Django's database connection pooling
"""

import logging
import threading
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple, cast

from django.db import DatabaseError, connection, transaction
from django.db.models import F
from django.utils import timezone

from ..exceptions import BackendError
from ..messages import ERROR_BACKEND_UNAVAILABLE
from .base import BaseBackend
from .utils import (
    create_operation_timer,
    format_token_bucket_metadata,
    log_backend_operation,
    normalize_key,
)

logger = logging.getLogger(__name__)


class DatabaseBackend(BaseBackend):
    """
    SQL database backend for rate limiting.

    Supports PostgreSQL, MySQL, and SQLite with database-level
    locking for atomic operations.

    Features:
    - Thread-safe operations using database transactions
    - Automatic cleanup of expired entries
    - Fixed window, sliding window, and token bucket algorithm support
    - Database-specific optimizations

    Configuration:
        algorithm: Algorithm to use ('fixed_window', 'sliding_window', 'token_bucket')
        cleanup_interval: Seconds between cleanup runs (default: 300)
        batch_cleanup_size: Number of records to delete per cleanup batch (default: 1000)
        fail_open: Allow requests on backend failure (default: False)
    """

    name = "database"

    def __init__(
        self,
        algorithm: str = "fixed_window",
        fail_open: bool = False,
        cleanup_interval: int = 300,
        batch_cleanup_size: int = 1000,
        enable_circuit_breaker: bool = True,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
        enable_background_cleanup: bool = True,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the database backend.

        Args:
            algorithm: Rate limiting algorithm to use
            fail_open: Allow requests on backend failure
            cleanup_interval: Seconds between cleanup runs
            batch_cleanup_size: Number of records to delete per cleanup batch
            enable_circuit_breaker: Whether to enable circuit breaker protection
            circuit_breaker_config: Custom circuit breaker configuration
            enable_background_cleanup: Whether to run cleanup in background thread
        """
        # Read Django settings
        from django_smart_ratelimit.config import get_settings

        settings = get_settings()

        # Initialize parent class
        super().__init__(
            enable_circuit_breaker=enable_circuit_breaker,
            circuit_breaker_config=circuit_breaker_config,
            fail_open=fail_open if fail_open else settings.fail_open,
            **kwargs,
        )

        self._algorithm = algorithm or settings.default_algorithm
        self._cleanup_interval = cleanup_interval
        self._batch_cleanup_size = batch_cleanup_size
        self._key_prefix = settings.key_prefix

        # Cleanup tracking
        self._last_cleanup = timezone.now()
        self._cleanup_lock = threading.Lock()

        # Background cleanup thread
        self._shutdown_event = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None

        if enable_background_cleanup:
            self._start_cleanup_thread()

    def _start_cleanup_thread(self) -> None:
        """Start background cleanup thread."""
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="ratelimit-db-cleanup",
        )
        self._cleanup_thread.start()

    def _cleanup_loop(self) -> None:
        """Background cleanup loop."""
        import time

        while not self._shutdown_event.is_set():
            time.sleep(self._cleanup_interval)
            if self._shutdown_event.is_set():
                break
            try:
                self.cleanup_expired()
            except Exception as e:
                log_backend_operation("cleanup_error", str(e), level="error")

    def shutdown(self) -> None:
        """Stop background cleanup thread."""
        self._shutdown_event.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=1.0)

    def _get_db_vendor(self) -> str:
        """Get the database vendor name."""
        return connection.vendor

    def _normalize_key(self, key: str) -> str:
        """Normalize a rate limit key."""
        return normalize_key(key, self._key_prefix)

    def incr(self, key: str, period: int) -> int:
        """
        Increment the counter for the given key within the time period.

        Uses the configured algorithm (fixed_window or sliding_window).

        Args:
            key: The rate limit key
            period: Time period in seconds

        Returns:
            Current count after increment
        """
        with create_operation_timer() as timer:
            try:
                normalized_key = self._normalize_key(key)

                if self._algorithm == "sliding_window":
                    result = self._incr_sliding_window(normalized_key, period)
                else:
                    result = self._incr_fixed_window(normalized_key, period)

                log_backend_operation(
                    "incr",
                    f"database backend increment for key {key}",
                    timer.elapsed_ms,
                )
                return result

            except DatabaseError as e:
                log_backend_operation(
                    "incr",
                    f"database backend increment failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                allowed, _ = self._handle_backend_error("incr", key, e)
                return 0 if allowed else 9999

    def _incr_fixed_window(self, key: str, period: int) -> int:
        """Increment counter using fixed window algorithm."""
        from ..models import RateLimitCounter

        now = timezone.now()
        window_start = now.replace(microsecond=0)
        # Align window to period boundary
        seconds_into_period = int(window_start.timestamp()) % period
        window_start = window_start - timedelta(seconds=seconds_into_period)
        window_end = window_start + timedelta(seconds=period)

        with transaction.atomic():
            # Try to get existing counter or create new one
            (
                counter,
                created,
            ) = RateLimitCounter.objects.select_for_update().get_or_create(
                key=key,
                window_start=window_start,
                defaults={
                    "count": 1,
                    "window_end": window_end,
                },
            )

            if not created:
                # Increment existing counter atomically
                counter.count = cast(int, F("count") + 1)
                counter.save(update_fields=["count", "updated_at"])
                counter.refresh_from_db()

            return counter.count

    def _incr_sliding_window(self, key: str, period: int) -> int:
        """Increment counter using sliding window algorithm."""
        from ..models import RateLimitEntry

        now = timezone.now()
        window_start = now - timedelta(seconds=period)
        expires_at = now + timedelta(seconds=period)

        with transaction.atomic():
            # Add new entry
            RateLimitEntry.objects.create(
                key=key,
                timestamp=now,
                expires_at=expires_at,
            )

            # Count entries in window
            count = RateLimitEntry.objects.filter(
                key=key,
                timestamp__gte=window_start,
            ).count()

            return count

    def reset(self, key: str) -> None:
        """
        Reset the counter for the given key.

        Args:
            key: The rate limit key to reset
        """
        with create_operation_timer() as timer:
            try:
                normalized_key = self._normalize_key(key)

                from ..models import (
                    RateLimitCounter,
                    RateLimitEntry,
                    RateLimitLeakyBucket,
                    RateLimitTokenBucket,
                )

                with transaction.atomic():
                    # Delete from all tables
                    RateLimitCounter.objects.filter(key=normalized_key).delete()
                    RateLimitEntry.objects.filter(key=normalized_key).delete()
                    RateLimitTokenBucket.objects.filter(key=normalized_key).delete()
                    RateLimitLeakyBucket.objects.filter(key=normalized_key).delete()

                log_backend_operation(
                    "reset",
                    f"database backend reset for key {key}",
                    timer.elapsed_ms,
                )

            except DatabaseError as e:
                log_backend_operation(
                    "reset",
                    f"database backend reset failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                allowed, _ = self._handle_backend_error("reset", key, e)
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
                normalized_key = self._normalize_key(key)

                if self._algorithm == "sliding_window":
                    result = self._get_count_sliding_window(normalized_key, period)
                else:
                    result = self._get_count_fixed_window(normalized_key, period)

                log_backend_operation(
                    "get_count",
                    f"database backend get_count for key {key}",
                    timer.elapsed_ms,
                )
                return result

            except DatabaseError as e:
                log_backend_operation(
                    "get_count",
                    f"database backend get_count failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                allowed, _ = self._handle_backend_error("get_count", key, e)
                return 0 if allowed else 9999

    def _get_count_fixed_window(self, key: str, period: int) -> int:
        """Get count using fixed window algorithm."""
        from ..models import RateLimitCounter

        now = timezone.now()
        window_start = now.replace(microsecond=0)
        seconds_into_period = int(window_start.timestamp()) % period
        window_start = window_start - timedelta(seconds=seconds_into_period)

        counter = RateLimitCounter.objects.filter(
            key=key,
            window_start=window_start,
        ).first()

        return counter.count if counter else 0

    def _get_count_sliding_window(self, key: str, period: int) -> int:
        """Get count using sliding window algorithm."""
        from ..models import RateLimitEntry

        now = timezone.now()
        window_start = now - timedelta(seconds=period)

        return RateLimitEntry.objects.filter(
            key=key,
            timestamp__gte=window_start,
        ).count()

    def get_reset_time(self, key: str) -> Optional[int]:
        """
        Get the timestamp when the key will reset.

        Args:
            key: The rate limit key

        Returns:
            Unix timestamp when key expires, or None if key doesn't exist
        """
        normalized_key = self._normalize_key(key)

        if self._algorithm == "sliding_window":
            from ..models import RateLimitEntry

            # For sliding window, reset time is when the oldest entry expires
            oldest = (
                RateLimitEntry.objects.filter(
                    key=normalized_key,
                )
                .order_by("timestamp")
                .first()
            )

            if oldest:
                return int(oldest.expires_at.timestamp())
            return None
        else:
            from ..models import RateLimitCounter

            # For fixed window, reset time is window_end
            counter = (
                RateLimitCounter.objects.filter(
                    key=normalized_key,
                    window_end__gt=timezone.now(),
                )
                .order_by("-window_start")
                .first()
            )

            if counter:
                return int(counter.window_end.timestamp())
            return None

    def token_bucket_check(
        self,
        key: str,
        bucket_size: int,
        refill_rate: float,
        initial_tokens: int,
        tokens_requested: int,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Token bucket rate limit check using database storage.

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
                normalized_key = self._normalize_key(key)

                # Handle edge case: zero bucket size
                if bucket_size <= 0:
                    metadata = format_token_bucket_metadata(
                        0, bucket_size, refill_rate, float("inf")
                    )
                    metadata["tokens_requested"] = tokens_requested
                    return False, metadata

                from ..models import RateLimitTokenBucket

                with transaction.atomic():
                    # Get or create bucket with lock
                    (
                        bucket,
                        created,
                    ) = RateLimitTokenBucket.objects.select_for_update().get_or_create(
                        key=normalized_key,
                        defaults={
                            "tokens": initial_tokens,
                            "last_update": timezone.now(),
                            "bucket_size": bucket_size,
                            "refill_rate": refill_rate,
                        },
                    )

                    # Calculate current tokens with refill
                    now = timezone.now()
                    if not created:
                        elapsed = (now - bucket.last_update).total_seconds()
                        refilled = bucket.tokens + (elapsed * refill_rate)
                        current_tokens = min(refilled, bucket_size)
                    else:
                        current_tokens = initial_tokens

                    # Check if we have enough tokens
                    if current_tokens >= tokens_requested:
                        # Consume tokens
                        remaining = current_tokens - tokens_requested
                        bucket.tokens = remaining
                        bucket.last_update = now
                        bucket.save(update_fields=["tokens", "last_update"])

                        time_to_refill = (
                            (bucket_size - remaining) / refill_rate
                            if refill_rate > 0
                            else 0
                        )

                        metadata = format_token_bucket_metadata(
                            remaining, bucket_size, refill_rate, time_to_refill
                        )
                        metadata["tokens_requested"] = tokens_requested

                        log_backend_operation(
                            "token_bucket_check",
                            f"database backend token bucket check success for key {key}",
                            timer.elapsed_ms,
                        )
                        return True, metadata
                    else:
                        # Not enough tokens - update last_update but don't consume
                        bucket.tokens = current_tokens
                        bucket.last_update = now
                        bucket.save(update_fields=["tokens", "last_update"])

                        tokens_needed = tokens_requested - current_tokens
                        time_to_refill = (
                            tokens_needed / refill_rate
                            if refill_rate > 0
                            else float("inf")
                        )

                        metadata = format_token_bucket_metadata(
                            current_tokens, bucket_size, refill_rate, time_to_refill
                        )
                        metadata["tokens_requested"] = tokens_requested

                        log_backend_operation(
                            "token_bucket_check",
                            f"database backend token bucket check rejected for key {key}",
                            timer.elapsed_ms,
                        )
                        return False, metadata

            except DatabaseError as e:
                log_backend_operation(
                    "token_bucket_check",
                    f"database backend token bucket check failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                if self.fail_open:
                    metadata = format_token_bucket_metadata(
                        bucket_size, bucket_size, refill_rate, 0.0
                    )
                    metadata["tokens_requested"] = tokens_requested
                    return True, metadata
                raise BackendError(
                    f"Database backend token bucket check failed: {str(e)}"
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
                normalized_key = self._normalize_key(key)

                from ..models import RateLimitTokenBucket

                bucket = RateLimitTokenBucket.objects.filter(key=normalized_key).first()

                now = timezone.now()

                if not bucket:
                    return {
                        "tokens_remaining": bucket_size,
                        "bucket_size": bucket_size,
                        "refill_rate": refill_rate,
                        "time_to_refill": 0.0,
                        "last_refill": now.timestamp(),
                    }

                # Calculate current tokens
                elapsed = (now - bucket.last_update).total_seconds()
                refilled = bucket.tokens + (elapsed * refill_rate)
                current_tokens = min(refilled, bucket_size)

                time_to_refill = (
                    max(0, (bucket_size - current_tokens) / refill_rate)
                    if refill_rate > 0
                    else 0
                )

                log_backend_operation(
                    "token_bucket_info",
                    f"database backend token bucket info for key {key}",
                    timer.elapsed_ms,
                )

                return {
                    "tokens_remaining": current_tokens,
                    "bucket_size": bucket_size,
                    "refill_rate": refill_rate,
                    "time_to_refill": time_to_refill,
                    "last_refill": bucket.last_update.timestamp(),
                }

            except DatabaseError as e:
                log_backend_operation(
                    "token_bucket_info",
                    f"database backend token bucket info failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                if self.fail_open:
                    return {
                        "tokens_remaining": bucket_size,
                        "bucket_size": bucket_size,
                        "refill_rate": refill_rate,
                        "time_to_refill": 0.0,
                        "last_refill": timezone.now().timestamp(),
                    }
                raise BackendError(
                    f"Database backend token bucket info failed: {str(e)}"
                ) from e

    def leaky_bucket_check(
        self,
        key: str,
        bucket_capacity: int,
        leak_rate: float,
        request_cost: int,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Leaky bucket rate limit check using database storage.

        The leaky bucket fills with requests and drains at a constant rate.
        When full, new requests are rejected until space is available.

        Args:
            key: Rate limit key
            bucket_capacity: Maximum fill level of the bucket
            leak_rate: Rate at which bucket drains (requests per second)
            request_cost: How much this request fills the bucket

        Returns:
            Tuple of (is_allowed, metadata_dict)
        """
        with create_operation_timer() as timer:
            try:
                normalized_key = self._normalize_key(key)

                # Handle edge case: zero bucket capacity
                if bucket_capacity <= 0:
                    metadata = {
                        "bucket_level": 0,
                        "bucket_capacity": bucket_capacity,
                        "leak_rate": leak_rate,
                        "request_cost": request_cost,
                        "space_remaining": 0,
                        "time_until_space": float("inf"),
                    }
                    return False, metadata

                from ..models import RateLimitLeakyBucket

                with transaction.atomic():
                    # Get or create bucket with lock
                    (
                        bucket,
                        created,
                    ) = RateLimitLeakyBucket.objects.select_for_update().get_or_create(
                        key=normalized_key,
                        defaults={
                            "level": 0,
                            "last_leak": timezone.now(),
                            "bucket_capacity": bucket_capacity,
                            "leak_rate": leak_rate,
                        },
                    )

                    # Calculate current level after leaking
                    now = timezone.now()
                    if not created:
                        elapsed = (now - bucket.last_leak).total_seconds()
                        leaked = elapsed * leak_rate
                        current_level = max(0, bucket.level - leaked)
                    else:
                        current_level = 0

                    # Check if request can be accepted
                    new_level = current_level + request_cost

                    if new_level <= bucket_capacity:
                        # Accept request - add to bucket
                        bucket.level = new_level
                        bucket.last_leak = now
                        bucket.save(update_fields=["level", "last_leak"])

                        space_remaining = bucket_capacity - new_level
                        time_until_space = (
                            0.0
                            if space_remaining > 0
                            else (
                                request_cost / leak_rate
                                if leak_rate > 0
                                else float("inf")
                            )
                        )

                        metadata = {
                            "bucket_level": new_level,
                            "bucket_capacity": bucket_capacity,
                            "leak_rate": leak_rate,
                            "request_cost": request_cost,
                            "space_remaining": space_remaining,
                            "time_until_space": time_until_space,
                        }

                        log_backend_operation(
                            "leaky_bucket_check",
                            f"database backend leaky bucket check success for key {key}",
                            timer.elapsed_ms,
                        )
                        return True, metadata
                    else:
                        # Reject request - bucket would overflow
                        bucket.level = current_level
                        bucket.last_leak = now
                        bucket.save(update_fields=["level", "last_leak"])

                        overflow = new_level - bucket_capacity
                        time_until_space = (
                            overflow / leak_rate if leak_rate > 0 else float("inf")
                        )

                        metadata = {
                            "bucket_level": current_level,
                            "bucket_capacity": bucket_capacity,
                            "leak_rate": leak_rate,
                            "request_cost": request_cost,
                            "space_remaining": max(0, bucket_capacity - current_level),
                            "time_until_space": time_until_space,
                        }

                        log_backend_operation(
                            "leaky_bucket_check",
                            f"database backend leaky bucket check rejected for key {key}",
                            timer.elapsed_ms,
                        )
                        return False, metadata

            except DatabaseError as e:
                log_backend_operation(
                    "leaky_bucket_check",
                    f"database backend leaky bucket check failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                if self.fail_open:
                    metadata = {
                        "bucket_level": 0,
                        "bucket_capacity": bucket_capacity,
                        "leak_rate": leak_rate,
                        "request_cost": request_cost,
                        "space_remaining": bucket_capacity,
                        "time_until_space": 0.0,
                    }
                    return True, metadata
                raise BackendError(
                    f"Database backend leaky bucket check failed: {str(e)}"
                ) from e

    def leaky_bucket_info(
        self, key: str, bucket_capacity: int, leak_rate: float
    ) -> Dict[str, Any]:
        """
        Get leaky bucket information without adding to the bucket.

        Args:
            key: Rate limit key
            bucket_capacity: Maximum fill level of the bucket
            leak_rate: Rate at which bucket drains (requests per second)

        Returns:
            Dictionary with current bucket state
        """
        with create_operation_timer() as timer:
            try:
                normalized_key = self._normalize_key(key)

                from ..models import RateLimitLeakyBucket

                bucket = RateLimitLeakyBucket.objects.filter(key=normalized_key).first()

                now = timezone.now()

                if not bucket:
                    return {
                        "bucket_level": 0,
                        "bucket_capacity": bucket_capacity,
                        "leak_rate": leak_rate,
                        "space_remaining": bucket_capacity,
                        "time_to_empty": 0.0,
                        "last_leak": now.timestamp(),
                    }

                # Calculate current level after leaking
                elapsed = (now - bucket.last_leak).total_seconds()
                leaked = elapsed * leak_rate
                current_level = max(0, bucket.level - leaked)

                space_remaining = bucket_capacity - current_level
                time_to_empty = current_level / leak_rate if leak_rate > 0 else 0

                log_backend_operation(
                    "leaky_bucket_info",
                    f"database backend leaky bucket info for key {key}",
                    timer.elapsed_ms,
                )

                return {
                    "bucket_level": current_level,
                    "bucket_capacity": bucket_capacity,
                    "leak_rate": leak_rate,
                    "space_remaining": space_remaining,
                    "time_to_empty": time_to_empty,
                    "last_leak": bucket.last_leak.timestamp(),
                }

            except DatabaseError as e:
                log_backend_operation(
                    "leaky_bucket_info",
                    f"database backend leaky bucket info failed for key {key}: {str(e)}",
                    timer.elapsed_ms,
                    "error",
                )
                if self.fail_open:
                    return {
                        "bucket_level": 0,
                        "bucket_capacity": bucket_capacity,
                        "leak_rate": leak_rate,
                        "space_remaining": bucket_capacity,
                        "time_to_empty": 0.0,
                        "last_leak": timezone.now().timestamp(),
                    }
                raise BackendError(
                    f"Database backend leaky bucket info failed: {str(e)}"
                ) from e

    def check_rate_limit(
        self,
        key: str,
        limit: int,
        period: int,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check rate limit for a key.

        Args:
            key: Rate limit key
            limit: Allowed requests
            period: Time window in seconds

        Returns:
            Tuple (allowed, Check metadata)
        """
        try:
            count = self.incr(key, period)
            allowed = count <= limit
            remaining = max(0, limit - count)

            return allowed, {
                "count": count,
                "remaining": remaining,
                "limit": limit,
                "period": period,
            }
        except Exception as e:
            return self._handle_backend_error("check_rate_limit", key, e)

    def cleanup_expired(self) -> Dict[str, int]:
        """
        Clean up expired entries from all tables.

        Returns:
            Dictionary with count of deleted records per table
        """
        from ..models import (
            RateLimitCounter,
            RateLimitEntry,
            RateLimitLeakyBucket,
            RateLimitTokenBucket,
        )

        with self._cleanup_lock:
            deleted = {
                "counters": RateLimitCounter.cleanup_expired(self._batch_cleanup_size),
                "entries": RateLimitEntry.cleanup_expired(self._batch_cleanup_size),
                "token_buckets": RateLimitTokenBucket.cleanup_stale(
                    days=7, batch_size=self._batch_cleanup_size
                ),
                "leaky_buckets": RateLimitLeakyBucket.cleanup_stale(
                    days=7, batch_size=self._batch_cleanup_size
                ),
            }

            self._last_cleanup = timezone.now()

            log_backend_operation(
                "cleanup",
                f"database backend cleanup: {deleted}",
            )

            return deleted

    def clear_all(self) -> None:
        """
        Clear all rate limiting data.

        This method is primarily for testing purposes.
        """
        from ..models import (
            RateLimitCounter,
            RateLimitEntry,
            RateLimitLeakyBucket,
            RateLimitTokenBucket,
        )

        with transaction.atomic():
            RateLimitCounter.objects.all().delete()
            RateLimitEntry.objects.all().delete()
            RateLimitTokenBucket.objects.all().delete()
            RateLimitLeakyBucket.objects.all().delete()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the database backend.

        Returns:
            Dictionary containing backend statistics
        """
        from ..models import (
            RateLimitCounter,
            RateLimitEntry,
            RateLimitLeakyBucket,
            RateLimitTokenBucket,
        )

        now = timezone.now()

        # Count active records
        active_counters = RateLimitCounter.objects.filter(window_end__gt=now).count()
        active_entries = RateLimitEntry.objects.filter(expires_at__gt=now).count()
        token_buckets = RateLimitTokenBucket.objects.count()
        leaky_buckets = RateLimitLeakyBucket.objects.count()

        return {
            "active_counters": active_counters,
            "active_entries": active_entries,
            "token_buckets": token_buckets,
            "leaky_buckets": leaky_buckets,
            "total_records": active_counters
            + active_entries
            + token_buckets
            + leaky_buckets,
            "algorithm": self._algorithm,
            "cleanup_interval": self._cleanup_interval,
            "last_cleanup": self._last_cleanup.isoformat(),
            "database_vendor": self._get_db_vendor(),
        }

    def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the database backend.

        Returns:
            Dictionary with health status information
        """
        start_time = timezone.now()

        try:
            # Simple query to test database connectivity
            from ..models import RateLimitCounter

            RateLimitCounter.objects.exists()

            response_time = (timezone.now() - start_time).total_seconds()

            return {
                "status": "healthy",
                "response_time": response_time,
                "database_vendor": self._get_db_vendor(),
                "algorithm": self._algorithm,
            }
        except DatabaseError as e:
            response_time = (timezone.now() - start_time).total_seconds()

            return {
                "status": "unhealthy",
                "response_time": response_time,
                "error": str(e),
                "database_vendor": self._get_db_vendor(),
            }
