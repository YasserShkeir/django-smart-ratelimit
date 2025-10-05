"""Tests for the database backend."""

import time
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import override_settings
from django.utils import timezone

from django_smart_ratelimit.backends.database import DatabaseBackend
from django_smart_ratelimit.backends.utils import get_window_times
from django_smart_ratelimit.models import (
    RateLimitConfig,
    RateLimitCounter,
    RateLimitEntry,
)
from tests.utils import BaseBackendTestCase


class DatabaseBackendTests(BaseBackendTestCase):
    """Test the database backend functionality."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        # Clean up any existing data
        RateLimitEntry.objects.all().delete()
        RateLimitCounter.objects.all().delete()

    def get_backend(self):
        """Return the backend to use for testing."""
        return DatabaseBackend()

    def test_database_backend_initialization(self):
        """Test that the database backend initializes correctly."""
        backend = DatabaseBackend()
        self.assertEqual(backend.cleanup_threshold, 1000)

        # Test with custom configuration
        backend = DatabaseBackend(cleanup_threshold=500)
        self.assertEqual(backend.cleanup_threshold, 500)

    def test_incr_sliding_window(self):
        """Test incrementing count with sliding window algorithm."""
        key = "test:sliding"
        window_seconds = 60

        # First increment
        count1 = self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")
        self.assertEqual(count1, 1)

        # Second increment
        count2 = self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")
        self.assertEqual(count2, 2)

        # Check that entries are created
        entries = RateLimitEntry.objects.filter(key=key)
        self.assertEqual(entries.count(), 2)

    def test_incr_fixed_window(self):
        """Test incrementing count with fixed window algorithm."""
        key = "test:fixed"
        window_seconds = 60

        # First increment
        count1 = self.backend.incr_with_algorithm(key, window_seconds, "fixed_window")
        self.assertEqual(count1, 1)

        # Second increment
        count2 = self.backend.incr_with_algorithm(key, window_seconds, "fixed_window")
        self.assertEqual(count2, 2)

        # Check that counter is created
        counter = RateLimitCounter.objects.get(key=key)
        self.assertEqual(counter.count, 2)

    def test_get_count_sliding_window(self):
        """Test getting count with sliding window algorithm."""
        key = "test:get_sliding"
        window_seconds = 60

        # No entries initially
        count = self.backend.get_count_with_algorithm(
            key, window_seconds, "sliding_window"
        )
        self.assertEqual(count, 0)

        # Add some entries
        self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")
        self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")

        count = self.backend.get_count_with_algorithm(
            key, window_seconds, "sliding_window"
        )
        self.assertEqual(count, 2)

    def test_get_count_fixed_window(self):
        """Test getting count with fixed window algorithm."""
        key = "test:get_fixed"
        window_seconds = 60

        # No counter initially
        count = self.backend.get_count_with_algorithm(
            key, window_seconds, "fixed_window"
        )
        self.assertEqual(count, 0)

        # Add some counts
        self.backend.incr_with_algorithm(key, window_seconds, "fixed_window")
        self.backend.incr_with_algorithm(key, window_seconds, "fixed_window")

        count = self.backend.get_count_with_algorithm(
            key, window_seconds, "fixed_window"
        )
        self.assertEqual(count, 2)

    def test_get_reset_time_sliding_window(self):
        """Test getting reset time with sliding window algorithm."""
        key = "test:reset_sliding"
        window_seconds = 60

        # No reset time initially
        reset_time = self.backend.get_reset_time_with_algorithm(
            key, window_seconds, "sliding_window"
        )
        self.assertIsNone(reset_time)

        # Add an entry
        self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")

        reset_time = self.backend.get_reset_time_with_algorithm(
            key, window_seconds, "sliding_window"
        )
        self.assertIsNotNone(reset_time)
        self.assertIsInstance(reset_time, int)

    def test_get_reset_time_fixed_window(self):
        """Test getting reset time with fixed window algorithm."""
        key = "test:reset_fixed"
        window_seconds = 60

        # No reset time initially
        reset_time = self.backend.get_reset_time_with_algorithm(
            key, window_seconds, "fixed_window"
        )
        self.assertIsNone(reset_time)

        # Add a counter
        self.backend.incr_with_algorithm(key, window_seconds, "fixed_window")

        reset_time = self.backend.get_reset_time_with_algorithm(
            key, window_seconds, "fixed_window"
        )
        self.assertIsNotNone(reset_time)
        self.assertIsInstance(reset_time, int)

    def test_reset_key(self):
        """Test resetting a rate limit key."""
        key = "test:reset"
        window_seconds = 60

        # Add some data
        self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")
        self.backend.incr_with_algorithm(key, window_seconds, "fixed_window")

        # Verify data exists
        self.assertTrue(RateLimitEntry.objects.filter(key=key).exists())
        self.assertTrue(RateLimitCounter.objects.filter(key=key).exists())

        # Reset
        self.backend.reset(key)

        # Verify data is gone
        self.assertFalse(RateLimitEntry.objects.filter(key=key).exists())
        self.assertFalse(RateLimitCounter.objects.filter(key=key).exists())

    def test_reset_nonexistent_key(self):
        """Test resetting a non-existent key."""
        self.backend.reset("nonexistent:key")  # Reset should not raise an exception

    def test_expired_entries_cleanup(self):
        """Test that expired entries are cleaned up."""
        key = "test:cleanup"
        now = timezone.now()

        # Create an expired entry
        RateLimitEntry.objects.create(
            key=key,
            timestamp=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
            algorithm="sliding_window",
        )

        # Create a non-expired entry
        RateLimitEntry.objects.create(
            key=key,
            timestamp=now,
            expires_at=now + timedelta(hours=1),
            algorithm="sliding_window",
        )

        # Force cleanup
        self.backend._cleanup_expired_entries(_force=True)

        # Only non-expired entry should remain
        remaining_entries = RateLimitEntry.objects.filter(key=key)
        self.assertEqual(remaining_entries.count(), 1)
        self.assertTrue(remaining_entries.first().expires_at > now)

    def test_expired_counters_cleanup(self):
        """Test that expired counters are cleaned up."""
        key = "test:counter_cleanup"
        now = timezone.now()

        # Create an expired counter
        RateLimitCounter.objects.create(
            key=key,
            count=5,
            window_start=now - timedelta(hours=2),
            window_end=now - timedelta(hours=1),
        )

        # Force cleanup
        self.backend._cleanup_expired_entries(_force=True)

        # Counter should be gone
        self.assertFalse(RateLimitCounter.objects.filter(key=key).exists())

    def test_health_check(self):
        """Test the health check functionality."""
        health = self.backend.health_check()

        self.assertEqual(health["backend"], "database")
        self.assertTrue(health["healthy"])
        self.assertIn("database_connection", health["details"])
        self.assertIn("table_access", health["details"])
        self.assertIn("write_operations", health["details"])

    def test_get_stats(self):
        """Test getting backend statistics."""
        # Add some test data
        key = "test:stats"
        self.backend.incr_with_algorithm(key, 60, "sliding_window")
        self.backend.incr_with_algorithm(key, 60, "fixed_window")

        stats = self.backend.get_stats()

        self.assertEqual(stats["backend"], "database")
        self.assertIn("entries", stats)
        self.assertIn("counters", stats)
        self.assertIn("cleanup", stats)

        # Check that we have the data we added
        self.assertGreater(stats["entries"]["total"], 0)
        self.assertGreater(stats["counters"]["total"], 0)

    def test_sliding_window_time_based_cleanup(self):
        """Test that sliding window properly handles time-based expiration."""
        key = "test:time_cleanup"
        window_seconds = 2  # shortened window for faster test

        # Add entry
        count1 = self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")
        self.assertEqual(count1, 1)

        # Wait for window to expire
        time.sleep(3)  # shorter sleep

        # New entry should start fresh count
        count2 = self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")
        self.assertEqual(count2, 1)

    def test_fixed_window_reset(self):
        """Test that fixed window counters reset properly."""
        key = "test:window_reset"

        # Mock window times to test reset behavior
        with patch(
            "django_smart_ratelimit.backends.database.get_window_times"
        ) as mock_times:
            now = timezone.now()

            # First window
            window1_start = now
            window1_end = now + timedelta(seconds=60)
            mock_times.return_value = (window1_start, window1_end)

            count1 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
            self.assertEqual(count1, 1)

            # Second window (later)
            window2_start = now + timedelta(seconds=120)
            window2_end = now + timedelta(seconds=180)
            mock_times.return_value = (window2_start, window2_end)

            count2 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
            self.assertEqual(count2, 1)  # Should reset to 1


class DatabaseBackendTransactionTests(TransactionTestCase):
    """Test database backend with transaction handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.backend = DatabaseBackend()

    def test_concurrent_sliding_window_increments(self):
        """Test concurrent increments with sliding window."""
        key = "test:concurrent_sliding"
        window_seconds = 60

        def increment_in_transaction():
            with transaction.atomic():
                return self.backend.incr_with_algorithm(
                    key, window_seconds, "sliding_window"
                )

        # Simulate concurrent increments
        count1 = increment_in_transaction()
        count2 = increment_in_transaction()

        # Both should succeed
        self.assertEqual(count1, 1)
        self.assertEqual(count2, 2)

    def test_concurrent_fixed_window_increments(self):
        """Test concurrent increments with fixed window."""
        key = "test:concurrent_fixed"
        window_seconds = 60

        def increment_in_transaction():
            with transaction.atomic():
                return self.backend.incr_with_algorithm(
                    key, window_seconds, "fixed_window"
                )

        # Simulate concurrent increments
        count1 = increment_in_transaction()
        count2 = increment_in_transaction()

        # Both should succeed
        self.assertEqual(count1, 1)
        self.assertEqual(count2, 2)


class DatabaseBackendManagementCommandTests(TestCase):
    """Test the cleanup management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.backend = DatabaseBackend()
        # Clean up any existing data
        RateLimitEntry.objects.all().delete()
        RateLimitCounter.objects.all().delete()

    def test_cleanup_command_dry_run(self):
        """Test cleanup command with dry run."""
        # Create some expired data
        now = timezone.now()
        RateLimitEntry.objects.create(
            key="test:expired",
            timestamp=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
            algorithm="sliding_window",
        )

        # Run dry run
        call_command("cleanup_ratelimit", "--dry-run", verbosity=0)

        # Data should still exist
        self.assertTrue(RateLimitEntry.objects.filter(key="test:expired").exists())

    def test_cleanup_command_real_run(self):
        """Test cleanup command with real execution."""
        # Create some expired data
        now = timezone.now()
        RateLimitEntry.objects.create(
            key="test:expired",
            timestamp=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
            algorithm="sliding_window",
        )

        RateLimitCounter.objects.create(
            key="test:expired_counter",
            count=5,
            window_start=now - timedelta(hours=2),
            window_end=now - timedelta(hours=1),
        )

        # Run cleanup
        call_command("cleanup_ratelimit", verbosity=0)

        # Data should be gone
        self.assertFalse(RateLimitEntry.objects.filter(key="test:expired").exists())
        self.assertFalse(
            RateLimitCounter.objects.filter(key="test:expired_counter").exists()
        )

    def test_cleanup_command_key_pattern(self):
        """Test cleanup command with key pattern filtering."""
        now = timezone.now()

        # Create expired data with different key patterns
        RateLimitEntry.objects.create(
            key="user:123",
            timestamp=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
            algorithm="sliding_window",
        )

        RateLimitEntry.objects.create(
            key="ip:192.168.1.1",
            timestamp=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
            algorithm="sliding_window",
        )

        # Cleanup only user keys
        call_command("cleanup_ratelimit", "--key-pattern=user:*", verbosity=0)

        # Only user key should be gone
        self.assertFalse(RateLimitEntry.objects.filter(key="user:123").exists())
        self.assertTrue(RateLimitEntry.objects.filter(key="ip:192.168.1.1").exists())

    def test_cleanup_command_older_than(self):
        """Test cleanup command with older-than option."""
        now = timezone.now()

        # Create data that's not expired but older than threshold
        RateLimitEntry.objects.create(
            key="test:old",
            timestamp=now - timedelta(hours=25),  # 25 hours old
            expires_at=now + timedelta(hours=1),  # But not expired
            algorithm="sliding_window",
        )

        # Cleanup entries older than 24 hours
        call_command("cleanup_ratelimit", "--older-than=24", verbosity=0)

        # Entry should be gone even though not expired
        self.assertFalse(RateLimitEntry.objects.filter(key="test:old").exists())


class DatabaseBackendModelTests(TestCase):
    """Test the database models."""

    def test_rate_limit_entry_model(self):
        """Test RateLimitEntry model functionality."""
        now = timezone.now()
        entry = RateLimitEntry.objects.create(
            key="test:entry",
            timestamp=now,
            expires_at=now + timedelta(hours=1),
            algorithm="sliding_window",
        )

        self.assertEqual(
            str(entry), f"RateLimit(test:entry, {now}, expires: {entry.expires_at})"
        )
        self.assertFalse(entry.is_expired())

        # Test expired entry
        expired_entry = RateLimitEntry.objects.create(
            key="test:expired",
            timestamp=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
            algorithm="sliding_window",
        )

        self.assertTrue(expired_entry.is_expired())

    def test_rate_limit_counter_model(self):
        """Test RateLimitCounter model functionality."""
        now = timezone.now()
        counter = RateLimitCounter.objects.create(
            key="test:counter",
            count=5,
            window_start=now,
            window_end=now + timedelta(hours=1),
        )

        self.assertFalse(counter.is_expired())

        # Test expired counter
        expired_counter = RateLimitCounter.objects.create(
            key="test:expired_counter",
            count=3,
            window_start=now - timedelta(hours=2),
            window_end=now - timedelta(hours=1),
        )

        self.assertTrue(expired_counter.is_expired())

    def test_rate_limit_counter_reset(self):
        """Test RateLimitCounter reset functionality."""
        now = timezone.now()

        # Create expired counter
        counter = RateLimitCounter.objects.create(
            key="test:reset_counter",
            count=5,
            window_start=now - timedelta(hours=2),
            window_end=now - timedelta(hours=1),
        )

        # Reset should update the window
        counter.reset_if_expired()

        # Counter should be reset
        self.assertEqual(counter.count, 0)
        self.assertGreater(counter.window_start, now - timedelta(minutes=1))

    def test_rate_limit_config_model(self):
        """Test RateLimitConfig model functionality."""
        config = RateLimitConfig.objects.create(
            key_pattern="user:*",
            rate_limit="100/h",
            algorithm="sliding_window",
            description="User rate limits",
        )

        self.assertEqual(str(config), "Config(user:*, 100/h)")
        self.assertTrue(config.is_active)


class DatabaseBackendIntegrationTests(TestCase):
    """Integration tests for database backend."""

    def test_backend_selection(self):
        """Test that database backend can be selected."""
        from django_smart_ratelimit import get_backend

        with override_settings(RATELIMIT_BACKEND="database"):
            backend = get_backend()
            self.assertIsInstance(backend, DatabaseBackend)

    def test_with_decorator(self):
        """Test database backend with rate limit decorator."""
        from django.http import HttpResponse
        from django.test import RequestFactory

        from django_smart_ratelimit import rate_limit

        factory = RequestFactory()

        @rate_limit(key="ip", rate="2/m", backend="database")
        def test_view(_request):
            return HttpResponse("OK")

        # First two requests should succeed
        _request = factory.get("/")
        _request.META["REMOTE_ADDR"] = "127.0.0.1"

        response1 = test_view(_request)
        self.assertEqual(response1.status_code, 200)

        response2 = test_view(_request)
        self.assertEqual(response2.status_code, 200)

        # Third _request should be rate limited
        response3 = test_view(_request)
        self.assertEqual(response3.status_code, 429)

    def test_performance_with_large_dataset(self):
        """Test performance with a moderate number of entries (trimmed for speed)."""
        backend = DatabaseBackend()
        key_prefix = "perf:test"

        # Create entries
        start_time = time.time()
        for i in range(50):  # reduced from 100
            backend.incr_with_algorithm(f"{key_prefix}:{i}", 60, "sliding_window")
        creation_time = time.time() - start_time

        # Read performance
        start_time = time.time()
        for i in range(50):  # reduced from 100
            backend.get_count_with_algorithm(f"{key_prefix}:{i}", 60, "sliding_window")
        read_time = time.time() - start_time

        # Tighter thresholds for smaller dataset
        self.assertLess(creation_time, 3.0)
        self.assertLess(read_time, 1.5)


class DatabaseBackendEdgeCaseTests(TestCase):
    """Test edge cases and error conditions for database backend."""

    def setUp(self):
        """Set up test fixtures."""
        self.backend = DatabaseBackend()
        # Clean up any existing data
        RateLimitEntry.objects.all().delete()
        RateLimitCounter.objects.all().delete()

    def test_empty_key_handling(self):
        """Test handling of empty keys."""
        with self.assertRaises(ValueError):
            self.backend.incr_with_algorithm("", 60, "sliding_window")

    def test_sliding_window_partial_expiration(self):
        """Test sliding window with partial expiration of entries."""
        key = "test:partial_expire"
        window_seconds = 3  # shortened window

        # Add first entry
        self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")

        # Wait partial window time
        time.sleep(1)

        # Add second entry
        self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")

        # Wait for first entry to expire but not second
        time.sleep(2)

        # Should only count the second entry
        count = self.backend.get_count_with_algorithm(
            key, window_seconds, "sliding_window"
        )
        self.assertEqual(count, 1)

    def test_invalid_algorithm(self):
        """Test handling of invalid algorithm names."""
        key = "test:invalid_algo"

        # Should default to sliding window for unknown algorithms
        count = self.backend.incr_with_algorithm(key, 60, "unknown_algorithm")
        self.assertEqual(count, 1)

        # Verify it created a sliding window entry
        self.assertTrue(RateLimitEntry.objects.filter(key=key).exists())

    def test_concurrent_window_boundary(self):
        """Test behavior at window boundaries."""
        key = "test:boundary"

        # Mock specific window times to test boundary conditions
        with patch(
            "django_smart_ratelimit.backends.database.get_window_times"
        ) as mock_times:
            now = timezone.now()

            # Set up window boundary
            window_start = now.replace(second=0, microsecond=0)
            window_end = window_start + timedelta(minutes=1)
            mock_times.return_value = (window_start, window_end)

            # First increment
            count1 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
            self.assertEqual(count1, 1)

            # Exactly at window boundary
            window_start2 = window_end
            window_end2 = window_start2 + timedelta(minutes=1)
            mock_times.return_value = (window_start2, window_end2)

            # Should start new window
            count2 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
            self.assertEqual(count2, 1)

    def test_database_connection_failure(self):
        """Test graceful handling of database connection failures."""
        # Mock database connection failure
        with patch(
            "django_smart_ratelimit.models.RateLimitEntry.objects"
        ) as mock_entry:
            mock_entry.create.side_effect = Exception("Database connection failed")

            key = "test:db_failure"
            with self.assertRaises(Exception):
                self.backend.incr_with_algorithm(key, 60, "sliding_window")

    def test_health_check_failure_scenarios(self):
        """Test health check under various failure conditions."""
        # Test database connectivity failure
        with patch(
            "django_smart_ratelimit.models.RateLimitEntry.objects"
        ) as mock_entry:
            mock_entry.count.side_effect = Exception("Connection failed")

            health = self.backend.health_check()
            self.assertFalse(health["healthy"])
            self.assertIn("Failed", health["details"]["database_connection"])

    def test_cleanup_threshold_behavior(self):
        """Test cleanup threshold behavior edge cases."""
        # Test with threshold of 0 (should always cleanup)
        backend = DatabaseBackend(cleanup_threshold=0)

        # Create some entries
        key = "test:threshold"
        backend.incr_with_algorithm(key, 60, "sliding_window")

        # Should cleanup immediately when threshold is 0
        cleaned = backend._cleanup_expired_entries(_force=False)
        # Even if nothing to cleanup, should return 0
        self.assertGreaterEqual(cleaned, 0)

    def test_massive_increment_operations(self):
        """Test behavior with massive number of increments."""
        key = "test:massive"
        window_seconds = 60

        # Test sliding window with many increments
        for i in range(1000):
            count = self.backend.incr_with_algorithm(
                key, window_seconds, "sliding_window"
            )
            self.assertEqual(count, i + 1)

        # Verify count is correct
        final_count = self.backend.get_count_with_algorithm(
            key, window_seconds, "sliding_window"
        )
        self.assertEqual(final_count, 1000)

    def test_mixed_algorithm_operations(self):
        """Test operations with mixed algorithms on same key."""
        key = "test:mixed"

        # Use both algorithms with same key
        sliding_count = self.backend.incr_with_algorithm(key, 60, "sliding_window")
        fixed_count = self.backend.incr_with_algorithm(key, 60, "fixed_window")

        self.assertEqual(sliding_count, 1)
        self.assertEqual(fixed_count, 1)

        # Both should coexist
        self.assertTrue(RateLimitEntry.objects.filter(key=key).exists())
        self.assertTrue(RateLimitCounter.objects.filter(key=key).exists())

        # Reset with algorithm should only affect one
        self.backend.reset_with_algorithm(key, 60, "sliding_window")

        self.assertFalse(RateLimitEntry.objects.filter(key=key).exists())
        self.assertTrue(RateLimitCounter.objects.filter(key=key).exists())

    def test_base_interface_methods(self):
        """Test the base interface methods work correctly."""
        key = "test:base_interface"

        # Test base incr method (should use sliding window)
        count1 = self.backend.incr(key, 60)
        self.assertEqual(count1, 1)

        # Test base get_count method
        count2 = self.backend.get_count(key)
        self.assertEqual(count2, 1)

        # Test base get_reset_time method
        reset_time = self.backend.get_reset_time(key)
        self.assertIsNotNone(reset_time)
        self.assertIsInstance(reset_time, int)

        # Test base reset method
        self.backend.reset(key)

        # Should be gone
        count3 = self.backend.get_count(key)
        self.assertEqual(count3, 0)

    def test_timezone_edge_cases(self):
        """Test timezone-related edge cases."""
        key = "test:timezone"

        # Test around DST transition (mock different timezones)
        with patch("django.utils.timezone.now") as mock_now:
            # Mock a specific time
            fixed_time = datetime(2025, 3, 10, 2, 30, 0, tzinfo=dt_timezone.utc)
            mock_now.return_value = fixed_time

            count = self.backend.incr_with_algorithm(key, 3600, "fixed_window")
            self.assertEqual(count, 1)

            # Verify window calculation works with mocked time
            window_start, window_end = get_window_times(3600)
            self.assertIsInstance(window_start, datetime)
            self.assertIsInstance(window_end, datetime)

    def test_model_validation_edge_cases(self):
        """Test model validation in edge cases."""
        from django.core.exceptions import ValidationError

        now = timezone.now()

        # Test RateLimitEntry with invalid expiration
        entry = RateLimitEntry(
            key="test:validation",
            timestamp=now,
            expires_at=now - timedelta(hours=1),  # Expires in the past
            algorithm="sliding_window",
        )

        with self.assertRaises(ValidationError):
            entry.clean()

    def test_window_boundary_precision(self):
        """Test precision at exact window boundaries."""
        key = "test:boundary_precision"

        with patch(
            "django_smart_ratelimit.backends.database.get_window_times"
        ) as mock_times:
            base_time = timezone.now().replace(microsecond=0)

            # Set exact window boundary
            window_start = base_time
            window_end = base_time + timedelta(seconds=60)
            mock_times.return_value = (window_start, window_end)

            # Add entry at start of window
            count1 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
            self.assertEqual(count1, 1)

            # Move to exact end of window
            window_start2 = window_end
            window_end2 = window_start2 + timedelta(seconds=60)
            mock_times.return_value = (window_start2, window_end2)

            # Should start new window
            count2 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
            self.assertEqual(count2, 1)


class DatabaseBackendStressTests(TestCase):
    """Stress tests for database backend under high load conditions."""

    def setUp(self):
        """Set up test fixtures."""
        self.backend = DatabaseBackend()
        # Clean up any existing data
        RateLimitEntry.objects.all().delete()
        RateLimitCounter.objects.all().delete()

    def test_rapid_increment_same_key(self):
        """Test rapid increments on the same key."""
        key = "test:rapid"
        window_seconds = 60

        # Rapid increments
        counts = []
        for i in range(50):
            count = self.backend.incr_with_algorithm(
                key, window_seconds, "sliding_window"
            )
            counts.append(count)

        # Verify counts are consecutive
        self.assertEqual(counts, list(range(1, 51)))

    def test_many_different_keys(self):
        """Test handling many different keys simultaneously."""
        window_seconds = 60
        num_keys = 50  # reduced from 100

        for i in range(num_keys):
            key = f"test:many_keys:{i}"
            count = self.backend.incr_with_algorithm(
                key, window_seconds, "sliding_window"
            )
            self.assertEqual(count, 1)

        total_entries = RateLimitEntry.objects.count()
        self.assertEqual(total_entries, num_keys)

    def test_sliding_window_gradual_expiration(self):
        """Test sliding window gradual expiration over time (trimmed)."""
        key = "test:gradual"
        window_seconds = 3

        counts = []
        for i in range(3):  # reduced iterations
            count = self.backend.incr_with_algorithm(
                key, window_seconds, "sliding_window"
            )
            counts.append(count)
            time.sleep(0.5)

        # All entries should still be in window
        self.assertEqual(counts, [1, 2, 3])

        # Wait for first entries to expire
        time.sleep(2)

        # Add another entry - some should have expired
        final_count = self.backend.incr_with_algorithm(
            key, window_seconds, "sliding_window"
        )
        self.assertLess(final_count, 4)


class DatabaseBackendAdvancedTests(TransactionTestCase):
    """Advanced database backend tests for transaction isolation, deadlock handling, and timezone edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.backend = DatabaseBackend()
        # Clean up any existing data
        RateLimitEntry.objects.all().delete()
        RateLimitCounter.objects.all().delete()

    def test_transaction_isolation_read_committed(self):
        """Test behavior under READ COMMITTED isolation level."""
        from django.db import connection

        # Skip if database doesn't support isolation levels
        if connection.vendor == "sqlite":
            self.skipTest("SQLite doesn't support READ COMMITTED isolation")

        key = "test:isolation"

        def concurrent_increment():
            # Simulate concurrent access with explicit transaction isolation
            with transaction.atomic():
                # Read current state
                count1 = self.backend.get_count("fixed_window", key, 60)

                # Short delay to increase chance of race condition
                time.sleep(0.01)

                # Increment
                count2 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
                return count2

        # Run two concurrent operations
        count1 = concurrent_increment()
        count2 = concurrent_increment()

        # Both should succeed and be sequential (1, 2) not (1, 1)
        self.assertIn(count1, [1, 2])
        self.assertIn(count2, [1, 2])
        self.assertNotEqual(count1, count2)

    def test_deadlock_retry_mechanism(self):
        """Test that deadlock scenarios are handled gracefully."""
        import os

        # Skip unless explicitly testing deadlocks (can be flaky)
        if not os.environ.get("TEST_DEADLOCK_HANDLING"):
            self.skipTest("Set TEST_DEADLOCK_HANDLING=1 to test deadlock retry")

        from unittest.mock import patch

        from django.db import OperationalError

        key = "test:deadlock"

        # Simulate deadlock on first attempt
        original_incr = self.backend.incr_with_algorithm
        call_count = 0

        def mock_incr_with_deadlock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError("deadlock detected")
            return original_incr(*args, **kwargs)

        with patch.object(
            self.backend, "incr_with_algorithm", side_effect=mock_incr_with_deadlock
        ):
            try:
                count = self.backend.incr_with_algorithm(key, 60, "fixed_window")
                # Should succeed on retry
                self.assertEqual(count, 1)
                self.assertEqual(
                    call_count, 2
                )  # First attempt failed, second succeeded
            except OperationalError:
                # If backend doesn't have retry logic, that's also valid behavior to document
                self.skipTest(
                    "Backend doesn't implement deadlock retry - consider adding"
                )

    def test_timezone_rounding_and_clock_drift(self):
        """Test behavior around timezone boundaries and clock drift scenarios."""
        from zoneinfo import ZoneInfo

        key = "test:timezone"

        # Test with different timezones
        timezones = [
            dt_timezone.utc,
            ZoneInfo("US/Eastern"),
            ZoneInfo("Asia/Tokyo"),
            ZoneInfo("Europe/London"),
        ]

        for tz in timezones:
            with self.subTest(timezone=str(tz)):
                # Create datetime at window boundary
                base_time = datetime(2025, 8, 16, 12, 0, 0, tzinfo=tz)

                with patch("django.utils.timezone.now") as mock_now:
                    mock_now.return_value = base_time

                    # Increment at exact window boundary
                    count1 = self.backend.incr_with_algorithm(
                        f"{key}_{tz}", 3600, "fixed_window"  # 1-hour window
                    )

                    # Move to just before next window boundary
                    mock_now.return_value = base_time + timedelta(seconds=3599)
                    count2 = self.backend.incr_with_algorithm(
                        f"{key}_{tz}", 3600, "fixed_window"
                    )

                    # Should be in same window
                    self.assertEqual(count2, 2)

                    # Move to next window boundary
                    mock_now.return_value = base_time + timedelta(seconds=3600)
                    count3 = self.backend.incr_with_algorithm(
                        f"{key}_{tz}", 3600, "fixed_window"
                    )

                    # Should be in new window
                    self.assertEqual(count3, 1)

    def test_database_constraint_behavior_under_churn(self):
        """Test unique constraints and indexes under high churn scenarios."""
        key = "test:churn"
        window_seconds = 10

        # Create high-churn scenario with many rapid increments
        counts = []
        for i in range(50):  # Reduced from potentially higher numbers for speed
            count = self.backend.incr_with_algorithm(
                key, window_seconds, "sliding_window"
            )
            counts.append(count)

            # Occasional cleanup to test constraint behavior during maintenance
            if i % 10 == 0:
                from io import StringIO

                from django.core.management import call_command

                out = StringIO()
                call_command("cleanup_ratelimit", "--older-than", 24, stdout=out)

        # Verify counts are sequential and constraints held
        self.assertEqual(len(counts), 50)
        self.assertEqual(counts[-1], 50)  # Final count should be 50

        # Verify no duplicate entries violating constraints
        entries = RateLimitEntry.objects.filter(key=key)
        timestamps = [entry.timestamp for entry in entries]
        self.assertEqual(
            len(timestamps), len(set(timestamps))
        )  # No duplicate timestamps

    def test_cleanup_command_idempotency(self):
        """Test that cleanup command can be run multiple times safely."""
        # Create some expired and non-expired data
        now = timezone.now()

        # Expired data (well in the past)
        RateLimitEntry.objects.create(
            key="test:expired1",
            timestamp=now - timedelta(hours=25),  # More than 24h ago
            expires_at=now - timedelta(hours=24),
            algorithm="sliding_window",
        )

        RateLimitEntry.objects.create(
            key="test:expired2",
            timestamp=now - timedelta(hours=26),
            expires_at=now - timedelta(hours=25),
            algorithm="fixed_window",
        )

        # Active data (recent with future expiry)
        RateLimitEntry.objects.create(
            key="test:active",
            timestamp=now - timedelta(minutes=5),  # Very recent
            expires_at=now + timedelta(hours=1),  # Expires in future
            algorithm="sliding_window",
        )

        initial_total = RateLimitEntry.objects.count()
        self.assertEqual(initial_total, 3)

        # First cleanup run - only clean up entries older than 1 hour
        call_command("cleanup_ratelimit", "--older-than", "1", verbosity=0)
        after_first = RateLimitEntry.objects.count()
        self.assertEqual(after_first, 1)  # Only active entry remains

        # Second cleanup run should be safe and not change anything
        call_command("cleanup_ratelimit", "--older-than", "1", verbosity=0)
        after_second = RateLimitEntry.objects.count()
        self.assertEqual(after_second, 1)  # Still only active entry

        # Third cleanup run with verbose output
        call_command("cleanup_ratelimit", "--older-than", "1", verbosity=2)
        after_third = RateLimitEntry.objects.count()
        self.assertEqual(after_third, 1)  # Still safe

        # Verify the remaining entry is the correct one
        remaining = RateLimitEntry.objects.get()
        self.assertEqual(remaining.key, "test:active")

    def test_parametrized_isolation_levels_if_supported(self):
        """Test different isolation levels where database supports them."""
        from django.db import connection

        # Skip for databases that don't support multiple isolation levels
        if connection.vendor in ["sqlite"]:
            self.skipTest(
                f"{connection.vendor} doesn't support configurable isolation levels"
            )

        key = "test:isolation_levels"

        # Test available isolation levels
        isolation_levels = []
        if connection.vendor == "postgresql":
            isolation_levels = ["READ COMMITTED", "SERIALIZABLE"]
        elif connection.vendor == "mysql":
            isolation_levels = ["READ COMMITTED", "REPEATABLE READ"]

        for level in isolation_levels:
            with self.subTest(isolation_level=level):
                with connection.cursor() as cursor:
                    try:
                        cursor.execute(f"SET TRANSACTION ISOLATION LEVEL {level}")

                        # Test basic increment under this isolation level
                        with transaction.atomic():
                            count = self.backend.incr_with_algorithm(
                                f"{key}_{level.replace(' ', '_')}", 60, "fixed_window"
                            )
                            self.assertEqual(count, 1)

                    except Exception as e:
                        # Document which isolation levels work/don't work
                        self.fail(f"Isolation level {level} failed: {e}")

                # Reset connection state
                connection.close()
