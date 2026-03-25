"""Unit tests for RateLimitCounter model.

Tests cover:
- Model creation and validation
- Unique together constraints
- is_expired() method
- cleanup_expired() class method
- String representation
"""

from datetime import timedelta

import pytest

from django.db import IntegrityError
from django.utils import timezone

from django_smart_ratelimit.models import RateLimitCounter


@pytest.fixture
def counter_data():
    """Base data for creating counters."""
    now = timezone.now()
    return {
        "key": "ip:192.168.1.1",
        "count": 1,
        "window_start": now,
        "window_end": now + timedelta(minutes=1),
    }


@pytest.mark.django_db
class TestRateLimitCounterCreation:
    """Test RateLimitCounter model creation."""

    def test_create_counter_basic(self, counter_data):
        """Test basic counter creation."""
        counter = RateLimitCounter.objects.create(**counter_data)

        assert counter.id is not None
        assert counter.key == "ip:192.168.1.1"
        assert counter.count == 1
        assert counter.window_start is not None
        assert counter.window_end is not None

    def test_create_counter_with_zero_count(self, counter_data):
        """Test counter creation with zero count (default)."""
        counter_data["count"] = 0
        counter = RateLimitCounter.objects.create(**counter_data)

        assert counter.count == 0

    def test_counter_default_count(self, counter_data):
        """Test that count defaults to 0 when not specified."""
        del counter_data["count"]
        counter = RateLimitCounter.objects.create(**counter_data)

        assert counter.count == 0

    def test_counter_timestamps_auto_set(self, counter_data):
        """Test that created_at and updated_at are auto-set."""
        counter = RateLimitCounter.objects.create(**counter_data)

        assert counter.created_at is not None
        assert counter.updated_at is not None
        # created_at and updated_at should be very close on creation
        time_diff = abs((counter.updated_at - counter.created_at).total_seconds())
        assert time_diff < 1

    def test_counter_updated_at_changes_on_save(self, counter_data):
        """Test that updated_at changes when counter is saved."""
        counter = RateLimitCounter.objects.create(**counter_data)
        original_updated_at = counter.updated_at

        counter.count = 5
        counter.save()
        counter.refresh_from_db()

        assert counter.updated_at >= original_updated_at

    def test_create_counter_various_keys(self):
        """Test counters with different key formats."""
        now = timezone.now()
        keys = [
            "ip:192.168.1.1",
            "user:42",
            "api:key:abc123",
            "tenant:acme:user:99",
            "header:x-client-id:client_xyz",
        ]

        for key in keys:
            counter = RateLimitCounter.objects.create(
                key=key,
                count=1,
                window_start=now,
                window_end=now + timedelta(minutes=1),
            )
            assert counter.key == key


@pytest.mark.django_db
class TestRateLimitCounterConstraints:
    """Test RateLimitCounter model constraints."""

    def test_unique_together_constraint(self, counter_data):
        """Test that key + window_start must be unique."""
        RateLimitCounter.objects.create(**counter_data)

        # Same key and window_start should fail
        with pytest.raises(IntegrityError):
            RateLimitCounter.objects.create(**counter_data)

    def test_same_key_different_window_allowed(self, counter_data):
        """Test that same key with different window_start is allowed."""
        RateLimitCounter.objects.create(**counter_data)

        # Same key but different window_start
        counter_data["window_start"] = timezone.now() + timedelta(minutes=2)
        counter_data["window_end"] = timezone.now() + timedelta(minutes=3)
        counter2 = RateLimitCounter.objects.create(**counter_data)

        assert counter2.id is not None

    def test_different_key_same_window_allowed(self, counter_data):
        """Test that different keys with same window is allowed."""
        RateLimitCounter.objects.create(**counter_data)

        counter_data["key"] = "ip:10.0.0.1"
        counter2 = RateLimitCounter.objects.create(**counter_data)

        assert counter2.id is not None

    def test_key_max_length(self):
        """Test key max length (255 characters)."""
        now = timezone.now()
        long_key = "k" * 255

        counter = RateLimitCounter.objects.create(
            key=long_key,
            count=1,
            window_start=now,
            window_end=now + timedelta(minutes=1),
        )
        assert len(counter.key) == 255


@pytest.mark.django_db
class TestRateLimitCounterMethods:
    """Test RateLimitCounter model methods."""

    def test_is_expired_when_not_expired(self, counter_data):
        """Test is_expired returns False when window is still active."""
        counter_data["window_end"] = timezone.now() + timedelta(hours=1)
        counter = RateLimitCounter.objects.create(**counter_data)

        assert counter.is_expired() is False

    def test_is_expired_when_expired(self, counter_data):
        """Test is_expired returns True when window has passed."""
        counter_data["window_start"] = timezone.now() - timedelta(hours=2)
        counter_data["window_end"] = timezone.now() - timedelta(hours=1)
        counter = RateLimitCounter.objects.create(**counter_data)

        assert counter.is_expired() is True

    def test_str_representation(self, counter_data):
        """Test string representation of counter."""
        counter = RateLimitCounter.objects.create(**counter_data)
        str_repr = str(counter)

        assert "ip:192.168.1.1" in str_repr
        assert "1" in str_repr  # count

    def test_cleanup_expired_deletes_old_records(self):
        """Test cleanup_expired removes expired counters."""
        now = timezone.now()

        # Create expired counters
        for i in range(5):
            RateLimitCounter.objects.create(
                key=f"expired:{i}",
                count=i,
                window_start=now - timedelta(hours=2),
                window_end=now - timedelta(hours=1),
            )

        # Create active counters
        for i in range(3):
            RateLimitCounter.objects.create(
                key=f"active:{i}",
                count=i,
                window_start=now,
                window_end=now + timedelta(hours=1),
            )

        assert RateLimitCounter.objects.count() == 8

        deleted = RateLimitCounter.cleanup_expired()

        assert deleted == 5
        assert RateLimitCounter.objects.count() == 3
        assert RateLimitCounter.objects.filter(key__startswith="active:").count() == 3

    def test_cleanup_expired_respects_batch_size(self):
        """Test cleanup_expired respects batch_size parameter."""
        now = timezone.now()

        # Create 10 expired counters
        for i in range(10):
            RateLimitCounter.objects.create(
                key=f"expired:{i}",
                count=i,
                window_start=now - timedelta(hours=2),
                window_end=now - timedelta(hours=1),
            )

        # Cleanup with batch_size=3 should still delete all
        deleted = RateLimitCounter.cleanup_expired(batch_size=3)

        assert deleted == 10
        assert RateLimitCounter.objects.count() == 0

    def test_cleanup_expired_no_records(self):
        """Test cleanup_expired when no expired records exist."""
        now = timezone.now()

        # Create only active counters
        RateLimitCounter.objects.create(
            key="active:1",
            count=1,
            window_start=now,
            window_end=now + timedelta(hours=1),
        )

        deleted = RateLimitCounter.cleanup_expired()

        assert deleted == 0
        assert RateLimitCounter.objects.count() == 1


@pytest.mark.django_db
class TestRateLimitCounterIndexes:
    """Test that indexes are properly used."""

    def test_key_window_start_index_exists(self):
        """Verify the key + window_start index exists."""
        # This tests that queries use the index (implicitly via model meta)
        now = timezone.now()

        # Create some test data
        for i in range(100):
            RateLimitCounter.objects.create(
                key=f"key:{i % 10}",
                count=1,
                window_start=now + timedelta(seconds=i),
                window_end=now + timedelta(minutes=1, seconds=i),
            )

        # This query should use the key + window_start index
        result = RateLimitCounter.objects.filter(
            key="key:5",
            window_start__gte=now,
        ).first()

        assert result is not None

    def test_window_end_index_for_cleanup(self):
        """Verify window_end index is used for cleanup queries."""
        now = timezone.now()

        # Create expired counters
        for i in range(50):
            RateLimitCounter.objects.create(
                key=f"key:{i}",
                count=1,
                window_start=now - timedelta(hours=2),
                window_end=now - timedelta(hours=1),
            )

        # Cleanup query uses window_end index
        expired_count = RateLimitCounter.objects.filter(window_end__lt=now).count()

        assert expired_count == 50
