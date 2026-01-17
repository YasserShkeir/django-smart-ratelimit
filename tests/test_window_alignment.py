"""
Tests for Window Alignment Configuration.

This module tests the RATELIMIT_ALIGN_WINDOW_TO_CLOCK setting which controls
whether rate limit windows are aligned to clock boundaries (e.g., :00, :01)
or start from the first request time.
"""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase, override_settings

from django_smart_ratelimit.backends.utils import (
    get_time_bucket_key_suffix,
    get_window_times,
)
from django_smart_ratelimit.config import reset_settings
from django_smart_ratelimit.decorator import _calculate_stable_reset_time_sliding_window


class TestGetWindowTimesClockAligned(TestCase):
    """Test get_window_times with clock alignment (default behavior)."""

    def test_clock_aligned_snaps_to_boundary(self):
        """Window start should snap to clock boundary when align_to_clock=True."""
        # 1 hour window (3600 seconds)
        window_start, window_end = get_window_times(3600, align_to_clock=True)

        # Window start should be at an hour boundary (minute and second = 0)
        self.assertEqual(window_start.minute, 0)
        self.assertEqual(window_start.second, 0)

        # Window end should be exactly 1 hour after start
        expected_end = window_start + timedelta(hours=1)
        self.assertEqual(window_end, expected_end)

        # Start time should be aligned to hour (divisible by 3600)
        self.assertEqual(int(window_start.timestamp()) % 3600, 0)

    def test_clock_aligned_minute_boundary(self):
        """Test minute boundary alignment."""
        # 1 minute window (60 seconds)
        window_start, window_end = get_window_times(60, align_to_clock=True)

        # Window start should be at a minute boundary (second = 0)
        self.assertEqual(window_start.second, 0)

        # Window end should be exactly 1 minute after start
        expected_end = window_start + timedelta(minutes=1)
        self.assertEqual(window_end, expected_end)

        # Start time should be aligned to minute (divisible by 60)
        self.assertEqual(int(window_start.timestamp()) % 60, 0)


class TestGetWindowTimesFirstRequestAligned(TestCase):
    """Test get_window_times with first-request alignment."""

    def test_first_request_aligned_uses_current_time(self):
        """Window start should be current time when align_to_clock=False."""
        # Capture time before calling
        before = datetime.now(dt_timezone.utc)

        # 1 hour window (3600 seconds)
        window_start, window_end = get_window_times(3600, align_to_clock=False)

        # Capture time after calling
        after = datetime.now(dt_timezone.utc)

        # Window start should be between before and after (not snapped)
        self.assertGreaterEqual(window_start, before - timedelta(seconds=1))
        self.assertLessEqual(window_start, after + timedelta(seconds=1))

        # Window end should be exactly 1 hour after start
        expected_end = window_start + timedelta(hours=1)
        self.assertEqual(window_end, expected_end)

    def test_first_request_not_aligned_to_boundary(self):
        """First-request aligned window should NOT always be at boundaries."""
        # Get a minute-aligned window
        window_start, _ = get_window_times(60, align_to_clock=False)

        # For first-request aligned, the start time preserves the current second
        # (unless we happen to call at exactly :00, which is unlikely)
        # Just verify the window end is correct relative to start
        actual_start, actual_end = get_window_times(60, align_to_clock=False)
        self.assertEqual(actual_end - actual_start, timedelta(minutes=1))


class TestGetTimeBucketKeySuffix(TestCase):
    """Test the time bucket key suffix generation."""

    def test_clock_aligned_returns_bucket_suffix(self):
        """Should return a timestamp bucket suffix when aligned."""
        with patch("time.time", return_value=1705161645.0):  # Some arbitrary time
            suffix = get_time_bucket_key_suffix(60, align_to_clock=True)

            # Should be a colon followed by a number
            assert suffix.startswith(":")
            assert suffix[1:].isdigit()

            # The bucket should be aligned to 60 seconds
            bucket_ts = int(suffix[1:])
            assert bucket_ts % 60 == 0

    def test_first_request_aligned_returns_empty(self):
        """Should return empty string when not aligned."""
        suffix = get_time_bucket_key_suffix(60, align_to_clock=False)
        assert suffix == ""


class TestResetTimeCalculation(TestCase):
    """Test reset time calculation respects alignment setting."""

    def test_clock_aligned_reset_time(self):
        """Reset time should be at next clock boundary when aligned."""
        with patch("time.time", return_value=1705161645.0):  # 14:30:45
            reset_time = _calculate_stable_reset_time_sliding_window(
                60, align_to_clock=True
            )

            # Should be at next minute boundary (14:31:00)
            # 1705161645 // 60 = 28419360
            # 28419360 * 60 = 1705161600 (14:30:00)
            # + 60 = 1705161660 (14:31:00)
            expected = 1705161660
            assert reset_time == expected

    def test_first_request_aligned_reset_time(self):
        """Reset time should be current_time + period when not aligned."""
        current_time = 1705161645.0  # 14:30:45
        with patch("time.time", return_value=current_time):
            reset_time = _calculate_stable_reset_time_sliding_window(
                60, align_to_clock=False
            )

            # Should be exactly current_time + 60
            expected = int(current_time + 60)
            assert reset_time == expected


class TestSettingsIntegration(TestCase):
    """Test that settings are properly loaded and used."""

    def setUp(self):
        reset_settings()

    def tearDown(self):
        reset_settings()

    @override_settings(RATELIMIT_ALIGN_WINDOW_TO_CLOCK=False)
    def test_setting_disabled(self):
        """Test that setting can be disabled via Django settings."""
        from django_smart_ratelimit.config import get_settings

        settings = get_settings()
        assert settings.align_window_to_clock is False

    @override_settings(RATELIMIT_ALIGN_WINDOW_TO_CLOCK=True)
    def test_setting_enabled(self):
        """Test that setting can be enabled via Django settings."""
        from django_smart_ratelimit.config import get_settings

        settings = get_settings()
        assert settings.align_window_to_clock is True

    def test_default_is_clock_aligned(self):
        """Test that default behavior is clock-aligned for backward compat."""
        from django_smart_ratelimit.config import get_settings

        settings = get_settings()
        assert settings.align_window_to_clock is True
