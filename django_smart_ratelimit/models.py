"""Django models for database-backed rate limiting (v2.0).

This module provides Django models for storing rate limit state in SQL databases.
These models support fixed window, sliding window, token bucket, and leaky bucket
algorithms.

Supported databases:
- PostgreSQL (recommended for production)
- MySQL 8.0+
- SQLite 3.35+ (for development/testing)
"""

import re
from datetime import datetime, timedelta
from typing import Any

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
    count: "models.PositiveBigIntegerField[int, int]" = models.PositiveBigIntegerField(
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
    bucket_size: "models.PositiveBigIntegerField[int, int]" = (
        models.PositiveBigIntegerField(
            help_text="Maximum capacity of the bucket",
        )
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
            Seconds until tokens are available (0 if already available,
            ``float("inf")`` if the bucket never refills)
        """
        current_tokens = self.calculate_current_tokens()
        if current_tokens >= tokens_needed:
            return 0.0
        if self.refill_rate <= 0:
            return float("inf")
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
    bucket_capacity: "models.PositiveBigIntegerField[int, int]" = (
        models.PositiveBigIntegerField(
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


class RateLimitRule(models.Model):
    """Dynamic rate limit configuration stored in the database.

    Rules let operators define and change rate limits at runtime (via the Django
    admin or the ORM) without a redeploy. The :class:`RuleEngine` matches a
    request against the active rules by ``path_pattern`` / ``method`` and applies
    the highest-``priority`` match.
    """

    ALGORITHM_CHOICES = [
        ("fixed_window", "Fixed Window"),
        ("sliding_window", "Sliding Window"),
        ("token_bucket", "Token Bucket"),
        ("leaky_bucket", "Leaky Bucket"),
    ]

    name: "models.CharField[str, str]" = models.CharField(max_length=100, unique=True)
    description: "models.TextField[str, str]" = models.TextField(blank=True)

    # Target configuration
    path_pattern: "models.CharField[str, str]" = models.CharField(
        max_length=255,
        help_text="URL pattern (regex) this rule applies to, e.g. '^/api/'.",
    )
    method: "models.CharField[str, str]" = models.CharField(
        max_length=50,
        default="ALL",
        help_text="HTTP methods (comma-separated, e.g. 'GET,POST') or 'ALL'.",
    )

    # Rate limit configuration
    rate: "models.CharField[str, str]" = models.CharField(
        max_length=50,
        help_text="Rate limit string, e.g. '100/m', '1000/h', '10/30s'.",
    )
    key: "models.CharField[str, str]" = models.CharField(
        max_length=100,
        default="ip",
        help_text="Key function (ip, user, header:X-API-Key, ...).",
    )
    algorithm: "models.CharField[str, str]" = models.CharField(
        max_length=50,
        default="fixed_window",
        choices=ALGORITHM_CHOICES,
    )

    # Behavior
    block: "models.BooleanField[bool, bool]" = models.BooleanField(
        default=True,
        help_text="Block requests when the limit is exceeded.",
    )

    # Metadata
    is_active: "models.BooleanField[bool, bool]" = models.BooleanField(default=True)
    priority: "models.IntegerField[int, int]" = models.IntegerField(
        default=0,
        help_text="Higher-priority rules are evaluated first.",
    )
    created_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        auto_now_add=True
    )
    updated_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        """Order by priority (desc) then name; index active rules."""

        ordering = ["-priority", "name"]
        verbose_name = "rate limit rule"
        verbose_name_plural = "rate limit rules"
        indexes = [
            models.Index(
                fields=["is_active", "-priority"], name="ratelimit_rule_active"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.rate} {self.path_pattern})"

    def clean(self) -> None:
        """Validate the rate string and the path regex at save time."""
        from django.core.exceptions import ImproperlyConfigured, ValidationError

        from .backends.utils import parse_rate

        try:
            parse_rate(self.rate)
        except ImproperlyConfigured as exc:
            raise ValidationError({"rate": str(exc)})

        try:
            re.compile(self.path_pattern)
        except re.error as exc:
            raise ValidationError(
                {"path_pattern": f"Invalid regular expression: {exc}"}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Full-clean before saving so ORM writes are validated too."""
        self.full_clean()
        super().save(*args, **kwargs)

    def methods(self) -> list:
        """Return the parsed list of HTTP methods, or ['ALL']."""
        if self.method.strip().upper() == "ALL":
            return ["ALL"]
        return [m.strip().upper() for m in self.method.split(",") if m.strip()]


class UserTier(models.Model):
    """A named rate-limit tier (e.g. free / premium) for users.

    A tier either scales the base rate by ``rate_multiplier`` or overrides it
    outright per scope via ``explicit_limits`` (which wins when a key is present).
    """

    name: "models.CharField[str, str]" = models.CharField(max_length=100, unique=True)
    description: "models.TextField[str, str]" = models.TextField(blank=True)
    rate_multiplier: "models.FloatField[float, float]" = models.FloatField(
        default=1.0,
        help_text="Scale the base limit (1.0 = normal, 2.0 = double).",
    )
    explicit_limits: "models.JSONField[dict, dict]" = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-scope overrides, e.g. {'api': '1000/h', 'upload': '100/d'}.",
    )
    priority: "models.IntegerField[int, int]" = models.IntegerField(default=0)

    class Meta:
        """Higher-priority tiers win when a user resolves to several."""

        ordering = ["-priority"]

    def __str__(self) -> str:
        return self.name


class UserTierAssignment(models.Model):
    """Assigns a user to a :class:`UserTier` (optionally with an expiry)."""

    from django.conf import settings as _dj_settings

    user: Any = models.OneToOneField(
        _dj_settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ratelimit_tier",
    )
    tier: Any = models.ForeignKey("UserTier", on_delete=models.CASCADE)
    expires_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        null=True, blank=True
    )

    def __str__(self) -> str:
        return f"{self.user} -> {self.tier}"

    def is_expired(self) -> bool:
        """True if the assignment has an expiry in the past."""
        return self.expires_at is not None and self.expires_at < timezone.now()


class GroupRateLimit(models.Model):
    """Maps a Django ``auth.Group`` to a tier (and/or custom per-scope limits)."""

    group: Any = models.OneToOneField(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="ratelimit_config",
    )
    tier: Any = models.ForeignKey(
        "UserTier", on_delete=models.SET_NULL, null=True, blank=True
    )
    custom_limits: "models.JSONField[dict, dict]" = models.JSONField(
        default=dict, blank=True
    )

    def __str__(self) -> str:
        return f"group:{self.group} -> {self.tier}"


class UserRateLimitOverride(models.Model):
    """A time-bounded per-user rate override (highest precedence)."""

    from django.conf import settings as _dj_settings

    user: Any = models.ForeignKey(
        _dj_settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ratelimit_overrides",
    )
    rule_name: "models.CharField[str, str]" = models.CharField(
        max_length=100,
        blank=True,
        help_text="Scope/rule this override applies to, or blank for all.",
    )
    rate: "models.CharField[str, str]" = models.CharField(max_length=50)
    reason: "models.TextField[str, str]" = models.TextField(blank=True)
    created_by: Any = models.ForeignKey(
        _dj_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    starts_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        default=timezone.now
    )
    expires_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField()

    class Meta:
        """Most recent override first."""

        ordering = ["-starts_at"]

    def __str__(self) -> str:
        return f"{self.user} {self.rate} (until {self.expires_at:%Y-%m-%d})"

    def is_active(self, when: Any = None) -> bool:
        """True if ``when`` (default now) is within [starts_at, expires_at)."""
        when = when or timezone.now()
        return self.starts_at <= when < self.expires_at


class APIKey(models.Model):
    """An API key, optionally tied to a user and a tier, for keyed limiting."""

    from django.conf import settings as _dj_settings

    key: "models.CharField[str, str]" = models.CharField(
        max_length=64, unique=True, db_index=True
    )
    name: "models.CharField[str, str]" = models.CharField(max_length=100)
    user: Any = models.ForeignKey(
        _dj_settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    tier: Any = models.ForeignKey(
        "UserTier", on_delete=models.SET_NULL, null=True, blank=True
    )
    is_active: "models.BooleanField[bool, bool]" = models.BooleanField(default=True)
    created_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        auto_now_add=True
    )
    last_used_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        null=True, blank=True
    )

    def __str__(self) -> str:
        return f"{self.name} ({self.key[:8]}...)"


class RateLimitEvent(models.Model):
    """A recorded rate-limit decision, for historical reporting and analytics.

    Recorded by the middleware when ``RATELIMIT_LOG_EVENTS`` is enabled. One row
    per request is written, so enable it deliberately and prune old rows (the
    ``ratelimit_cleanup`` command and TTL-style age cutoff handle this).
    """

    timestamp: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        auto_now_add=True, db_index=True
    )
    key: "models.CharField[str, str]" = models.CharField(max_length=255, db_index=True)
    rule_name: "models.CharField[str, str]" = models.CharField(
        max_length=100, blank=True
    )
    path: "models.CharField[str, str]" = models.CharField(max_length=500)
    method: "models.CharField[str, str]" = models.CharField(max_length=10)

    # Outcome
    allowed: "models.BooleanField[bool, bool]" = models.BooleanField()
    count: "models.PositiveBigIntegerField[int, int]" = models.PositiveBigIntegerField()
    limit: "models.PositiveBigIntegerField[int, int]" = models.PositiveBigIntegerField()

    # Optional context
    ip_address: Any = models.GenericIPAddressField(null=True, blank=True)
    user_id: "models.PositiveBigIntegerField[int, int]" = (
        models.PositiveBigIntegerField(null=True, blank=True)
    )

    class Meta:
        """Index for time-range, per-key, and allowed/blocked reporting."""

        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp"], name="ratelimit_event_ts"),
            models.Index(fields=["key", "timestamp"], name="ratelimit_event_key_ts"),
            models.Index(
                fields=["allowed", "timestamp"], name="ratelimit_event_allowed_ts"
            ),
        ]

    def __str__(self) -> str:
        verb = "allowed" if self.allowed else "blocked"
        return f"{self.key} {verb} @ {self.timestamp:%Y-%m-%d %H:%M}"

    @classmethod
    def cleanup_old(cls, older_than_days: int = 30, batch_size: int = 1000) -> int:
        """Delete events older than ``older_than_days``; return the count."""
        cutoff = timezone.now() - timedelta(days=older_than_days)
        total = 0
        while True:
            ids = list(
                cls.objects.filter(timestamp__lt=cutoff).values_list("id", flat=True)[
                    :batch_size
                ]
            )
            if not ids:
                break
            deleted, _ = cls.objects.filter(id__in=ids).delete()
            total += deleted
            if deleted < batch_size:
                break
        return total


class TenantQuota(models.Model):
    """Per-tenant rate quota for multi-tenant (SaaS) rate limiting (Phase 5.5)."""

    tenant_id: "models.CharField[str, str]" = models.CharField(
        max_length=100, unique=True, db_index=True
    )
    rate: "models.CharField[str, str]" = models.CharField(
        max_length=50, help_text="Rate string, e.g. '1000/h'."
    )
    is_active: "models.BooleanField[bool, bool]" = models.BooleanField(default=True)
    created_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        auto_now_add=True
    )
    updated_at: "models.DateTimeField[datetime, datetime]" = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        """Quotas ordered by tenant for stable admin listing."""

        ordering = ["tenant_id"]

    def __str__(self) -> str:
        return f"{self.tenant_id}: {self.rate}"

    def clean(self) -> None:
        """Validate the rate string."""
        from django.core.exceptions import ImproperlyConfigured, ValidationError

        from .backends.utils import parse_rate

        try:
            parse_rate(self.rate)
        except ImproperlyConfigured as exc:
            raise ValidationError({"rate": str(exc)})

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate before saving."""
        self.full_clean()
        super().save(*args, **kwargs)
