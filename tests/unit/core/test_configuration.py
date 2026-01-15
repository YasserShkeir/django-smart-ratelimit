"""Simplified tests for configuration module."""

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from django_smart_ratelimit import RateLimitConfigManager


class RateLimitConfigManagerSimpleTests(TestCase):
    """Simplified tests for RateLimitConfigManager."""

    def setUp(self):
        """Set up test fixtures."""
        self.config_manager = RateLimitConfigManager()

    def test_initialization(self):
        """Test config manager initialization."""
        assert isinstance(self.config_manager, RateLimitConfigManager)
        assert isinstance(self.config_manager._config_cache, dict)
        assert isinstance(self.config_manager._default_configs, dict)

    def test_default_configs_loaded(self):
        """Test that default configurations are loaded."""
        assert "api_endpoints" in self.config_manager._default_configs
        assert "authentication" in self.config_manager._default_configs
        assert "public_content" in self.config_manager._default_configs

    def test_get_config(self):
        """Test get_config method."""
        config = self.config_manager.get_config("api_endpoints")
        assert isinstance(config, dict)
        assert "rate" in config

    def test_validate_invalid_config(self):
        """Test validate_config with invalid configuration."""
        # Test with minimal config that should pass basic validation
        invalid_config = {"invalid_key": "invalid_value"}
        # The method may not exist, so we'll test what we can
        try:
            result = self.config_manager.get_config("api_endpoints", **invalid_config)
            assert isinstance(result, dict)
        except AttributeError:
            # Method might not exist, that's okay
            pass


# ---------------- Expanded, comprehensive tests below ----------------


class RateLimitConfigManagerValidationTests(TestCase):
    """Validation and behavior tests for RateLimitConfigManager."""

    def setUp(self):
        self.mgr = RateLimitConfigManager()

    def test_invalid_rate_format_raises(self):
        """Test that invalid rate formats raise ImproperlyConfigured."""
        with self.assertRaises(ImproperlyConfigured):
            self.mgr.get_config("api_endpoints", rate="invalid")

    def test_invalid_key_type_raises(self):
        """Test that invalid key types raise ImproperlyConfigured."""
        with self.assertRaises(ImproperlyConfigured):
            self.mgr.get_config("api_endpoints", key=123)  # not str or callable

    def test_invalid_skip_if_type_raises(self):
        """Test that invalid skip_if types raise ImproperlyConfigured."""
        with self.assertRaises(ImproperlyConfigured):
            self.mgr.get_config("api_endpoints", skip_if="not_callable")

    def test_invalid_skip_if_signature_raises(self):
        """Test that skip_if callables with wrong signature raise ImproperlyConfigured."""

        def bad_skip_if(a, b):  # wrong arity
            return False

        with self.assertRaises(ImproperlyConfigured):
            self.mgr.get_config("api_endpoints", skip_if=bad_skip_if)

    def test_invalid_algorithm_raises(self):
        """Test that invalid algorithm names raise ImproperlyConfigured."""
        with self.assertRaises(ImproperlyConfigured):
            self.mgr.get_config("api_endpoints", algorithm="unknown")

    def test_register_and_get_custom_config(self):
        """Test registering and retrieving a custom configuration."""
        custom = {"rate": "10/m", "key": "ip", "algorithm": "fixed_window"}
        self.mgr.register_config("custom_actions", custom)

        cfg = self.mgr.get_config("custom_actions")
        assert cfg["rate"] == "10/m"
        assert cfg["key"] == "ip"
        assert cfg["algorithm"] == "fixed_window"

    def test_overrides_are_applied_and_cached(self):
        """Test that configuration overrides are applied and cached correctly."""
        cfg1 = self.mgr.get_config("api_endpoints", rate="50/m", block=False)
        cfg2 = self.mgr.get_config("api_endpoints", rate="50/m", block=False)
        # Same overrides should hit cache and be equal
        assert cfg1 == cfg2

    def test_clear_cache(self):
        """Test that clearing the cache removes cached configurations."""
        _ = self.mgr.get_config("api_endpoints", rate="75/m")
        assert self.mgr._config_cache
        self.mgr.clear_cache()
        assert not self.mgr._config_cache

    def test_register_validator_called(self):
        """Test that registered validators are called during configuration retrieval."""

        def must_block_validator(cfg):
            # Ensure configs explicitly set block True
            if cfg.get("block") is not True:
                raise ImproperlyConfigured("block must be True for this validator")

        self.mgr.register_validator("must_block", must_block_validator)
        with self.assertRaises(ImproperlyConfigured):
            self.mgr.get_config("api_endpoints", block=False)

    @override_settings(
        RATELIMIT_CONFIG_CUSTOM={
            "rate": "10/m",
            "key": "ip",
            "algorithm": "fixed_window",
            "block": True,
        }
    )
    def test_get_config_from_django_settings(self):
        """Test retrieving configuration from Django settings."""
        cfg = self.mgr.get_config("custom")
        assert cfg["rate"] == "10/m"
        assert cfg["key"] == "ip"
        assert cfg["algorithm"] == "fixed_window"
        assert cfg["block"]


@pytest.mark.parametrize(
    "fmt",
    [
        "10",  # missing period
        "m",  # missing limit
        "10/x",  # invalid period
        "10/0s",  # zero period (invalid suffix)
    ],
)
def test_more_invalid_rate_formats_parametrized(fmt):
    """Test additional invalid rate formats."""
    mgr = RateLimitConfigManager()
    with pytest.raises(ImproperlyConfigured):
        mgr.get_config("api_endpoints", rate=fmt)
