"""Unit tests for DatabaseBackend leaky bucket operations."""

from datetime import timedelta

import pytest

from django.utils import timezone

from django_smart_ratelimit.backends.database import DatabaseBackend
from django_smart_ratelimit.models import RateLimitLeakyBucket


@pytest.fixture
def db_backend(db):
    """Create a database backend for testing."""
    return DatabaseBackend(
        algorithm="fixed_window",
        enable_background_cleanup=False,
    )


@pytest.mark.django_db
class TestDatabaseBackendLeakyBucketCheck:
    """Tests for leaky_bucket_check method."""

    def test_first_request_creates_bucket(self, db_backend):
        """Test that first request creates a new bucket."""
        result, metadata = db_backend.leaky_bucket_check(
            key="test:first",
            bucket_capacity=10,
            leak_rate=1.0,
            request_cost=1,
        )
        assert result is True
        assert metadata["bucket_level"] == 1
        assert metadata["bucket_capacity"] == 10
        assert RateLimitLeakyBucket.objects.filter(key__contains="test:first").exists()

    def test_request_allowed_with_space(self, db_backend):
        """Test that request is allowed when bucket has space."""
        # First request
        result1, _ = db_backend.leaky_bucket_check(
            key="test:space",
            bucket_capacity=10,
            leak_rate=1.0,
            request_cost=1,
        )
        assert result1 is True

        # Second request (still space)
        result2, metadata = db_backend.leaky_bucket_check(
            key="test:space",
            bucket_capacity=10,
            leak_rate=1.0,
            request_cost=1,
        )
        assert result2 is True
        # Allow for small leaking between requests
        assert abs(metadata["bucket_level"] - 2) < 0.1

    def test_request_rejected_when_bucket_full(self, db_backend):
        """Test that request is rejected when bucket is full."""
        # Fill the bucket with a very low leak rate to avoid leaking during test
        for _ in range(10):
            db_backend.leaky_bucket_check(
                key="test:full",
                bucket_capacity=10,
                leak_rate=0.001,  # Very slow leak
                request_cost=1,
            )

        # Next request should be rejected
        result, metadata = db_backend.leaky_bucket_check(
            key="test:full",
            bucket_capacity=10,
            leak_rate=0.001,  # Very slow leak
            request_cost=1,
        )
        assert result is False
        # Allow for tiny leakage
        assert metadata["space_remaining"] < 0.1

    def test_bucket_leaks_over_time(self, db_backend, db):
        """Test that bucket level decreases over time."""
        # Create a bucket at full capacity
        key = "test:leak"
        normalized_key = db_backend._normalize_key(key)

        RateLimitLeakyBucket.objects.create(
            key=normalized_key,
            level=10.0,
            last_leak=timezone.now() - timedelta(seconds=5),  # 5 seconds ago
            bucket_capacity=10,
            leak_rate=1.0,  # 1 per second
        )

        # After 5 seconds with leak_rate=1.0, level should be ~5
        result, metadata = db_backend.leaky_bucket_check(
            key=key,
            bucket_capacity=10,
            leak_rate=1.0,
            request_cost=1,
        )

        # Should be allowed now
        assert result is True
        # Level should be around 5 (leaked) + 1 (request) = 6
        assert abs(metadata["bucket_level"] - 6) < 0.5

    def test_zero_bucket_capacity_rejected(self, db_backend):
        """Test that zero bucket capacity always rejects."""
        result, metadata = db_backend.leaky_bucket_check(
            key="test:zero",
            bucket_capacity=0,
            leak_rate=1.0,
            request_cost=1,
        )
        assert result is False
        assert metadata["space_remaining"] == 0

    def test_high_request_cost(self, db_backend):
        """Test handling of high request cost."""
        result, metadata = db_backend.leaky_bucket_check(
            key="test:cost",
            bucket_capacity=10,
            leak_rate=1.0,
            request_cost=5,
        )
        assert result is True
        assert metadata["bucket_level"] == 5
        assert metadata["request_cost"] == 5

    def test_request_cost_exceeds_capacity(self, db_backend):
        """Test request with cost exceeding capacity."""
        result, metadata = db_backend.leaky_bucket_check(
            key="test:exceed",
            bucket_capacity=10,
            leak_rate=1.0,
            request_cost=15,
        )
        assert result is False
        assert metadata["time_until_space"] > 0


@pytest.mark.django_db
class TestDatabaseBackendLeakyBucketInfo:
    """Tests for leaky_bucket_info method."""

    def test_info_for_nonexistent_bucket(self, db_backend):
        """Test info for bucket that doesn't exist."""
        info = db_backend.leaky_bucket_info(
            key="test:nonexistent",
            bucket_capacity=10,
            leak_rate=1.0,
        )
        assert info["bucket_level"] == 0
        assert info["bucket_capacity"] == 10
        assert info["space_remaining"] == 10

    def test_info_for_existing_bucket(self, db_backend):
        """Test info for existing bucket."""
        # Create a bucket with very slow leak rate
        db_backend.leaky_bucket_check(
            key="test:exists",
            bucket_capacity=10,
            leak_rate=0.001,  # Very slow leak
            request_cost=5,
        )

        info = db_backend.leaky_bucket_info(
            key="test:exists",
            bucket_capacity=10,
            leak_rate=0.001,  # Very slow leak
        )
        # Allow for small leakage between operations
        assert abs(info["bucket_level"] - 5) < 0.1
        assert abs(info["space_remaining"] - 5) < 0.1

    def test_info_does_not_modify_bucket(self, db_backend):
        """Test that info doesn't modify bucket state."""
        # Create a bucket
        db_backend.leaky_bucket_check(
            key="test:readonly",
            bucket_capacity=10,
            leak_rate=1.0,
            request_cost=5,
        )

        # Get info multiple times
        info1 = db_backend.leaky_bucket_info(
            key="test:readonly",
            bucket_capacity=10,
            leak_rate=1.0,
        )
        info2 = db_backend.leaky_bucket_info(
            key="test:readonly",
            bucket_capacity=10,
            leak_rate=1.0,
        )

        # Level should be the same (within time tolerance)
        assert abs(info1["bucket_level"] - info2["bucket_level"]) < 0.1


@pytest.mark.django_db
class TestDatabaseBackendLeakyBucketCleanup:
    """Tests for leaky bucket cleanup."""

    def test_cleanup_includes_leaky_buckets(self, db_backend, db):
        """Test that cleanup_expired includes leaky buckets."""
        # Create a stale leaky bucket
        RateLimitLeakyBucket.objects.create(
            key="test:stale",
            level=5.0,
            last_leak=timezone.now() - timedelta(days=10),
            bucket_capacity=100,
            leak_rate=1.0,
        )

        result = db_backend.cleanup_expired()
        assert result["leaky_buckets"] == 1

    def test_cleanup_preserves_active_leaky_buckets(self, db_backend, db):
        """Test that cleanup preserves active leaky buckets."""
        # Create an active leaky bucket
        RateLimitLeakyBucket.objects.create(
            key="test:active",
            level=5.0,
            last_leak=timezone.now(),
            bucket_capacity=100,
            leak_rate=1.0,
        )

        result = db_backend.cleanup_expired()
        assert result["leaky_buckets"] == 0
        assert RateLimitLeakyBucket.objects.filter(key="test:active").exists()


@pytest.mark.django_db
class TestDatabaseBackendLeakyBucketReset:
    """Tests for reset method with leaky buckets."""

    def test_reset_deletes_leaky_bucket(self, db_backend):
        """Test that reset deletes leaky bucket for key."""
        key = "test:reset"
        # Create a bucket
        db_backend.leaky_bucket_check(
            key=key,
            bucket_capacity=10,
            leak_rate=1.0,
            request_cost=5,
        )

        normalized_key = db_backend._normalize_key(key)
        assert RateLimitLeakyBucket.objects.filter(key=normalized_key).exists()

        # Reset
        db_backend.reset(key)
        assert not RateLimitLeakyBucket.objects.filter(key=normalized_key).exists()


@pytest.mark.django_db
class TestDatabaseBackendLeakyBucketStats:
    """Tests for get_stats with leaky buckets."""

    def test_stats_includes_leaky_buckets(self, db_backend, db):
        """Test that stats includes leaky bucket count."""
        # Create some leaky buckets
        for i in range(3):
            RateLimitLeakyBucket.objects.create(
                key=f"test:stats:{i}",
                level=5.0,
                last_leak=timezone.now(),
                bucket_capacity=100,
                leak_rate=1.0,
            )

        stats = db_backend.get_stats()
        assert stats["leaky_buckets"] == 3
        assert stats["total_records"] >= 3


@pytest.mark.django_db
class TestDatabaseBackendLeakyBucketClearAll:
    """Tests for clear_all with leaky buckets."""

    def test_clear_all_deletes_leaky_buckets(self, db_backend, db):
        """Test that clear_all deletes all leaky buckets."""
        # Create some leaky buckets
        for i in range(5):
            RateLimitLeakyBucket.objects.create(
                key=f"test:clear:{i}",
                level=5.0,
                last_leak=timezone.now(),
                bucket_capacity=100,
                leak_rate=1.0,
            )

        assert RateLimitLeakyBucket.objects.count() == 5
        db_backend.clear_all()
        assert RateLimitLeakyBucket.objects.count() == 0
