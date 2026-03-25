"""Unit tests for ratelimit_cleanup management command."""

import json
from datetime import timedelta
from io import StringIO

import pytest

from django.core.management import call_command
from django.utils import timezone


@pytest.fixture
def expired_counters(db):
    """Create expired rate limit counters."""
    from django_smart_ratelimit.models import RateLimitCounter

    now = timezone.now()
    counters = []

    # Create expired counters
    for i in range(5):
        counter = RateLimitCounter.objects.create(
            key=f"expired:counter:{i}",
            count=i + 1,
            window_start=now - timedelta(hours=2),
            window_end=now - timedelta(hours=1),
        )
        counters.append(counter)

    return counters


@pytest.fixture
def active_counters(db):
    """Create active (non-expired) rate limit counters."""
    from django_smart_ratelimit.models import RateLimitCounter

    now = timezone.now()
    counters = []

    # Create active counters
    for i in range(3):
        counter = RateLimitCounter.objects.create(
            key=f"active:counter:{i}",
            count=i + 1,
            window_start=now,
            window_end=now + timedelta(hours=1),
        )
        counters.append(counter)

    return counters


@pytest.fixture
def expired_entries(db):
    """Create expired sliding window entries."""
    from django_smart_ratelimit.models import RateLimitEntry

    now = timezone.now()
    entries = []

    # Create expired entries
    for i in range(7):
        entry = RateLimitEntry.objects.create(
            key=f"expired:entry:{i}",
            timestamp=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        entries.append(entry)

    return entries


@pytest.fixture
def active_entries(db):
    """Create active sliding window entries."""
    from django_smart_ratelimit.models import RateLimitEntry

    now = timezone.now()
    entries = []

    # Create active entries
    for i in range(4):
        entry = RateLimitEntry.objects.create(
            key=f"active:entry:{i}",
            timestamp=now,
            expires_at=now + timedelta(hours=1),
        )
        entries.append(entry)

    return entries


@pytest.fixture
def stale_buckets(db):
    """Create stale token buckets."""
    from django_smart_ratelimit.models import RateLimitTokenBucket

    now = timezone.now()
    buckets = []

    # Create stale buckets (last updated 10 days ago)
    for i in range(4):
        bucket = RateLimitTokenBucket.objects.create(
            key=f"stale:bucket:{i}",
            tokens=50.0,
            last_update=now - timedelta(days=10),
            bucket_size=100,
            refill_rate=1.0,
        )
        buckets.append(bucket)

    return buckets


@pytest.fixture
def active_buckets(db):
    """Create active token buckets."""
    from django_smart_ratelimit.models import RateLimitTokenBucket

    now = timezone.now()
    buckets = []

    # Create active buckets (recently updated)
    for i in range(2):
        bucket = RateLimitTokenBucket.objects.create(
            key=f"active:bucket:{i}",
            tokens=50.0,
            last_update=now,
            bucket_size=100,
            refill_rate=1.0,
        )
        buckets.append(bucket)

    return buckets


@pytest.mark.django_db
class TestRatelimitCleanupBasic:
    """Basic tests for ratelimit_cleanup command."""

    def test_command_runs_without_error(self):
        """Test that the command runs without error on empty database."""
        out = StringIO()
        call_command("ratelimit_cleanup", stdout=out)
        output = out.getvalue()
        assert "Cleanup completed" in output or "Total:" in output

    def test_dry_run_shows_but_does_not_delete(
        self, expired_counters, expired_entries, stale_buckets
    ):
        """Test that --dry-run shows what would be deleted but doesn't delete."""
        from django_smart_ratelimit.models import (
            RateLimitCounter,
            RateLimitEntry,
            RateLimitTokenBucket,
        )

        initial_counters = RateLimitCounter.objects.count()
        initial_entries = RateLimitEntry.objects.count()
        initial_buckets = RateLimitTokenBucket.objects.count()

        out = StringIO()
        call_command("ratelimit_cleanup", "--dry-run", stdout=out)
        output = out.getvalue()

        # Check output mentions dry run
        assert "DRY RUN" in output

        # Verify nothing was deleted
        assert RateLimitCounter.objects.count() == initial_counters
        assert RateLimitEntry.objects.count() == initial_entries
        assert RateLimitTokenBucket.objects.count() == initial_buckets

    def test_cleanup_removes_expired_counters(self, expired_counters, active_counters):
        """Test that cleanup removes only expired counters."""
        from django_smart_ratelimit.models import RateLimitCounter

        assert RateLimitCounter.objects.count() == 8  # 5 expired + 3 active

        out = StringIO()
        call_command("ratelimit_cleanup", stdout=out)

        # Only active counters should remain
        assert RateLimitCounter.objects.count() == 3
        # Verify they are the active ones
        assert RateLimitCounter.objects.filter(key__startswith="active:").count() == 3

    def test_cleanup_removes_expired_entries(self, expired_entries, active_entries):
        """Test that cleanup removes only expired entries."""
        from django_smart_ratelimit.models import RateLimitEntry

        assert RateLimitEntry.objects.count() == 11  # 7 expired + 4 active

        out = StringIO()
        call_command("ratelimit_cleanup", stdout=out)

        # Only active entries should remain
        assert RateLimitEntry.objects.count() == 4
        # Verify they are the active ones
        assert RateLimitEntry.objects.filter(key__startswith="active:").count() == 4

    def test_cleanup_removes_stale_buckets(self, stale_buckets, active_buckets):
        """Test that cleanup removes only stale token buckets."""
        from django_smart_ratelimit.models import RateLimitTokenBucket

        assert RateLimitTokenBucket.objects.count() == 6  # 4 stale + 2 active

        out = StringIO()
        call_command("ratelimit_cleanup", stdout=out)

        # Only active buckets should remain
        assert RateLimitTokenBucket.objects.count() == 2
        # Verify they are the active ones
        assert (
            RateLimitTokenBucket.objects.filter(key__startswith="active:").count() == 2
        )

    def test_cleanup_preserves_active_records(
        self, active_counters, active_entries, active_buckets
    ):
        """Test that cleanup preserves all active records."""
        from django_smart_ratelimit.models import (
            RateLimitCounter,
            RateLimitEntry,
            RateLimitTokenBucket,
        )

        out = StringIO()
        call_command("ratelimit_cleanup", stdout=out)

        # All active records should remain
        assert RateLimitCounter.objects.count() == 3
        assert RateLimitEntry.objects.count() == 4
        assert RateLimitTokenBucket.objects.count() == 2


@pytest.mark.django_db
class TestRatelimitCleanupOptions:
    """Tests for command options."""

    def test_batch_size_option(self, db):
        """Test that --batch-size controls deletion batches."""
        from django_smart_ratelimit.models import RateLimitCounter

        now = timezone.now()

        # Create 50 expired counters
        for i in range(50):
            RateLimitCounter.objects.create(
                key=f"batch:test:{i}",
                count=1,
                window_start=now - timedelta(hours=2),
                window_end=now - timedelta(hours=1),
            )

        out = StringIO()
        call_command("ratelimit_cleanup", "--batch-size=10", "--verbose", stdout=out)
        out.getvalue()

        # With batch size 10 and 50 records, we should see multiple batches
        # Check that all records were deleted
        assert RateLimitCounter.objects.count() == 0

    def test_stale_days_option(self, db):
        """Test that --stale-days controls token bucket cleanup."""
        from django_smart_ratelimit.models import RateLimitTokenBucket

        now = timezone.now()

        # Create buckets of different ages
        # 5 days old - should NOT be deleted with default 7 days
        RateLimitTokenBucket.objects.create(
            key="bucket:5days",
            tokens=50.0,
            last_update=now - timedelta(days=5),
            bucket_size=100,
            refill_rate=1.0,
        )

        # 10 days old - should be deleted with default 7 days
        RateLimitTokenBucket.objects.create(
            key="bucket:10days",
            tokens=50.0,
            last_update=now - timedelta(days=10),
            bucket_size=100,
            refill_rate=1.0,
        )

        # Test with default (7 days)
        out = StringIO()
        call_command("ratelimit_cleanup", stdout=out)

        # 5-day bucket should remain, 10-day bucket should be deleted
        assert RateLimitTokenBucket.objects.count() == 1
        assert RateLimitTokenBucket.objects.filter(key="bucket:5days").exists()

    def test_stale_days_custom_value(self, db):
        """Test custom --stale-days value."""
        from django_smart_ratelimit.models import RateLimitTokenBucket

        now = timezone.now()

        # Create bucket 3 days old
        RateLimitTokenBucket.objects.create(
            key="bucket:3days",
            tokens=50.0,
            last_update=now - timedelta(days=3),
            bucket_size=100,
            refill_rate=1.0,
        )

        # With --stale-days=2, the 3-day bucket should be deleted
        out = StringIO()
        call_command("ratelimit_cleanup", "--stale-days=2", stdout=out)

        assert RateLimitTokenBucket.objects.count() == 0


@pytest.mark.django_db
class TestRatelimitCleanupOutput:
    """Tests for command output formatting."""

    def test_json_output(self, expired_counters, expired_entries, stale_buckets):
        """Test that --json outputs valid JSON."""
        out = StringIO()
        call_command("ratelimit_cleanup", "--json", stdout=out)
        output = out.getvalue()

        # Should be valid JSON
        data = json.loads(output)

        # Check structure
        assert "counters" in data
        assert "entries" in data
        assert "token_buckets" in data
        assert "total_deleted" in data
        assert "elapsed_seconds" in data

        # Check values
        assert data["counters"]["deleted"] == 5
        assert data["entries"]["deleted"] == 7
        assert data["token_buckets"]["deleted"] == 4

    def test_json_output_dry_run(
        self, expired_counters, expired_entries, stale_buckets
    ):
        """Test JSON output with --dry-run."""
        out = StringIO()
        call_command("ratelimit_cleanup", "--json", "--dry-run", stdout=out)
        output = out.getvalue()

        data = json.loads(output)

        # Dry run should show found but not deleted
        assert data["dry_run"] is True
        assert data["counters"]["found"] == 5
        assert data["counters"]["deleted"] == 0
        assert data["entries"]["found"] == 7
        assert data["entries"]["deleted"] == 0

    def test_verbose_output(self, expired_counters):
        """Test verbose output shows progress."""
        out = StringIO()
        call_command("ratelimit_cleanup", "--verbose", stdout=out)
        output = out.getvalue()

        # Should show found records
        assert "Found" in output or "found" in output.lower()

    def test_empty_database_output(self, db):
        """Test output when database is empty."""
        out = StringIO()
        call_command("ratelimit_cleanup", stdout=out)
        output = out.getvalue()

        # Should handle empty database gracefully
        assert "Total:" in output or "0 records" in output.lower()


@pytest.mark.django_db
class TestRatelimitCleanupLargeDataset:
    """Tests with larger datasets."""

    def test_large_dataset_cleanup(self, db):
        """Test cleanup with 1000+ records."""
        from django_smart_ratelimit.models import RateLimitCounter, RateLimitEntry

        now = timezone.now()

        # Create 500 expired counters
        counters = [
            RateLimitCounter(
                key=f"large:counter:{i}",
                count=1,
                window_start=now - timedelta(hours=2),
                window_end=now - timedelta(hours=1),
            )
            for i in range(500)
        ]
        RateLimitCounter.objects.bulk_create(counters)

        # Create 500 expired entries
        entries = [
            RateLimitEntry(
                key=f"large:entry:{i}",
                timestamp=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            )
            for i in range(500)
        ]
        RateLimitEntry.objects.bulk_create(entries)

        # Create 100 active records to keep
        active_counters = [
            RateLimitCounter(
                key=f"active:counter:{i}",
                count=1,
                window_start=now,
                window_end=now + timedelta(hours=1),
            )
            for i in range(100)
        ]
        RateLimitCounter.objects.bulk_create(active_counters)

        out = StringIO()
        call_command("ratelimit_cleanup", "--batch-size=100", stdout=out)

        # All expired should be deleted, active should remain
        assert RateLimitCounter.objects.count() == 100
        assert RateLimitEntry.objects.count() == 0
        assert RateLimitCounter.objects.filter(key__startswith="active:").count() == 100


@pytest.mark.django_db
class TestRatelimitCleanupMixedState:
    """Tests with mixed expired and active records."""

    def test_mixed_state_cleanup(
        self,
        expired_counters,
        active_counters,
        expired_entries,
        active_entries,
        stale_buckets,
        active_buckets,
    ):
        """Test cleanup with a mix of expired and active records."""
        from django_smart_ratelimit.models import (
            RateLimitCounter,
            RateLimitEntry,
            RateLimitTokenBucket,
        )

        # Verify initial state
        assert RateLimitCounter.objects.count() == 8
        assert RateLimitEntry.objects.count() == 11
        assert RateLimitTokenBucket.objects.count() == 6

        out = StringIO()
        call_command("ratelimit_cleanup", "--json", stdout=out)
        data = json.loads(out.getvalue())

        # Check correct records were deleted
        assert data["counters"]["deleted"] == 5
        assert data["entries"]["deleted"] == 7
        assert data["token_buckets"]["deleted"] == 4

        # Verify only active records remain
        assert RateLimitCounter.objects.count() == 3
        assert RateLimitEntry.objects.count() == 4
        assert RateLimitTokenBucket.objects.count() == 2
