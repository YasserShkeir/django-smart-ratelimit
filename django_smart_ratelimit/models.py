"""Django models for database-backed rate limiting (v2.0).

This module provides Django models for storing rate limit state in SQL databases.
These models support fixed window, sliding window, token bucket, and leaky bucket
algorithms.

Supported databases:
- PostgreSQL (recommended for production)
- MySQL 8.0+
- SQLite 3.35+ (for development/testing)
"""

from datetime import datetime

from django.db import models
from django.utils import timezone


class RateLimitCounter(models.Model):
    """Stores rate limit counters for fixed window algorithm.

    This model tracks the count of requests within a specific time window.
    Each record represents one window for a given key.

    Attributes:
        key: The rate limit key (e.g., "ip:192.168.1.1" or "user:42")
        count: Number of requests in this window
        window_start: Start of the time window
        window_end: End of the time window (used for cleanup)
        created_at: When this counter was created
        updated_at: When this counter was last updated

    Example:
        >>> counter = RateLimitCounter.objects.create(
        ...     key="ip:192.168.1.1",
        ...     count=1,
        ...     window_start=timezone.now(),
        ...     window_end=timezone.now() + timedelta(minutes=1),
        ... )
    """

    key: "models.CharField[str, str]" = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Rate limit key (e.g., 'ip:192.168.1.1', 'user:42')",
    )
    count: "models.PositiveIntegerField[int, int]" = models.PositiveIntegerField(
        default=0,
        help_text="Number of requests in this window",
    )
    window_start: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        help_text="Start timestamp of the rate limit window",
    )
    window_end: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        db_index=True,
        help_text="End timestamp of the rate limit window (for cleanup queries)",
    )
    created_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        auto_now_add=True,
        help_text="When this counter was first created",
    )
    updated_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        auto_now=True,
        help_text="When this counter was last updated",
    )

    class Meta:
        """Meta options for RateLimitCounter."""

        db_table = "ratelimit_counter"
        verbose_name = "Rate Limit Counter"
        verbose_name_plural = "Rate Limit Counters"
        unique_together = [["key", "window_start"]]
        indexes = [
            models.Index(
                fields=["key", "window_start"], name="ratelimit_counter_key_win"
            ),
            models.Index(fields=["window_end"], name="ratelimit_counter_win_end"),
        ]

    def __str__(self) -> str:
        return f"{self.key}: {self.count} ({self.window_start} - {self.window_end})"

    def is_expired(self) -> bool:
        """Check if this counter's window has expired."""
        return timezone.now() > self.window_end

    @classmethod
    def cleanup_expired(cls, batch_size: int = 1000) -> int:
        """Delete expired counters in batches.

        Args:
            batch_size: Maximum number of records to delete per batch

        Returns:
            Total number of deleted records
        """
        total_deleted = 0
        while True:
            # Get IDs of expired records
            expired_ids = list(
                cls.objects.filter(window_end__lt=timezone.now()).values_list(
                    "id", flat=True
                )[:batch_size]
            )
            if not expired_ids:
                break
            deleted, _ = cls.objects.filter(id__in=expired_ids).delete()
            total_deleted += deleted
            if deleted < batch_size:
                break
        return total_deleted


class RateLimitEntry(models.Model):
    """Stores individual request timestamps for sliding window algorithm.

    This model tracks each request timestamp, allowing precise sliding
    window rate limiting. Records are automatically cleaned up after expiration.

    Attributes:
        key: The rate limit key
        timestamp: When the request occurred
        expires_at: When this entry should be cleaned up

    Note:
        For high-throughput applications, consider using Redis backend
        instead, as sliding window creates many database records.

    Example:
        >>> entry = RateLimitEntry.objects.create(
        ...     key="user:42",
        ...     timestamp=timezone.now(),
        ...     expires_at=timezone.now() + timedelta(minutes=1),
        ... )
    """

    key: "models.CharField[str, str]" = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Rate limit key",
    )
    timestamp: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        db_index=True,
        help_text="Timestamp of the request",
    )
    expires_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        db_index=True,
        help_text="When this entry should be cleaned up",
    )

    class Meta:
        """Meta options for RateLimitEntry."""

        db_table = "ratelimit_entry"
        verbose_name = "Rate Limit Entry"
        verbose_name_plural = "Rate Limit Entries"
        indexes = [
            models.Index(fields=["key", "timestamp"], name="ratelimit_entry_key_ts"),
            models.Index(fields=["expires_at"], name="ratelimit_entry_expires"),
        ]

    def __str__(self) -> str:
        return f"{self.key} @ {self.timestamp}"

    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        return timezone.now() > self.expires_at

    @classmethod
    def cleanup_expired(cls, batch_size: int = 1000) -> int:
        """Delete expired entries in batches.

        Args:
            batch_size: Maximum number of records to delete per batch

        Returns:
            Total number of deleted records
        """
        total_deleted = 0
        while True:
            expired_ids = list(
                cls.objects.filter(expires_at__lt=timezone.now()).values_list(
                    "id", flat=True
                )[:batch_size]
            )
            if not expired_ids:
                break
            deleted, _ = cls.objects.filter(id__in=expired_ids).delete()
            total_deleted += deleted
            if deleted < batch_size:
                break
        return total_deleted

    @classmethod
    def count_in_window(cls, key: str, window_start: datetime) -> int:
        """Count entries for a key within a time window.

        Args:
            key: The rate limit key
            window_start: Start of the sliding window

        Returns:
            Number of entries in the window
        """
        return cls.objects.filter(
            key=key,
            timestamp__gte=window_start,
        ).count()


class RateLimitTokenBucket(models.Model):
    """Stores token bucket state for token bucket algorithm.

    This model maintains the state of a token bucket, including current
    tokens and the last update time for calculating refills.

    Attributes:
        key: The rate limit key (unique)
        tokens: Current number of tokens in the bucket
        last_update: When the bucket was last updated
        bucket_size: Maximum capacity of the bucket
        refill_rate: Tokens added per second

    Example:
        >>> bucket = RateLimitTokenBucket.objects.create(
        ...     key="api:client_123",
        ...     tokens=100.0,
        ...     last_update=timezone.now(),
        ...     bucket_size=100,
        ...     refill_rate=10.0,  # 10 tokens per second
        ... )
    """

    key: "models.CharField[str, str]" = models.CharField(
        max_length=255,
        unique=True,
        help_text="Rate limit key (unique per bucket)",
    )
    tokens: "models.FloatField[float, float]" = models.FloatField(
        help_text="Current number of tokens in the bucket",
    )
    last_update: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        help_text="When the bucket was last updated",
    )
    bucket_size: "models.PositiveIntegerField[int, int]" = models.PositiveIntegerField(
        help_text="Maximum capacity of the bucket",
    )
    refill_rate: "models.FloatField[float, float]" = models.FloatField(
        help_text="Tokens added per second",
    )
    created_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        auto_now_add=True,
        help_text="When this bucket was created",
    )

    class Meta:
        """Meta options for RateLimitTokenBucket."""

        db_table = "ratelimit_token_bucket"
        verbose_name = "Rate Limit Token Bucket"
        verbose_name_plural = "Rate Limit Token Buckets"
        indexes = [
            models.Index(fields=["key"], name="ratelimit_bucket_key"),
        ]

    def __str__(self) -> str:
        return f"{self.key}: {self.tokens:.1f}/{self.bucket_size} tokens"

    def calculate_current_tokens(self) -> float:
        """Calculate current tokens based on time elapsed since last update.

        Returns:
            Current token count (capped at bucket_size)
        """
        now = timezone.now()
        elapsed_seconds = (now - self.last_update).total_seconds()
        refilled = self.tokens + (elapsed_seconds * self.refill_rate)
        return min(refilled, self.bucket_size)

    def consume(self, tokens_requested: int = 1) -> bool:
        """Attempt to consume tokens from the bucket.

        This method calculates the current tokens, attempts to consume
        the requested amount, and saves the updated state.

        Args:
            tokens_requested: Number of tokens to consume

        Returns:
            True if tokens were consumed, False if insufficient tokens

        Note:
            This method saves the model. For atomic operations in
            concurrent environments, use the DatabaseBackend methods.
        """
        current_tokens = self.calculate_current_tokens()
        if current_tokens >= tokens_requested:
            self.tokens = current_tokens - tokens_requested
            self.last_update = timezone.now()
            self.save(update_fields=["tokens", "last_update"])
            return True
        return False

    def time_until_tokens(self, tokens_needed: int) -> float:
        """Calculate time until specified tokens are available.

        Args:
            tokens_needed: Number of tokens needed

        Returns:
            Seconds until tokens are available (0 if already available)
        """
        current_tokens = self.calculate_current_tokens()
        if current_tokens >= tokens_needed:
            return 0.0
        tokens_deficit = tokens_needed - current_tokens
        return tokens_deficit / self.refill_rate

    @classmethod
    def cleanup_stale(cls, days: int = 7, batch_size: int = 1000) -> int:
        """Delete token buckets that haven't been updated recently.

        Args:
            days: Delete buckets not updated in this many days
            batch_size: Maximum records to delete per batch

        Returns:
            Total number of deleted records
        """
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=days)
        total_deleted = 0
        while True:
            stale_ids = list(
                cls.objects.filter(last_update__lt=cutoff).values_list("id", flat=True)[
                    :batch_size
                ]
            )
            if not stale_ids:
                break
            deleted, _ = cls.objects.filter(id__in=stale_ids).delete()
            total_deleted += deleted
            if deleted < batch_size:
                break
        return total_deleted


class RateLimitLeakyBucket(models.Model):
    """Stores leaky bucket state for leaky bucket algorithm.

    The leaky bucket algorithm models requests filling a bucket that
    "leaks" at a constant rate. When the bucket is full, requests
    are rejected. This provides smooth, consistent rate limiting.

    Attributes:
        key: The rate limit key (unique)
        level: Current fill level of the bucket
        last_leak: When the bucket was last updated (for calculating leaked amount)
        bucket_capacity: Maximum capacity of the bucket
        leak_rate: Rate at which the bucket leaks (requests per second)

    Example:
        >>> bucket = RateLimitLeakyBucket.objects.create(
        ...     key="api:client_123",
        ...     level=5.0,
        ...     last_leak=timezone.now(),
        ...     bucket_capacity=100,
        ...     leak_rate=10.0,  # 10 requests leak per second
        ... )
    """

    key: "models.CharField[str, str]" = models.CharField(
        max_length=255,
        unique=True,
        help_text="Rate limit key (unique per bucket)",
    )
    level: "models.FloatField[float, float]" = models.FloatField(
        default=0,
        help_text="Current fill level of the bucket",
    )
    last_leak: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        help_text="When the bucket was last updated",
    )
    bucket_capacity: "models.PositiveIntegerField[int, int]" = (
        models.PositiveIntegerField(
            help_text="Maximum capacity of the bucket",
        )
    )
    leak_rate: "models.FloatField[float, float]" = models.FloatField(
        help_text="Rate at which the bucket leaks (requests per second)",
    )
    created_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        auto_now_add=True,
        help_text="When this bucket was created",
    )

    class Meta:
        """Meta options for RateLimitLeakyBucket."""

        db_table = "ratelimit_leaky_bucket"
        verbose_name = "Rate Limit Leaky Bucket"
        verbose_name_plural = "Rate Limit Leaky Buckets"
        indexes = [
            models.Index(fields=["key"], name="ratelimit_leaky_key"),
        ]

    def __str__(self) -> str:
        return f"{self.key}: {self.level:.1f}/{self.bucket_capacity} level"

    def calculate_current_level(self) -> float:
        """Calculate current bucket level after leaking.

        Returns:
            Current level (minimum 0)
        """
        now = timezone.now()
        elapsed_seconds = (now - self.last_leak).total_seconds()
        leaked_amount = elapsed_seconds * self.leak_rate
        return max(0, self.level - leaked_amount)

    def add_request(self, request_cost: int = 1) -> bool:
        """Attempt to add a request to the bucket.

        This method calculates the current level after leaking,
        checks if there's space for the request, and updates the state.

        Args:
            request_cost: How much this request fills the bucket

        Returns:
            True if request was accepted, False if bucket would overflow

        Note:
            This method saves the model. For atomic operations in
            concurrent environments, use the DatabaseBackend methods.
        """
        current_level = self.calculate_current_level()
        new_level = current_level + request_cost

        if new_level <= self.bucket_capacity:
            self.level = new_level
            self.last_leak = timezone.now()
            self.save(update_fields=["level", "last_leak"])
            return True
        return False

    def space_remaining(self) -> float:
        """Calculate remaining space in the bucket.

        Returns:
            Space remaining in the bucket
        """
        current_level = self.calculate_current_level()
        return max(0, self.bucket_capacity - current_level)

    def time_until_space(self, space_needed: int = 1) -> float:
        """Calculate time until enough space is available.

        Args:
            space_needed: Space needed in the bucket

        Returns:
            Seconds until space is available (0 if already available)
        """
        current_level = self.calculate_current_level()
        available_space = self.bucket_capacity - current_level

        if available_space >= space_needed:
            return 0.0

        overflow = space_needed - available_space
        return overflow / self.leak_rate if self.leak_rate > 0 else float("inf")

    @classmethod
    def cleanup_stale(cls, days: int = 7, batch_size: int = 1000) -> int:
        """Delete leaky buckets that haven't been updated recently.

        Args:
            days: Delete buckets not updated in this many days
            batch_size: Maximum records to delete per batch

        Returns:
            Total number of deleted records
        """
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=days)
        total_deleted = 0
        while True:
            stale_ids = list(
                cls.objects.filter(last_leak__lt=cutoff).values_list("id", flat=True)[
                    :batch_size
                ]
            )
            if not stale_ids:
                break
            deleted, _ = cls.objects.filter(id__in=stale_ids).delete()
            total_deleted += deleted
            if deleted < batch_size:
                break
        return total_deleted
