"""Unit tests for RateLimitLeakyBucket model."""

from datetime import timedelta

import pytest

from django.utils import timezone

from django_smart_ratelimit.models import RateLimitLeakyBucket


@pytest.fixture
def leaky_bucket(db):
    """Create a leaky bucket for testing."""
    return RateLimitLeakyBucket.objects.create(
        key="test:leaky:bucket",
        level=5.0,
        last_leak=timezone.now(),
        bucket_capacity=10,
        leak_rate=1.0,
    )


@pytest.fixture
def stale_leaky_buckets(db):
    """Create stale leaky buckets for cleanup testing."""
    now = timezone.now()
    buckets = []
    for i in range(5):
        bucket = RateLimitLeakyBucket.objects.create(
            key=f"stale:leaky:{i}",
            level=5.0,
            last_leak=now - timedelta(days=10),
            bucket_capacity=100,
            leak_rate=1.0,
        )
        buckets.append(bucket)
    return buckets


@pytest.fixture
def active_leaky_buckets(db):
    """Create active leaky buckets for cleanup testing."""
    now = timezone.now()
    buckets = []
    for i in range(3):
        bucket = RateLimitLeakyBucket.objects.create(
            key=f"active:leaky:{i}",
            level=5.0,
            last_leak=now,
            bucket_capacity=100,
            leak_rate=1.0,
        )
        buckets.append(bucket)
    return buckets


@pytest.mark.django_db
class TestRateLimitLeakyBucketModel:
    """Tests for RateLimitLeakyBucket model."""

    def test_create_bucket(self, db):
        """Test creating a leaky bucket."""
        now = timezone.now()
        bucket = RateLimitLeakyBucket.objects.create(
            key="test:bucket",
            level=0.0,
            last_leak=now,
            bucket_capacity=100,
            leak_rate=10.0,
        )
        assert bucket.key == "test:bucket"
        assert bucket.level == 0.0
        assert bucket.bucket_capacity == 100
        assert bucket.leak_rate == 10.0
        assert bucket.created_at is not None

    def test_unique_key(self, leaky_bucket):
        """Test that key is unique."""
        with pytest.raises(Exception):  # IntegrityError
            RateLimitLeakyBucket.objects.create(
                key=leaky_bucket.key,
                level=0.0,
                last_leak=timezone.now(),
                bucket_capacity=100,
                leak_rate=1.0,
            )

    def test_str_representation(self, leaky_bucket):
        """Test string representation of leaky bucket."""
        str_repr = str(leaky_bucket)
        assert "test:leaky:bucket" in str_repr
        assert "5.0" in str_repr
        assert "10" in str_repr


@pytest.mark.django_db
class TestRateLimitLeakyBucketCalculations:
    """Tests for leaky bucket calculation methods."""

    def test_calculate_current_level_no_leaking(self, leaky_bucket):
        """Test current level calculation when no time has passed."""
        # Refresh from db to get exact time
        leaky_bucket.refresh_from_db()
        # Should be approximately the same (within milliseconds)
        current_level = leaky_bucket.calculate_current_level()
        assert abs(current_level - 5.0) < 0.1

    def test_calculate_current_level_with_leaking(self, db):
        """Test current level calculation after time passes."""
        bucket = RateLimitLeakyBucket.objects.create(
            key="test:leak:calc",
            level=10.0,
            last_leak=timezone.now() - timedelta(seconds=5),
            bucket_capacity=100,
            leak_rate=1.0,  # 1 unit per second
        )
        # After 5 seconds with leak_rate=1.0, level should be ~5.0
        current_level = bucket.calculate_current_level()
        assert abs(current_level - 5.0) < 0.2

    def test_calculate_current_level_cannot_go_negative(self, db):
        """Test that level cannot go below 0."""
        bucket = RateLimitLeakyBucket.objects.create(
            key="test:negative",
            level=5.0,
            last_leak=timezone.now() - timedelta(seconds=100),  # Long time ago
            bucket_capacity=100,
            leak_rate=1.0,
        )
        # After 100 seconds with leak_rate=1.0, would be -95, but should be 0
        current_level = bucket.calculate_current_level()
        assert current_level == 0

    def test_space_remaining(self, db):
        """Test space_remaining calculation."""
        bucket = RateLimitLeakyBucket.objects.create(
            key="test:space",
            level=30.0,
            last_leak=timezone.now(),
            bucket_capacity=100,
            leak_rate=1.0,
        )
        space = bucket.space_remaining()
        assert abs(space - 70.0) < 0.5

    def test_time_until_space_already_available(self, db):
        """Test time_until_space when space is available."""
        bucket = RateLimitLeakyBucket.objects.create(
            key="test:time:available",
            level=50.0,
            last_leak=timezone.now(),
            bucket_capacity=100,
            leak_rate=1.0,
        )
        time_until = bucket.time_until_space(10)
        assert time_until == 0.0  # 50 space available, need 10

    def test_time_until_space_not_available(self, db):
        """Test time_until_space when space is not available."""
        bucket = RateLimitLeakyBucket.objects.create(
            key="test:time:not:available",
            level=99.0,
            last_leak=timezone.now(),
            bucket_capacity=100,
            leak_rate=1.0,
        )
        # Need 10 space, have ~1, need 9 more
        # With leak_rate=1.0, need ~9 seconds
        time_until = bucket.time_until_space(10)
        assert abs(time_until - 9.0) < 0.5


@pytest.mark.django_db
class TestRateLimitLeakyBucketAddRequest:
    """Tests for add_request method."""

    def test_add_request_success(self, db):
        """Test adding a request when space available."""
        bucket = RateLimitLeakyBucket.objects.create(
            key="test:add:success",
            level=5.0,
            last_leak=timezone.now(),
            bucket_capacity=100,
            leak_rate=1.0,
        )
        result = bucket.add_request(10)
        assert result is True
        bucket.refresh_from_db()
        assert bucket.level > 5.0  # Level increased

    def test_add_request_failure_bucket_full(self, db):
        """Test adding a request when bucket would overflow."""
        bucket = RateLimitLeakyBucket.objects.create(
            key="test:add:fail",
            level=95.0,
            last_leak=timezone.now(),
            bucket_capacity=100,
            leak_rate=1.0,
        )
        result = bucket.add_request(10)
        assert result is False
        bucket.refresh_from_db()
        assert bucket.level == 95.0  # Level unchanged

    def test_add_request_updates_last_leak(self, db):
        """Test that add_request updates last_leak time."""
        old_time = timezone.now() - timedelta(seconds=10)
        bucket = RateLimitLeakyBucket.objects.create(
            key="test:add:time",
            level=5.0,
            last_leak=old_time,
            bucket_capacity=100,
            leak_rate=1.0,
        )
        bucket.add_request(1)
        bucket.refresh_from_db()
        assert bucket.last_leak > old_time


@pytest.mark.django_db
class TestRateLimitLeakyBucketCleanup:
    """Tests for cleanup_stale classmethod."""

    def test_cleanup_stale_removes_old_buckets(self, stale_leaky_buckets):
        """Test that cleanup removes stale buckets."""
        assert RateLimitLeakyBucket.objects.count() == 5
        deleted = RateLimitLeakyBucket.cleanup_stale(days=7)
        assert deleted == 5
        assert RateLimitLeakyBucket.objects.count() == 0

    def test_cleanup_stale_keeps_active_buckets(
        self, stale_leaky_buckets, active_leaky_buckets
    ):
        """Test that cleanup keeps active buckets."""
        assert RateLimitLeakyBucket.objects.count() == 8
        deleted = RateLimitLeakyBucket.cleanup_stale(days=7)
        assert deleted == 5
        assert RateLimitLeakyBucket.objects.count() == 3
        assert (
            RateLimitLeakyBucket.objects.filter(key__startswith="active:").count() == 3
        )

    def test_cleanup_stale_custom_days(self, db):
        """Test cleanup with custom days threshold."""
        now = timezone.now()
        # Create bucket 3 days old
        RateLimitLeakyBucket.objects.create(
            key="test:3days",
            level=5.0,
            last_leak=now - timedelta(days=3),
            bucket_capacity=100,
            leak_rate=1.0,
        )
        # With default 7 days, should not be deleted
        deleted = RateLimitLeakyBucket.cleanup_stale(days=7)
        assert deleted == 0
        # With 2 days, should be deleted
        deleted = RateLimitLeakyBucket.cleanup_stale(days=2)
        assert deleted == 1

    def test_cleanup_stale_batch_size(self, db):
        """Test cleanup with batch size limit."""
        now = timezone.now()
        # Create 50 stale buckets
        for i in range(50):
            RateLimitLeakyBucket.objects.create(
                key=f"batch:test:{i}",
                level=5.0,
                last_leak=now - timedelta(days=10),
                bucket_capacity=100,
                leak_rate=1.0,
            )
        # Even with small batch size, all should be deleted
        deleted = RateLimitLeakyBucket.cleanup_stale(days=7, batch_size=10)
        assert deleted == 50
        assert RateLimitLeakyBucket.objects.count() == 0
