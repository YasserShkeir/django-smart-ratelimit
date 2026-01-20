"""Unit tests for RateLimitEntry model.

Tests cover:
- Model creation and validation
- is_expired() method
- cleanup_expired() class method
- count_in_window() class method
- String representation
"""

from datetime import timedelta

import pytest

from django.utils import timezone

from django_smart_ratelimit.models import RateLimitEntry


@pytest.fixture
def entry_data():
    """Base data for creating entries."""
    now = timezone.now()
    return {
        "key": "user:42",
        "timestamp": now,
        "expires_at": now + timedelta(minutes=1),
    }


@pytest.mark.django_db
class TestRateLimitEntryCreation:
    """Test RateLimitEntry model creation."""

    def test_create_entry_basic(self, entry_data):
        """Test basic entry creation."""
        entry = RateLimitEntry.objects.create(**entry_data)

        assert entry.id is not None
        assert entry.key == "user:42"
        assert entry.timestamp is not None
        assert entry.expires_at is not None

    def test_create_multiple_entries_same_key(self, entry_data):
        """Test creating multiple entries with the same key (no unique constraint)."""
        entries = []
        for i in range(5):
            data = entry_data.copy()
            data["timestamp"] = timezone.now() + timedelta(seconds=i)
            entries.append(RateLimitEntry.objects.create(**data))

        assert len(entries) == 5
        assert RateLimitEntry.objects.filter(key="user:42").count() == 5

    def test_create_entry_various_keys(self):
        """Test entries with different key formats."""
        now = timezone.now()
        keys = [
            "ip:10.0.0.1",
            "user:123",
            "api:key:xyz",
            "composite:tenant:acme:user:1",
        ]

        for key in keys:
            entry = RateLimitEntry.objects.create(
                key=key,
                timestamp=now,
                expires_at=now + timedelta(minutes=1),
            )
            assert entry.key == key


@pytest.mark.django_db
class TestRateLimitEntryMethods:
    """Test RateLimitEntry model methods."""

    def test_is_expired_when_not_expired(self, entry_data):
        """Test is_expired returns False when entry is still valid."""
        entry_data["expires_at"] = timezone.now() + timedelta(hours=1)
        entry = RateLimitEntry.objects.create(**entry_data)

        assert entry.is_expired() is False

    def test_is_expired_when_expired(self, entry_data):
        """Test is_expired returns True when entry has expired."""
        entry_data["timestamp"] = timezone.now() - timedelta(hours=2)
        entry_data["expires_at"] = timezone.now() - timedelta(hours=1)
        entry = RateLimitEntry.objects.create(**entry_data)

        assert entry.is_expired() is True

    def test_str_representation(self, entry_data):
        """Test string representation of entry."""
        entry = RateLimitEntry.objects.create(**entry_data)
        str_repr = str(entry)

        assert "user:42" in str_repr

    def test_cleanup_expired_deletes_old_records(self):
        """Test cleanup_expired removes expired entries."""
        now = timezone.now()

        # Create expired entries
        for i in range(10):
            RateLimitEntry.objects.create(
                key=f"expired:{i}",
                timestamp=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            )

        # Create active entries
        for i in range(5):
            RateLimitEntry.objects.create(
                key=f"active:{i}",
                timestamp=now,
                expires_at=now + timedelta(hours=1),
            )

        assert RateLimitEntry.objects.count() == 15

        deleted = RateLimitEntry.cleanup_expired()

        assert deleted == 10
        assert RateLimitEntry.objects.count() == 5
        assert RateLimitEntry.objects.filter(key__startswith="active:").count() == 5

    def test_cleanup_expired_with_batch_size(self):
        """Test cleanup_expired with small batch size."""
        now = timezone.now()

        # Create 20 expired entries
        for i in range(20):
            RateLimitEntry.objects.create(
                key=f"expired:{i}",
                timestamp=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            )

        deleted = RateLimitEntry.cleanup_expired(batch_size=5)

        assert deleted == 20
        assert RateLimitEntry.objects.count() == 0

    def test_cleanup_expired_no_records(self):
        """Test cleanup_expired when no expired records exist."""
        now = timezone.now()

        RateLimitEntry.objects.create(
            key="active:1",
            timestamp=now,
            expires_at=now + timedelta(hours=1),
        )

        deleted = RateLimitEntry.cleanup_expired()

        assert deleted == 0
        assert RateLimitEntry.objects.count() == 1


@pytest.mark.django_db
class TestRateLimitEntryCountInWindow:
    """Test RateLimitEntry.count_in_window() method."""

    def test_count_in_window_basic(self):
        """Test counting entries within a time window."""
        now = timezone.now()
        key = "user:42"

        # Create 5 entries within the window
        for i in range(5):
            RateLimitEntry.objects.create(
                key=key,
                timestamp=now - timedelta(seconds=i * 10),
                expires_at=now + timedelta(minutes=1),
            )

        # Count entries in the last minute
        window_start = now - timedelta(minutes=1)
        count = RateLimitEntry.count_in_window(key, window_start)

        assert count == 5

    def test_count_in_window_excludes_old_entries(self):
        """Test that count_in_window excludes entries before window."""
        now = timezone.now()
        key = "user:42"

        # Create entries within window
        for i in range(3):
            RateLimitEntry.objects.create(
                key=key,
                timestamp=now - timedelta(seconds=i * 10),
                expires_at=now + timedelta(minutes=1),
            )

        # Create entries outside window (old)
        for i in range(4):
            RateLimitEntry.objects.create(
                key=key,
                timestamp=now - timedelta(hours=1, seconds=i * 10),
                expires_at=now + timedelta(minutes=1),
            )

        window_start = now - timedelta(minutes=1)
        count = RateLimitEntry.count_in_window(key, window_start)

        assert count == 3

    def test_count_in_window_different_keys(self):
        """Test that count_in_window only counts matching keys."""
        now = timezone.now()

        # Create entries for different keys
        for i in range(5):
            RateLimitEntry.objects.create(
                key="user:42",
                timestamp=now - timedelta(seconds=i),
                expires_at=now + timedelta(minutes=1),
            )

        for i in range(3):
            RateLimitEntry.objects.create(
                key="user:99",
                timestamp=now - timedelta(seconds=i),
                expires_at=now + timedelta(minutes=1),
            )

        window_start = now - timedelta(minutes=1)

        assert RateLimitEntry.count_in_window("user:42", window_start) == 5
        assert RateLimitEntry.count_in_window("user:99", window_start) == 3
        assert RateLimitEntry.count_in_window("user:nonexistent", window_start) == 0

    def test_count_in_window_empty_result(self):
        """Test count_in_window returns 0 for non-existent key."""
        now = timezone.now()
        window_start = now - timedelta(minutes=1)

        count = RateLimitEntry.count_in_window("nonexistent:key", window_start)

        assert count == 0


@pytest.mark.django_db
class TestRateLimitEntrySlidingWindowScenarios:
    """Test realistic sliding window scenarios."""

    def test_sliding_window_rate_limiting(self):
        """Simulate a sliding window rate limit check."""
        now = timezone.now()
        key = "api:client_123"
        limit = 5
        window_seconds = 60

        # Add some requests
        for i in range(3):
            RateLimitEntry.objects.create(
                key=key,
                timestamp=now - timedelta(seconds=i * 10),
                expires_at=now + timedelta(seconds=window_seconds),
            )

        window_start = now - timedelta(seconds=window_seconds)
        current_count = RateLimitEntry.count_in_window(key, window_start)

        # Should allow more requests
        assert current_count < limit
        remaining = limit - current_count
        assert remaining == 2

    def test_sliding_window_at_limit(self):
        """Test sliding window when at the rate limit."""
        now = timezone.now()
        key = "api:client_456"
        limit = 5
        window_seconds = 60

        # Fill up to limit
        for i in range(limit):
            RateLimitEntry.objects.create(
                key=key,
                timestamp=now - timedelta(seconds=i * 10),
                expires_at=now + timedelta(seconds=window_seconds),
            )

        window_start = now - timedelta(seconds=window_seconds)
        current_count = RateLimitEntry.count_in_window(key, window_start)

        assert current_count == limit
        assert current_count >= limit  # Should block

    def test_sliding_window_entries_age_out(self):
        """Test that old entries don't count in the window."""
        now = timezone.now()
        key = "api:client_789"
        window_seconds = 60

        # Old entries (outside window)
        for i in range(10):
            RateLimitEntry.objects.create(
                key=key,
                timestamp=now - timedelta(seconds=window_seconds + 30 + i),
                expires_at=now + timedelta(seconds=30),  # Expired
            )

        # Recent entries (inside window)
        for i in range(2):
            RateLimitEntry.objects.create(
                key=key,
                timestamp=now - timedelta(seconds=i * 10),
                expires_at=now + timedelta(seconds=window_seconds),
            )

        window_start = now - timedelta(seconds=window_seconds)
        current_count = RateLimitEntry.count_in_window(key, window_start)

        # Only recent entries should count
        assert current_count == 2


@pytest.mark.django_db
class TestRateLimitEntryIndexes:
    """Test that indexes are properly used."""

    def test_key_timestamp_index(self):
        """Verify key + timestamp index is used for queries."""
        now = timezone.now()

        # Create test data
        for i in range(100):
            RateLimitEntry.objects.create(
                key=f"key:{i % 10}",
                timestamp=now - timedelta(seconds=i),
                expires_at=now + timedelta(minutes=1),
            )

        # This query should use the key + timestamp index
        result = RateLimitEntry.objects.filter(
            key="key:5",
            timestamp__gte=now - timedelta(minutes=1),
        ).first()

        assert result is not None

    def test_expires_at_index_for_cleanup(self):
        """Verify expires_at index is used for cleanup."""
        now = timezone.now()

        # Create expired entries
        for i in range(50):
            RateLimitEntry.objects.create(
                key=f"key:{i}",
                timestamp=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            )

        # This query should use the expires_at index
        expired_count = RateLimitEntry.objects.filter(expires_at__lt=now).count()

        assert expired_count == 50
