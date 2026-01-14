"""Tests for configuration validation."""

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from django_smart_ratelimit.backends.utils import validate_backend_config
from django_smart_ratelimit.config import RateLimitSettings
from django_smart_ratelimit.utils import parse_rate


class TestConfigurationValidation(TestCase):
    """Tests for configuration validation."""

    def test_parse_rate_limit_invalid(self):
        """Test parsing of invalid rate limit strings."""
        invalid_limits = [
            "abc",
            "100",  # Missing period
            "100/x",  # Invalid period
            "/m",  # Missing count
            "100/",  # Missing period
            "",
        ]

        for invalid in invalid_limits:
            with self.assertRaises(ImproperlyConfigured):
                parse_rate(invalid)

    def test_parse_rate_limit_valid(self):
        """Test parsing of valid rate limit strings."""
        test_cases = [
            ("100/s", 100, 1),
            ("100/m", 100, 60),
            ("100/h", 100, 3600),
            ("100/d", 100, 86400),
            ("1/s", 1, 1),
            ("1000000/h", 1000000, 3600),
        ]

        for limit_str, expected_count, expected_period in test_cases:
            count, period = parse_rate(limit_str)
            self.assertEqual(count, expected_count)
            self.assertEqual(period, expected_period)


class TestBackendConfigurationValidation(TestCase):
    """Tests for backend configuration validation."""

    def test_validate_backend_config_invalid_timeout(self):
        """Test validate_backend_config with invalid timeout."""
        config = {"timeout": -1}
        with self.assertRaisesRegex(ValueError, "Timeout must be a positive number"):
            validate_backend_config(config, "redis")

        config = {"timeout": "invalid"}
        with self.assertRaisesRegex(ValueError, "Timeout must be a positive number"):
            validate_backend_config(config, "redis")

    def test_validate_backend_config_invalid_max_connections(self):
        """Test validate_backend_config with invalid max_connections."""
        config = {"max_connections": 0}
        with self.assertRaisesRegex(
            ValueError, "max_connections must be a positive integer"
        ):
            validate_backend_config(config, "redis")

        config = {"max_connections": "invalid"}
        with self.assertRaisesRegex(
            ValueError, "max_connections must be a positive integer"
        ):
            validate_backend_config(config, "redis")

    @override_settings(RATELIMIT_ENABLE="not_a_bool")
    def test_ratelimit_enable_validation(self):
        """Test that RATELIMIT_ENABLE must be a boolean."""
        with self.assertRaisesRegex(
            ImproperlyConfigured, "RATELIMIT_ENABLE must be a boolean"
        ):
            RateLimitSettings.from_django_settings()

    @override_settings(RATELIMIT_BACKEND="nonexistent.Backend")
    def test_invalid_backend_setting(self):
        """Test handling of invalid backend configuration."""
        from django_smart_ratelimit.backends import get_backend

        with self.assertRaises(ImproperlyConfigured):
            get_backend()
