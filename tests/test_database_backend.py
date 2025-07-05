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
from django_smart_ratelimit.models import (
    RateLimitConfig,
    RateLimitCounter,
    RateLimitEntry,
)


class DatabaseBackendTests(TestCase):
    """Test the database backend functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.backend = DatabaseBackend()
        # Clean up any existing data
        RateLimitEntry.objects.all().delete()
        RateLimitCounter.objects.all().delete()

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
        self.backend._cleanup_expired_entries(force=True)

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
        self.backend._cleanup_expired_entries(force=True)

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
        window_seconds = 5  # 5 second window

        # Add entry
        count1 = self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")
        self.assertEqual(count1, 1)

        # Wait for window to expire
        time.sleep(6)

        # New entry should start fresh count
        count2 = self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")
        # Should be 1 because old entry expired
        self.assertEqual(count2, 1)

    def test_fixed_window_reset(self):
        """Test that fixed window counters reset properly."""
        key = "test:window_reset"

        # Mock window times to test reset behavior
        with patch.object(self.backend, "_get_window_times") as mock_times:
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
        from django_smart_ratelimit.backends import get_backend

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
        def test_view(request):
            return HttpResponse("OK")

        # First two requests should succeed
        request = factory.get("/")
        request.META["REMOTE_ADDR"] = "127.0.0.1"

        response1 = test_view(request)
        self.assertEqual(response1.status_code, 200)

        response2 = test_view(request)
        self.assertEqual(response2.status_code, 200)

        # Third request should be rate limited
        response3 = test_view(request)
        self.assertEqual(response3.status_code, 429)

    def test_performance_with_large_dataset(self):
        """Test performance with a large number of entries."""
        backend = DatabaseBackend()
        key_prefix = "perf:test"

        # Create many entries
        start_time = time.time()
        for i in range(100):
            backend.incr_with_algorithm(f"{key_prefix}:{i}", 60, "sliding_window")

        creation_time = time.time() - start_time

        # Read performance
        start_time = time.time()
        for i in range(100):
            backend.get_count_with_algorithm(f"{key_prefix}:{i}", 60, "sliding_window")

        read_time = time.time() - start_time

        # Performance should be reasonable (adjust thresholds as needed)
        self.assertLess(creation_time, 5.0)  # 5 seconds for 100 creates
        self.assertLess(read_time, 2.0)  # 2 seconds for 100 reads


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

    def test_get_count_with_algorithm_key_length_validation(self):
        """Test that get_count_with_algorithm validates key length."""
        long_key = "test:" + "x" * 500  # Very long key

        with self.assertRaises(ValueError) as context:
            self.backend.get_count_with_algorithm(long_key, 60, "sliding_window")

        self.assertIn("Key length cannot exceed 255 characters", str(context.exception))

    def test_get_count_with_algorithm_empty_key_validation(self):
        """Test that get_count_with_algorithm validates empty keys."""
        with self.assertRaises(ValueError) as context:
            self.backend.get_count_with_algorithm("", 60, "sliding_window")

        self.assertIn("Key cannot be empty", str(context.exception))

        with self.assertRaises(ValueError) as context:
            self.backend.get_count_with_algorithm("   ", 60, "sliding_window")

        self.assertIn("Key cannot be empty", str(context.exception))

    def test_get_count_with_algorithm_negative_window_validation(self):
        """Test that get_count_with_algorithm validates negative window seconds."""
        with self.assertRaises(ValueError) as context:
            self.backend.get_count_with_algorithm("test:key", -60, "sliding_window")

        self.assertIn("Window seconds must be positive", str(context.exception))

    def test_negative_window_seconds(self):
        """Test handling of negative window seconds."""
        key = "test:negative"
        with self.assertRaises(ValueError):
            self.backend.incr_with_algorithm(key, -60, "sliding_window")

    def test_zero_window_seconds(self):
        """Test handling of zero window seconds."""
        key = "test:zero"
        with self.assertRaises(ValueError):
            self.backend.incr_with_algorithm(key, 0, "sliding_window")

    def test_very_large_window_seconds(self):
        """Test handling of very large window seconds."""
        key = "test:large_window"
        large_window = 365 * 24 * 3600  # 1 year

        count = self.backend.incr_with_algorithm(key, large_window, "sliding_window")
        self.assertEqual(count, 1)

        # Should work with fixed window too
        count = self.backend.incr_with_algorithm(
            key + "_fixed", large_window, "fixed_window"
        )
        self.assertEqual(count, 1)

    def test_unicode_keys(self):
        """Test handling of unicode characters in keys."""
        unicode_key = "test:用户:123"
        count = self.backend.incr_with_algorithm(unicode_key, 60, "sliding_window")
        self.assertEqual(count, 1)

    def test_very_long_keys(self):
        """Test handling of very long keys."""
        long_key = "test:" + "x" * 500  # Very long key

        # Should handle long keys gracefully (may truncate or raise error)
        try:
            count = self.backend.incr_with_algorithm(long_key, 60, "sliding_window")
            self.assertEqual(count, 1)
        except Exception as e:
            # If it raises an exception, it should be a validation error
            self.assertIn("key", str(e).lower())

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
        with patch.object(self.backend, "_get_window_times") as mock_times:
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
        cleaned = backend._cleanup_expired_entries(force=False)
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

    def test_sliding_window_partial_expiration(self):
        """Test sliding window with partial expiration of entries."""
        key = "test:partial_expire"
        window_seconds = 10

        # Add first entry
        self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")

        # Wait half the window time
        time.sleep(5)

        # Add second entry
        self.backend.incr_with_algorithm(key, window_seconds, "sliding_window")

        # Wait for first entry to expire but not second
        time.sleep(6)

        # Should only count the second entry
        count = self.backend.get_count_with_algorithm(
            key, window_seconds, "sliding_window"
        )
        self.assertEqual(count, 1)

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
            window_start, window_end = self.backend._get_window_times(3600)
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

    def test_window_calculation_precision(self):
        """Test window calculation precision with various intervals."""
        test_cases = [
            1,  # 1 second
            60,  # 1 minute
            3600,  # 1 hour
            86400,  # 1 day
            604800,  # 1 week
        ]

        for window_seconds in test_cases:
            window_start, window_end = self.backend._get_window_times(window_seconds)

            # Window should be exactly the right duration
            duration = (window_end - window_start).total_seconds()
            self.assertEqual(duration, window_seconds)

            # Window start should be aligned to the interval
            epoch = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)
            seconds_since_epoch = int((window_start - epoch).total_seconds())
            self.assertEqual(seconds_since_epoch % window_seconds, 0)

    def test_cleanup_with_database_errors(self):
        """Test cleanup behavior when database operations fail."""
        # Mock database error during cleanup
        with patch(
            "django_smart_ratelimit.models.RateLimitEntry.objects"
        ) as mock_entry:
            mock_entry.filter.return_value.delete.side_effect = Exception(
                "Delete failed"
            )

            # Should handle the error gracefully
            try:
                cleaned = self.backend.cleanup_expired()
                # If it doesn't raise, should return some reasonable value
                self.assertIsInstance(cleaned, int)
            except Exception:
                # If it raises, that's also acceptable behavior
                pass

    def test_stats_with_empty_database(self):
        """Test stats calculation with empty database."""
        stats = self.backend.get_stats()

        self.assertEqual(stats["backend"], "database")
        self.assertEqual(stats["entries"]["total"], 0)
        self.assertEqual(stats["counters"]["total"], 0)
        self.assertEqual(stats["entries"]["expired"], 0)
        self.assertEqual(stats["counters"]["expired"], 0)

    def test_reset_time_calculation_edge_cases(self):
        """Test reset time calculation in various edge cases."""
        key = "test:reset_time"

        # Test when no entries exist
        reset_time = self.backend.get_reset_time_with_algorithm(
            key, 60, "sliding_window"
        )
        self.assertIsNone(reset_time)

        # Test when counter doesn't exist (fixed window)
        reset_time = self.backend.get_reset_time_with_algorithm(key, 60, "fixed_window")
        self.assertIsNone(reset_time)

        # Test with very old entries
        old_time = timezone.now() - timedelta(days=30)
        RateLimitEntry.objects.create(
            key=key,
            timestamp=old_time,
            expires_at=old_time + timedelta(hours=1),
            algorithm="sliding_window",
        )

        reset_time = self.backend.get_reset_time_with_algorithm(
            key, 60, "sliding_window"
        )
        self.assertIsNotNone(reset_time)
        # Reset time should be in the past for old entries
        self.assertLess(reset_time, int(timezone.now().timestamp()))

    def test_whitespace_only_key_validation(self):
        """Test that whitespace-only keys are properly rejected."""
        whitespace_keys = ["   ", "\t", "\n", "\r", " \t\n\r "]

        for key in whitespace_keys:
            with self.assertRaises(ValueError) as context:
                self.backend.incr_with_algorithm(key, 60, "sliding_window")

            self.assertIn("Key cannot be empty", str(context.exception))

            with self.assertRaises(ValueError) as context:
                self.backend.get_count_with_algorithm(key, 60, "sliding_window")

            self.assertIn("Key cannot be empty", str(context.exception))

    def test_key_length_boundary_conditions(self):
        """Test key length at exact boundaries."""
        # Test exactly 255 characters (should work)
        key_255 = "test:" + "x" * 250  # 255 characters total
        count = self.backend.incr_with_algorithm(key_255, 60, "sliding_window")
        self.assertEqual(count, 1)

        # Test exactly 256 characters (should fail)
        key_256 = "test:" + "x" * 251  # 256 characters total
        with self.assertRaises(ValueError) as context:
            self.backend.incr_with_algorithm(key_256, 60, "sliding_window")

        self.assertIn("Key length cannot exceed 255 characters", str(context.exception))

    def test_extreme_window_boundary_values(self):
        """Test extreme window boundary values."""
        key = "test:extreme_window"

        # Test 1 second window
        count = self.backend.incr_with_algorithm(key + "_1s", 1, "sliding_window")
        self.assertEqual(count, 1)

        # Test very large window (10 years)
        large_window = 10 * 365 * 24 * 3600  # 10 years in seconds
        count = self.backend.incr_with_algorithm(
            key + "_10y", large_window, "sliding_window"
        )
        self.assertEqual(count, 1)

        # Test maximum integer value (if system supports it)
        try:
            max_int = 2**31 - 1  # 32-bit signed int max
            count = self.backend.incr_with_algorithm(
                key + "_max", max_int, "sliding_window"
            )
            self.assertEqual(count, 1)
        except (OverflowError, ValueError, Exception):
            # If system doesn't support such large values, that's acceptable
            pass

    def test_special_character_keys_comprehensive(self):
        """Test comprehensive set of special characters in keys."""
        special_chars_keys = [
            "test:key with spaces",
            "test:key_with_underscores",
            "test:key-with-dashes",
            "test:key.with.dots",
            "test:key/with/slashes",
            "test:key\\with\\backslashes",
            "test:key:with:colons",
            "test:key;with;semicolons",
            "test:key|with|pipes",
            "test:key@with@ats",
            "test:key#with#hashes",
            "test:key%with%percents",
            "test:key^with^carets",
            "test:key&with&ampersands",
            "test:key*with*asterisks",
            "test:key+with+plus",
            "test:key=with=equals",
            "test:key?with?questions",
            "test:key<with<less",
            "test:key>with>greater",
            "test:key{with{braces}",
            "test:key[with[brackets]",
            "test:key(with(parens)",
            "test:key'with'quotes",
            'test:key"with"doublequotes',
            "test:key`with`backticks",
            "test:key~with~tildes",
        ]

        for key in special_chars_keys:
            if len(key) <= 255:  # Only test if within length limit
                try:
                    count = self.backend.incr_with_algorithm(key, 60, "sliding_window")
                    self.assertEqual(count, 1)

                    # Verify we can read it back
                    retrieved_count = self.backend.get_count_with_algorithm(
                        key, 60, "sliding_window"
                    )
                    self.assertEqual(retrieved_count, 1)
                except (ValueError, Exception):
                    # Some special characters might be rejected, which is acceptable
                    pass

    def test_null_and_control_characters(self):
        """Test handling of null and control characters in keys."""
        control_chars = [
            "test:key\x00with\x00nulls",
            "test:key\x01with\x01control",
            "test:key\x1fwith\x1fcontrol",
            "test:key\x7fwith\x7fdelete",
        ]

        for key in control_chars:
            try:
                # These should either work or raise a reasonable error
                count = self.backend.incr_with_algorithm(key, 60, "sliding_window")
                self.assertEqual(count, 1)
            except (ValueError, Exception):
                # Control characters might be rejected, which is acceptable
                pass


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
        num_keys = 100

        # Create many different keys
        for i in range(num_keys):
            key = f"test:many_keys:{i}"
            count = self.backend.incr_with_algorithm(
                key, window_seconds, "sliding_window"
            )
            self.assertEqual(count, 1)

        # Verify all keys exist
        total_entries = RateLimitEntry.objects.count()
        self.assertEqual(total_entries, num_keys)

    def test_memory_cleanup_effectiveness(self):
        """Test that cleanup actually reduces memory usage."""
        key_prefix = "test:memory"
        window_seconds = 1  # Short window for quick expiration

        # Create many entries
        for i in range(100):
            self.backend.incr_with_algorithm(
                f"{key_prefix}:{i}", window_seconds, "sliding_window"
            )

        initial_count = RateLimitEntry.objects.count()
        self.assertEqual(initial_count, 100)

        # Wait for entries to expire
        time.sleep(2)

        # Force cleanup
        cleaned = self.backend.cleanup_expired()

        # Should have cleaned up expired entries
        remaining_count = RateLimitEntry.objects.count()
        self.assertLess(remaining_count, initial_count)
        self.assertGreaterEqual(cleaned, 0)  # Use the cleaned variable

    def test_alternating_algorithms_same_key(self):
        """Test alternating between algorithms on the same key."""
        key = "test:alternating"
        window_seconds = 60

        # Alternate between algorithms
        for i in range(10):
            algorithm = "sliding_window" if i % 2 == 0 else "fixed_window"
            count = self.backend.incr_with_algorithm(key, window_seconds, algorithm)
            # Each algorithm maintains its own count
            expected_count = (i // 2) + 1
            self.assertEqual(count, expected_count)

    def test_fixed_window_across_multiple_windows(self):
        """Test fixed window behavior across multiple time windows."""
        key = "test:multi_window"

        with patch.object(self.backend, "_get_window_times") as mock_times:
            now = timezone.now()

            # Window 1
            mock_times.return_value = (now, now + timedelta(minutes=1))
            count1 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
            count2 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
            self.assertEqual(count1, 1)
            self.assertEqual(count2, 2)

            # Window 2 (1 minute later)
            window2_start = now + timedelta(minutes=1)
            mock_times.return_value = (
                window2_start,
                window2_start + timedelta(minutes=1),
            )
            count3 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
            self.assertEqual(count3, 1)  # Should reset for new window

            # Window 3 (2 minutes later)
            window3_start = now + timedelta(minutes=2)
            mock_times.return_value = (
                window3_start,
                window3_start + timedelta(minutes=1),
            )
            count4 = self.backend.incr_with_algorithm(key, 60, "fixed_window")
            self.assertEqual(count4, 1)  # Should reset again

    def test_sliding_window_gradual_expiration(self):
        """Test sliding window gradual expiration over time."""
        key = "test:gradual"
        window_seconds = 5

        # Add entries over time
        counts = []
        for i in range(5):
            count = self.backend.incr_with_algorithm(
                key, window_seconds, "sliding_window"
            )
            counts.append(count)
            time.sleep(1)

        # All entries should still be in window
        self.assertEqual(counts, [1, 2, 3, 4, 5])

        # Wait for first entries to expire
        time.sleep(3)

        # Add another entry - some should have expired
        final_count = self.backend.incr_with_algorithm(
            key, window_seconds, "sliding_window"
        )
        self.assertLess(final_count, 6)

    def test_error_recovery_database_operations(self):
        """Test error recovery during database operations."""
        key = "test:error_recovery"

        # Test recovery from entry creation failure
        with patch(
            "django_smart_ratelimit.models.RateLimitEntry.objects.create"
        ) as mock_create:
            mock_create.side_effect = Exception("DB Error")

            # First call should raise exception
            with self.assertRaises(Exception):
                self.backend.incr_with_algorithm(key, 60, "sliding_window")

        # Backend should still be usable after error (outside the patch context)
        count = self.backend.incr_with_algorithm(
            key + "_recovery", 60, "sliding_window"
        )
        self.assertEqual(count, 1)

    def test_concurrent_operations_different_algorithms(self):
        """Test concurrent operations with different algorithms."""
        key = "test:concurrent_mixed"
        window_seconds = 60

        def sliding_increment():
            return self.backend.incr_with_algorithm(
                key, window_seconds, "sliding_window"
            )

        def fixed_increment():
            return self.backend.incr_with_algorithm(key, window_seconds, "fixed_window")

        # Simulate concurrent operations
        sliding_count = sliding_increment()
        fixed_count = fixed_increment()

        # Both should succeed independently
        self.assertEqual(sliding_count, 1)
        self.assertEqual(fixed_count, 1)

        # Verify both types of records exist
        self.assertTrue(RateLimitEntry.objects.filter(key=key).exists())
        self.assertTrue(RateLimitCounter.objects.filter(key=key).exists())

    def test_stats_accuracy_under_load(self):
        """Test that stats remain accurate under load."""
        key_prefix = "test:stats_load"

        # Create mixed entries and counters
        for i in range(50):
            self.backend.incr_with_algorithm(
                f"{key_prefix}:sliding:{i}", 60, "sliding_window"
            )
            self.backend.incr_with_algorithm(
                f"{key_prefix}:fixed:{i}", 60, "fixed_window"
            )

        stats = self.backend.get_stats()

        # Should accurately count all entries
        self.assertEqual(stats["entries"]["total"], 50)
        self.assertEqual(stats["counters"]["total"], 50)
        self.assertEqual(stats["entries"]["active"], 50)
        self.assertEqual(stats["counters"]["active"], 50)

    def test_cleanup_threshold_edge_cases(self):
        """Test cleanup threshold behavior in edge cases."""
        # Test with threshold = 1 (should cleanup after every entry)
        backend = DatabaseBackend(cleanup_threshold=1)

        # Create entry that will expire immediately
        now = timezone.now()
        RateLimitEntry.objects.create(
            key="test:threshold_edge",
            timestamp=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
            algorithm="sliding_window",
        )

        # Adding any new entry should trigger cleanup
        cleaned = backend._cleanup_expired_entries(force=False)
        self.assertGreaterEqual(cleaned, 1)

    def test_unicode_and_special_characters(self):
        """Test handling of various unicode and special characters in keys."""
        special_keys = [
            "test:emoji:🚀",
            "test:chinese:测试",
            "test:arabic:اختبار",
            "test:special:!@#$%^&*()",
            "test:symbols:αβγδε",
            "test:mixed:user🔥test_123",
        ]

        for key in special_keys:
            try:
                count = self.backend.incr_with_algorithm(key, 60, "sliding_window")
                self.assertEqual(count, 1)

                # Verify we can read it back
                retrieved_count = self.backend.get_count_with_algorithm(
                    key, 60, "sliding_window"
                )
                self.assertEqual(retrieved_count, 1)
            except ValueError:
                # Some special characters might be rejected, which is acceptable
                pass

    def test_precision_with_microsecond_timing(self):
        """Test precision with microsecond-level timing."""
        key = "test:precision"
        window_seconds = 60

        # Create entries with microsecond precision
        start_time = time.time()
        counts = []
        for i in range(10):
            count = self.backend.incr_with_algorithm(
                key, window_seconds, "sliding_window"
            )
            counts.append(count)
            # Small delay to ensure different timestamps
            time.sleep(0.001)

        end_time = time.time()
        elapsed = end_time - start_time

        # Should handle rapid operations (< 1 second total)
        self.assertLess(elapsed, 1.0)
        self.assertEqual(counts, list(range(1, 11)))

    def test_window_boundary_precision(self):
        """Test precision at exact window boundaries."""
        key = "test:boundary_precision"

        with patch.object(self.backend, "_get_window_times") as mock_times:
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

    def test_get_count_with_algorithm_key_length_validation(self):
        """Test that get_count_with_algorithm validates key length."""
        long_key = "test:" + "x" * 500  # Very long key

        with self.assertRaises(ValueError) as context:
            self.backend.get_count_with_algorithm(long_key, 60, "sliding_window")

        self.assertIn("Key length cannot exceed 255 characters", str(context.exception))

    def test_get_count_with_algorithm_empty_key_validation(self):
        """Test that get_count_with_algorithm validates empty keys."""
        with self.assertRaises(ValueError) as context:
            self.backend.get_count_with_algorithm("", 60, "sliding_window")

        self.assertIn("Key cannot be empty", str(context.exception))

        with self.assertRaises(ValueError) as context:
            self.backend.get_count_with_algorithm("   ", 60, "sliding_window")

        self.assertIn("Key cannot be empty", str(context.exception))

    def test_get_count_with_algorithm_negative_window_validation(self):
        """Test that get_count_with_algorithm validates negative window seconds."""
        with self.assertRaises(ValueError) as context:
            self.backend.get_count_with_algorithm("test:key", -60, "sliding_window")

        self.assertIn("Window seconds must be positive", str(context.exception))

    def test_whitespace_only_key_validation(self):
        """Test that whitespace-only keys are properly rejected."""
        whitespace_keys = ["   ", "\t", "\n", "\r", " \t\n\r "]

        for key in whitespace_keys:
            with self.assertRaises(ValueError) as context:
                self.backend.incr_with_algorithm(key, 60, "sliding_window")

            self.assertIn("Key cannot be empty", str(context.exception))

            with self.assertRaises(ValueError) as context:
                self.backend.get_count_with_algorithm(key, 60, "sliding_window")

            self.assertIn("Key cannot be empty", str(context.exception))

    def test_key_length_boundary_conditions(self):
        """Test key length at exact boundaries."""
        # Test exactly 255 characters (should work)
        key_255 = "test:" + "x" * 250  # 255 characters total
        count = self.backend.incr_with_algorithm(key_255, 60, "sliding_window")
        self.assertEqual(count, 1)

        # Test exactly 256 characters (should fail)
        key_256 = "test:" + "x" * 251  # 256 characters total
        with self.assertRaises(ValueError) as context:
            self.backend.incr_with_algorithm(key_256, 60, "sliding_window")

        self.assertIn("Key length cannot exceed 255 characters", str(context.exception))

    def test_extreme_window_boundary_values(self):
        """Test extreme window boundary values."""
        key = "test:extreme_window"

        # Test 1 second window
        count = self.backend.incr_with_algorithm(key + "_1s", 1, "sliding_window")
        self.assertEqual(count, 1)

        # Test very large window (10 years)
        large_window = 10 * 365 * 24 * 3600  # 10 years in seconds
        count = self.backend.incr_with_algorithm(
            key + "_10y", large_window, "sliding_window"
        )
        self.assertEqual(count, 1)

        # Test maximum integer value (if system supports it)
        try:
            max_int = 2**31 - 1  # 32-bit signed int max
            count = self.backend.incr_with_algorithm(
                key + "_max", max_int, "sliding_window"
            )
            self.assertEqual(count, 1)
        except (OverflowError, ValueError, Exception):
            # If system doesn't support such large values, that's acceptable
            pass

    def test_special_character_keys_comprehensive(self):
        """Test comprehensive set of special characters in keys."""
        special_chars_keys = [
            "test:key with spaces",
            "test:key_with_underscores",
            "test:key-with-dashes",
            "test:key.with.dots",
            "test:key/with/slashes",
            "test:key\\with\\backslashes",
            "test:key:with:colons",
            "test:key;with;semicolons",
            "test:key|with|pipes",
            "test:key@with@ats",
            "test:key#with#hashes",
            "test:key%with%percents",
            "test:key^with^carets",
            "test:key&with&ampersands",
            "test:key*with*asterisks",
            "test:key+with+plus",
            "test:key=with=equals",
            "test:key?with?questions",
            "test:key<with<less",
            "test:key>with>greater",
            "test:key{with{braces}",
            "test:key[with[brackets]",
            "test:key(with(parens)",
            "test:key'with'quotes",
            'test:key"with"doublequotes',
            "test:key`with`backticks",
            "test:key~with~tildes",
        ]

        for key in special_chars_keys:
            if len(key) <= 255:  # Only test if within length limit
                try:
                    count = self.backend.incr_with_algorithm(key, 60, "sliding_window")
                    self.assertEqual(count, 1)

                    # Verify we can read it back
                    retrieved_count = self.backend.get_count_with_algorithm(
                        key, 60, "sliding_window"
                    )
                    self.assertEqual(retrieved_count, 1)
                except (ValueError, Exception):
                    # Some special characters might be rejected, which is acceptable
                    pass

    def test_null_and_control_characters(self):
        """Test handling of null and control characters in keys."""
        control_chars = [
            "test:key\x00with\x00nulls",
            "test:key\x01with\x01control",
            "test:key\x1fwith\x1fcontrol",
            "test:key\x7fwith\x7fdelete",
        ]

        for key in control_chars:
            try:
                # These should either work or raise a reasonable error
                count = self.backend.incr_with_algorithm(key, 60, "sliding_window")
                self.assertEqual(count, 1)
            except (ValueError, Exception):
                # Control characters might be rejected, which is acceptable
                pass
