"""Database models for Django Smart Ratelimit."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class RateLimitEntry(models.Model):
    """
    Model to store rate limit entries in the database.

    This model stores individual rate limit entries with their keys,
    timestamps, and expiration times.
    """

    key: models.CharField = models.CharField(
        max_length=255,
        db_index=True,
        help_text="The rate limit key (e.g., 'user:123', 'ip:192.168.1.1')",
    )

    timestamp: models.DateTimeField = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="When this rate limit entry was created",
    )

    expires_at: models.DateTimeField = models.DateTimeField(
        db_index=True, help_text="When this rate limit entry expires"
    )

    algorithm: models.CharField = models.CharField(
        max_length=50,
        default="sliding_window",
        choices=[
            ("sliding_window", "Sliding Window"),
            ("fixed_window", "Fixed Window"),
        ],
        help_text="The algorithm used for this rate limit",
    )

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata for RateLimitEntry."""

        db_table = "django_smart_ratelimit_entry"
        verbose_name = "Rate Limit Entry"
        verbose_name_plural = "Rate Limit Entries"
        indexes = [
            models.Index(fields=["key", "expires_at"]),
            models.Index(fields=["expires_at"]),
            models.Index(fields=["key", "algorithm"]),
        ]
        ordering = ["-timestamp"]

    def clean(self) -> None:
        """Validate the model."""
        if self.expires_at and self.expires_at <= timezone.now():
            raise ValidationError("Expiration time must be in the future")

    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        return timezone.now() > self.expires_at

    def __str__(self) -> str:
        """Return string representation of the rate limit entry."""
        return f"RateLimit({self.key}, {self.timestamp}, expires: {self.expires_at})"


class RateLimitCounter(models.Model):
    """
    Model to store rate limit counters for fixed window algorithm.

    This model stores counters for rate limiting using the fixed window
    algorithm, where we track the count within a specific time window.
    """

    key: models.CharField = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="The rate limit key (e.g., 'user:123', 'ip:192.168.1.1')",
    )

    count: models.PositiveIntegerField = models.PositiveIntegerField(
        default=0, help_text="Current count for this rate limit key"
    )

    window_start: models.DateTimeField = models.DateTimeField(
        help_text="Start of the current rate limit window"
    )

    window_end: models.DateTimeField = models.DateTimeField(
        help_text="End of the current rate limit window"
    )

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata for RateLimitCounter."""

        db_table = "django_smart_ratelimit_counter"
        verbose_name = "Rate Limit Counter"
        verbose_name_plural = "Rate Limit Counters"
        indexes = [
            models.Index(fields=["key", "window_end"]),
            models.Index(fields=["window_end"]),
        ]

    def is_expired(self) -> bool:
        """Check if this counter window has expired."""
        return timezone.now() > self.window_end

    def reset_if_expired(self) -> None:
        """Reset counter if the window has expired."""
        if self.is_expired():
            self.count = 0
            now = timezone.now()
            window_duration = self.window_end - self.window_start
            self.window_start = now
            self.window_end = now + window_duration
            self.save()

    def __str__(self) -> str:
        """Return string representation of the rate limit counter."""
        return (
            f"Counter({self.key}, {self.count}, {self.window_start}-{self.window_end})"
        )


class RateLimitConfig(models.Model):
    """
    Model to store rate limit configurations.

    This model allows storing custom rate limit configurations
    that can override default settings.
    """

    key_pattern: models.CharField = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Pattern to match rate limit keys (supports wildcards)",
    )

    rate_limit: models.CharField = models.CharField(
        max_length=50, help_text="Rate limit (e.g., '100/h', '10/m')"
    )

    algorithm: models.CharField = models.CharField(
        max_length=50,
        default="sliding_window",
        choices=[
            ("sliding_window", "Sliding Window"),
            ("fixed_window", "Fixed Window"),
        ],
        help_text="Algorithm to use for this rate limit",
    )

    is_active: models.BooleanField = models.BooleanField(
        default=True, help_text="Whether this configuration is active"
    )

    description: models.TextField = models.TextField(
        blank=True, help_text="Description of this rate limit configuration"
    )

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata for RateLimitConfig."""

        db_table = "django_smart_ratelimit_config"
        verbose_name = "Rate Limit Configuration"
        verbose_name_plural = "Rate Limit Configurations"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        """Return string representation of the rate limit configuration."""
        return f"Config({self.key_pattern}, {self.rate_limit})"
