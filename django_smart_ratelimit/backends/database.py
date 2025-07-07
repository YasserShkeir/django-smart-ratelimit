"""Database backend for Django Smart Ratelimit."""

import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any, Dict, Optional, Tuple

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ..models import RateLimitCounter, RateLimitEntry
from .base import BaseBackend


class DatabaseBackend(BaseBackend):
    """
    Database backend that stores rate limit data in Django models.

    This backend uses Django's ORM to store rate limit entries and counters
    in the database, making it suitable for deployments without Redis.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the database backend with optional configuration."""
        # Don't call super().__init__ since it tries to access Redis config
        self.cleanup_threshold = kwargs.get("cleanup_threshold", 1000)

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

    def _incr_sliding_window(self, key: str, window_seconds: int) -> int:
        """
        Increment counter for sliding window algorithm.

        Args:
            key: The rate limit key
            window_seconds: The window size in seconds

        Returns:
            Current count in the window
        """
        now = timezone.now()
        expires_at = now + timedelta(seconds=window_seconds)

        with transaction.atomic():
            # Remove expired entries
            RateLimitEntry.objects.filter(key=key, expires_at__lt=now).delete()

            # Add new entry
            RateLimitEntry.objects.create(
                key=key,
                timestamp=now,
                expires_at=expires_at,
                algorithm="sliding_window",
            )

            # Count current entries in the window
            count = RateLimitEntry.objects.filter(
                key=key, timestamp__gte=now - timedelta(seconds=window_seconds)
            ).count()

            return count

    def _incr_fixed_window(self, key: str, window_seconds: int) -> int:
        """
        Increment counter for fixed window algorithm using atomic database operations.

        Args:
            key: The rate limit key
            window_seconds: The window size in seconds

        Returns:
            Current count in the window
        """
        window_start, window_end = self._get_window_times(window_seconds)

        with transaction.atomic():
            # Try to get existing counter for current window
            counter, created = RateLimitCounter.objects.get_or_create(
                key=key,
                defaults={
                    "count": 1,  # Start with 1 for new counter
                    "window_start": window_start,
                    "window_end": window_end,
                },
            )

            if created:
                # New counter created with count=1
                return 1

            # Counter exists - check if it's from the current window
            if counter.window_start != window_start or counter.window_end != window_end:
                # Reset counter for new window using atomic update
                counter.count = 1
                counter.window_start = window_start
                counter.window_end = window_end
                counter.save()
                return 1
            else:
                # Increment existing counter atomically using F() expression
                RateLimitCounter.objects.filter(
                    key=key, window_start=window_start, window_end=window_end
                ).update(count=F("count") + 1)

                # Refresh from database to get the updated count
                counter.refresh_from_db()
                return counter.count

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
        now = timezone.now()
        window_start = now - timedelta(seconds=window_seconds)

        # Clean up expired entries
        RateLimitEntry.objects.filter(key=key, expires_at__lt=now).delete()

        # Count current entries in the window
        count = RateLimitEntry.objects.filter(
            key=key, timestamp__gte=window_start
        ).count()

        return count

    def _get_count_fixed_window(self, key: str, window_seconds: int) -> int:
        """Get count for fixed window algorithm."""
        window_start, window_end = self._get_window_times(window_seconds)

        try:
            counter = RateLimitCounter.objects.get(key=key)

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
        # Reset both sliding window entries and fixed window counters
        RateLimitEntry.objects.filter(key=key).delete()
        RateLimitCounter.objects.filter(key=key).delete()

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
        self, key: str, window_seconds: int, algorithm: str = "sliding_window"
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
        Clean up expired rate limit entries.

        Returns:
            Number of entries cleaned up
        """
        now = timezone.now()
        total_cleaned = 0

        try:
            # Clean up expired sliding window entries
            sliding_count = RateLimitEntry.objects.filter(expires_at__lt=now).count()
            RateLimitEntry.objects.filter(expires_at__lt=now).delete()
            total_cleaned += sliding_count
        except Exception as e:
            # Log error but continue with counter cleanup
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to cleanup sliding window entries: {e}")

        try:
            # Clean up expired fixed window counters
            fixed_count = RateLimitCounter.objects.filter(window_end__lt=now).count()
            RateLimitCounter.objects.filter(window_end__lt=now).delete()
            total_cleaned += fixed_count
        except Exception as e:
            # Log error but don't fail completely
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to cleanup fixed window counters: {e}")

        return total_cleaned

    def _cleanup_expired_entries(self, force: bool = False) -> int:
        """
        Clean up expired rate limit entries.

        Args:
            force: Force cleanup regardless of threshold

        Returns:
            Number of entries cleaned up
        """
        if not force:
            # Check if we need to cleanup based on threshold
            total_entries = (
                RateLimitEntry.objects.count() + RateLimitCounter.objects.count()
            )
            if total_entries < self.cleanup_threshold:
                return 0

        return self.cleanup_expired()

    def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the database backend.

        Returns:
            Dictionary with health check results
        """
        details = {}

        try:
            # Test database connectivity
            RateLimitEntry.objects.count()
            details["database_connection"] = "OK"
        except Exception as e:
            details["database_connection"] = f"Failed: {str(e)}"

        try:
            # Test table access
            RateLimitCounter.objects.count()
            details["table_access"] = "OK"
        except Exception as e:
            details["table_access"] = f"Failed: {str(e)}"

        try:
            # Test write operations
            test_key = "health_check_test"
            RateLimitEntry.objects.filter(key=test_key).delete()
            details["write_operations"] = "OK"
        except Exception as e:
            details["write_operations"] = f"Failed: {str(e)}"

        healthy = all("Failed" not in str(value) for value in details.values())

        return {
            "healthy": healthy,
            "backend": "database",
            "message": (
                "Database health check completed"
                if healthy
                else "Database health check failed"
            ),
            "details": details,
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
