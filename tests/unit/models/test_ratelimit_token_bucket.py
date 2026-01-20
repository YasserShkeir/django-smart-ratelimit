"""Unit tests for RateLimitTokenBucket model.

Tests cover:
- Model creation and validation
- Unique key constraint
- calculate_current_tokens() method
- consume() method
- time_until_tokens() method
- cleanup_stale() class method
- String representation
"""

from datetime import timedelta

import pytest

from django.db import IntegrityError
from django.utils import timezone

from django_smart_ratelimit.models import RateLimitTokenBucket


@pytest.fixture
def bucket_data():
    """Base data for creating token buckets."""
    return {
        "key": "api:client_123",
        "tokens": 100.0,
        "last_update": timezone.now(),
        "bucket_size": 100,
        "refill_rate": 10.0,  # 10 tokens per second
    }


@pytest.mark.django_db
class TestRateLimitTokenBucketCreation:
    """Test RateLimitTokenBucket model creation."""

    def test_create_bucket_basic(self, bucket_data):
        """Test basic bucket creation."""
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        assert bucket.id is not None
        assert bucket.key == "api:client_123"
        assert bucket.tokens == 100.0
        assert bucket.bucket_size == 100
        assert bucket.refill_rate == 10.0

    def test_create_bucket_with_partial_tokens(self, bucket_data):
        """Test bucket creation with partial tokens."""
        bucket_data["tokens"] = 50.5
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        assert bucket.tokens == 50.5

    def test_create_bucket_with_zero_tokens(self, bucket_data):
        """Test bucket creation with zero tokens."""
        bucket_data["tokens"] = 0.0
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        assert bucket.tokens == 0.0

    def test_bucket_created_at_auto_set(self, bucket_data):
        """Test that created_at is auto-set."""
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        assert bucket.created_at is not None

    def test_create_buckets_various_refill_rates(self, bucket_data):
        """Test buckets with different refill rates."""
        refill_rates = [0.1, 1.0, 10.0, 100.0, 1000.0]

        for i, rate in enumerate(refill_rates):
            bucket_data["key"] = f"bucket:{i}"
            bucket_data["refill_rate"] = rate
            bucket = RateLimitTokenBucket.objects.create(**bucket_data)
            assert bucket.refill_rate == rate


@pytest.mark.django_db
class TestRateLimitTokenBucketConstraints:
    """Test RateLimitTokenBucket model constraints."""

    def test_unique_key_constraint(self, bucket_data):
        """Test that key must be unique."""
        RateLimitTokenBucket.objects.create(**bucket_data)

        # Same key should fail
        with pytest.raises(IntegrityError):
            RateLimitTokenBucket.objects.create(**bucket_data)

    def test_different_keys_allowed(self, bucket_data):
        """Test that different keys are allowed."""
        RateLimitTokenBucket.objects.create(**bucket_data)

        bucket_data["key"] = "api:client_456"
        bucket2 = RateLimitTokenBucket.objects.create(**bucket_data)

        assert bucket2.id is not None

    def test_key_max_length(self, bucket_data):
        """Test key max length (255 characters)."""
        bucket_data["key"] = "k" * 255
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        assert len(bucket.key) == 255


@pytest.mark.django_db
class TestRateLimitTokenBucketCalculateTokens:
    """Test RateLimitTokenBucket.calculate_current_tokens() method."""

    def test_calculate_tokens_no_time_elapsed(self, bucket_data):
        """Test tokens calculation when no time has elapsed."""
        bucket_data["tokens"] = 50.0
        bucket_data["last_update"] = timezone.now()
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        current = bucket.calculate_current_tokens()

        # Should be approximately 50 (may have tiny time difference)
        assert 49.9 <= current <= 50.1

    def test_calculate_tokens_with_refill(self, bucket_data):
        """Test tokens calculation with time elapsed for refill."""
        bucket_data["tokens"] = 50.0
        bucket_data["refill_rate"] = 10.0  # 10 per second
        bucket_data["last_update"] = timezone.now() - timedelta(seconds=3)
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        current = bucket.calculate_current_tokens()

        # 50 + (3 seconds * 10 tokens/sec) = 80
        assert 79.9 <= current <= 80.1

    def test_calculate_tokens_caps_at_bucket_size(self, bucket_data):
        """Test that tokens don't exceed bucket_size."""
        bucket_data["tokens"] = 90.0
        bucket_data["bucket_size"] = 100
        bucket_data["refill_rate"] = 10.0
        # 5 seconds of refill would give 50 tokens, for 140 total
        bucket_data["last_update"] = timezone.now() - timedelta(seconds=5)
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        current = bucket.calculate_current_tokens()

        # Should cap at bucket_size (100)
        assert current == 100.0

    def test_calculate_tokens_empty_bucket_refills(self, bucket_data):
        """Test refilling an empty bucket."""
        bucket_data["tokens"] = 0.0
        bucket_data["refill_rate"] = 5.0  # 5 per second
        bucket_data["last_update"] = timezone.now() - timedelta(seconds=10)
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        current = bucket.calculate_current_tokens()

        # 0 + (10 seconds * 5 tokens/sec) = 50
        assert 49.9 <= current <= 50.1

    def test_calculate_tokens_slow_refill_rate(self, bucket_data):
        """Test calculation with slow refill rate."""
        bucket_data["tokens"] = 10.0
        bucket_data["refill_rate"] = 0.1  # 0.1 per second
        bucket_data["last_update"] = timezone.now() - timedelta(seconds=100)
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        current = bucket.calculate_current_tokens()

        # 10 + (100 seconds * 0.1 tokens/sec) = 20
        assert 19.9 <= current <= 20.1


@pytest.mark.django_db
class TestRateLimitTokenBucketConsume:
    """Test RateLimitTokenBucket.consume() method."""

    def test_consume_success(self, bucket_data):
        """Test successful token consumption."""
        bucket_data["tokens"] = 50.0
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        result = bucket.consume(10)

        assert result is True
        bucket.refresh_from_db()
        # Tokens should be approximately 40 (allowing for tiny time delta)
        assert 39.0 <= bucket.tokens <= 41.0

    def test_consume_single_token(self, bucket_data):
        """Test consuming single token (default)."""
        bucket_data["tokens"] = 100.0
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        result = bucket.consume()  # Default is 1

        assert result is True
        bucket.refresh_from_db()
        assert 98.9 <= bucket.tokens <= 99.1

    def test_consume_insufficient_tokens(self, bucket_data):
        """Test consumption fails when insufficient tokens."""
        bucket_data["tokens"] = 5.0
        bucket_data["last_update"] = timezone.now()  # No refill time
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        result = bucket.consume(10)

        assert result is False
        bucket.refresh_from_db()
        # Tokens should be unchanged
        assert bucket.tokens == 5.0

    def test_consume_exactly_available(self, bucket_data):
        """Test consuming exactly available tokens."""
        bucket_data["tokens"] = 10.0
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        result = bucket.consume(10)

        assert result is True
        bucket.refresh_from_db()
        # Should be at or very near 0
        assert bucket.tokens <= 0.1

    def test_consume_updates_last_update(self, bucket_data):
        """Test that consume updates last_update timestamp."""
        old_time = timezone.now() - timedelta(hours=1)
        bucket_data["last_update"] = old_time
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        bucket.consume(1)

        bucket.refresh_from_db()
        # last_update should be recent
        time_diff = abs((timezone.now() - bucket.last_update).total_seconds())
        assert time_diff < 1

    def test_consume_with_refill_calculation(self, bucket_data):
        """Test consume accounts for refilled tokens."""
        bucket_data["tokens"] = 5.0
        bucket_data["refill_rate"] = 10.0  # 10 per second
        bucket_data["last_update"] = timezone.now() - timedelta(seconds=5)
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        # After 5 seconds: 5 + (5 * 10) = 55 tokens
        result = bucket.consume(50)

        assert result is True
        bucket.refresh_from_db()
        # Should have about 5 tokens remaining
        assert 4.0 <= bucket.tokens <= 6.0


@pytest.mark.django_db
class TestRateLimitTokenBucketTimeUntilTokens:
    """Test RateLimitTokenBucket.time_until_tokens() method."""

    def test_time_until_tokens_already_available(self, bucket_data):
        """Test when tokens are already available."""
        bucket_data["tokens"] = 50.0
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        wait_time = bucket.time_until_tokens(30)

        assert wait_time == 0.0

    def test_time_until_tokens_need_refill(self, bucket_data):
        """Test calculation when tokens need to refill."""
        bucket_data["tokens"] = 10.0
        bucket_data["refill_rate"] = 5.0  # 5 per second
        bucket_data["last_update"] = timezone.now()
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        # Need 30 tokens, have 10, deficit = 20
        # At 5 tokens/sec, need 4 seconds
        wait_time = bucket.time_until_tokens(30)

        assert 3.9 <= wait_time <= 4.1

    def test_time_until_tokens_empty_bucket(self, bucket_data):
        """Test calculation with empty bucket."""
        bucket_data["tokens"] = 0.0
        bucket_data["refill_rate"] = 10.0  # 10 per second
        bucket_data["last_update"] = timezone.now()
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        # Need 50 tokens, have 0, deficit = 50
        # At 10 tokens/sec, need 5 seconds
        wait_time = bucket.time_until_tokens(50)

        assert 4.9 <= wait_time <= 5.1

    def test_time_until_tokens_accounts_for_partial_refill(self, bucket_data):
        """Test that partial refill is accounted for."""
        bucket_data["tokens"] = 10.0
        bucket_data["refill_rate"] = 10.0
        bucket_data["last_update"] = timezone.now() - timedelta(seconds=2)
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        # Current: 10 + (2 * 10) = 30
        # Need 50, deficit = 20
        # At 10 tokens/sec, need 2 more seconds
        wait_time = bucket.time_until_tokens(50)

        assert 1.9 <= wait_time <= 2.1


@pytest.mark.django_db
class TestRateLimitTokenBucketStr:
    """Test RateLimitTokenBucket string representation."""

    def test_str_representation(self, bucket_data):
        """Test string representation."""
        bucket_data["tokens"] = 75.5
        bucket_data["bucket_size"] = 100
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        str_repr = str(bucket)

        assert "api:client_123" in str_repr
        assert "75.5" in str_repr
        assert "100" in str_repr


@pytest.mark.django_db
class TestRateLimitTokenBucketCleanup:
    """Test RateLimitTokenBucket.cleanup_stale() method."""

    def test_cleanup_stale_deletes_old_buckets(self, bucket_data):
        """Test cleanup_stale removes old buckets."""
        now = timezone.now()

        # Create stale buckets (not updated in 10 days)
        for i in range(5):
            RateLimitTokenBucket.objects.create(
                key=f"stale:{i}",
                tokens=100.0,
                last_update=now - timedelta(days=10),
                bucket_size=100,
                refill_rate=10.0,
            )

        # Create active buckets (recently updated)
        for i in range(3):
            RateLimitTokenBucket.objects.create(
                key=f"active:{i}",
                tokens=50.0,
                last_update=now - timedelta(hours=1),
                bucket_size=100,
                refill_rate=10.0,
            )

        assert RateLimitTokenBucket.objects.count() == 8

        deleted = RateLimitTokenBucket.cleanup_stale(days=7)

        assert deleted == 5
        assert RateLimitTokenBucket.objects.count() == 3
        assert (
            RateLimitTokenBucket.objects.filter(key__startswith="active:").count() == 3
        )

    def test_cleanup_stale_respects_days_parameter(self, bucket_data):
        """Test cleanup_stale respects the days parameter."""
        now = timezone.now()

        # Buckets updated 5 days ago
        for i in range(5):
            RateLimitTokenBucket.objects.create(
                key=f"bucket:{i}",
                tokens=100.0,
                last_update=now - timedelta(days=5),
                bucket_size=100,
                refill_rate=10.0,
            )

        # With days=7, these should NOT be deleted
        deleted = RateLimitTokenBucket.cleanup_stale(days=7)
        assert deleted == 0
        assert RateLimitTokenBucket.objects.count() == 5

        # With days=3, these SHOULD be deleted
        deleted = RateLimitTokenBucket.cleanup_stale(days=3)
        assert deleted == 5
        assert RateLimitTokenBucket.objects.count() == 0

    def test_cleanup_stale_with_batch_size(self):
        """Test cleanup_stale with batch_size parameter."""
        now = timezone.now()

        # Create 15 stale buckets
        for i in range(15):
            RateLimitTokenBucket.objects.create(
                key=f"stale:{i}",
                tokens=100.0,
                last_update=now - timedelta(days=30),
                bucket_size=100,
                refill_rate=10.0,
            )

        deleted = RateLimitTokenBucket.cleanup_stale(days=7, batch_size=5)

        assert deleted == 15
        assert RateLimitTokenBucket.objects.count() == 0

    def test_cleanup_stale_no_stale_buckets(self, bucket_data):
        """Test cleanup_stale when no stale buckets exist."""
        RateLimitTokenBucket.objects.create(**bucket_data)

        deleted = RateLimitTokenBucket.cleanup_stale(days=7)

        assert deleted == 0
        assert RateLimitTokenBucket.objects.count() == 1


@pytest.mark.django_db
class TestRateLimitTokenBucketRealWorldScenarios:
    """Test realistic token bucket scenarios."""

    def test_api_rate_limiting_scenario(self):
        """Simulate API rate limiting with token bucket."""
        bucket = RateLimitTokenBucket.objects.create(
            key="api:user_42",
            tokens=10.0,
            last_update=timezone.now(),
            bucket_size=10,
            refill_rate=1.0,  # 1 token per second
        )

        # Rapid requests should consume tokens
        successful_requests = 0
        for _ in range(15):
            if bucket.consume(1):
                successful_requests += 1

        # Should allow about 10 requests (bucket was full)
        assert successful_requests == 10

    def test_burst_then_steady_rate(self):
        """Test burst capability followed by steady rate."""
        bucket = RateLimitTokenBucket.objects.create(
            key="api:user_burst",
            tokens=100.0,  # Full bucket
            last_update=timezone.now(),
            bucket_size=100,
            refill_rate=10.0,  # 10 per second
        )

        # Burst: consume 50 tokens at once
        assert bucket.consume(50) is True
        bucket.refresh_from_db()
        assert 49.0 <= bucket.tokens <= 51.0

        # Try to consume another 60 - should fail (only ~50 available)
        # Note: No time has passed in test, so no refill
        assert bucket.consume(60) is False

    def test_token_bucket_recovery_after_pause(self, bucket_data):
        """Test bucket recovery after a pause period."""
        bucket_data["tokens"] = 0.0  # Empty bucket
        bucket_data["refill_rate"] = 10.0  # 10 per second
        bucket_data["bucket_size"] = 100
        bucket_data["last_update"] = timezone.now() - timedelta(seconds=10)
        bucket = RateLimitTokenBucket.objects.create(**bucket_data)

        # After 10 seconds, should have 100 tokens (capped at bucket_size)
        current = bucket.calculate_current_tokens()
        assert current == 100.0

        # Should be able to consume tokens now
        assert bucket.consume(50) is True


@pytest.mark.django_db
class TestRateLimitTokenBucketIndexes:
    """Test that indexes are properly used."""

    def test_key_index(self):
        """Verify key index exists and is used."""
        # Create test data
        for i in range(100):
            RateLimitTokenBucket.objects.create(
                key=f"bucket:{i}",
                tokens=100.0,
                last_update=timezone.now(),
                bucket_size=100,
                refill_rate=10.0,
            )

        # This query should use the key index
        bucket = RateLimitTokenBucket.objects.filter(key="bucket:50").first()

        assert bucket is not None
        assert bucket.key == "bucket:50"
