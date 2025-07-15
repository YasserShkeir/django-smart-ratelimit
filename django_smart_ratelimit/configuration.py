"""
Enhanced Configuration Utilities

This module provides advanced configuration management for rate limiting,
including dynamic configuration, validation, and standardized patterns.
"""

import inspect
import logging
from typing import Any, Callable, Dict, List, Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest

from .auth_utils import is_authenticated_user
from .key_functions import user_or_ip_key
from .utils import parse_rate

logger = logging.getLogger(__name__)


class RateLimitConfigManager:
    """
    Advanced configuration manager for rate limiting.

    Provides dynamic configuration management, validation, and caching.
    """

    def __init__(self) -> None:
        """Initialize instance."""
        self._config_cache: Dict[str, Dict[str, Any]] = {}
        self._validators: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self._default_configs = self._load_default_configs()

    def _load_default_configs(self) -> Dict[str, Any]:
        """Load default configurations for common patterns."""
        return {
            "api_endpoints": {
                "rate": "100/h",
                "key": user_or_ip_key,
                "algorithm": "sliding_window",
                "block": True,
            },
            "authentication": {
                "rate": "5/m",
                "key": "ip",
                "algorithm": "fixed_window",
                "block": True,
            },
            "public_content": {
                "rate": "1000/h",
                "key": "ip",
                "algorithm": "sliding_window",
                "block": False,
            },
            "user_actions": {
                "rate": "50/h",
                "key": "user",
                "algorithm": "sliding_window",
                "block": True,
                "skip_if": lambda request: not is_authenticated_user(request),
            },
            "admin_operations": {
                "rate": "10/m",
                "key": "user",
                "algorithm": "sliding_window",
                "block": True,
                "skip_if": lambda request: not (
                    is_authenticated_user(request) and request.user.is_staff
                ),
            },
        }

    def get_config(self, config_name: str, **overrides: Any) -> Dict[str, Any]:
        """
        Get a configuration by name with optional overrides.

        Args:
            config_name: Name of the configuration
            **overrides: Configuration overrides

        Returns:
            Configuration dictionary
        """
        # Try cache first
        cache_key = f"{config_name}:{hash(str(sorted(overrides.items())))}"
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]

        # Get base configuration
        if config_name in self._default_configs:
            config = self._default_configs[config_name].copy()
        else:
            # Try to load from Django settings
            setting_name = f"RATELIMIT_CONFIG_{config_name.upper()}"
            config = getattr(settings, setting_name, {})

        # Apply overrides
        config.update(overrides)

        # Validate configuration
        self._validate_config(config)

        # Cache and return
        self._config_cache[cache_key] = config
        return config

    def register_config(self, name: str, config: Dict[str, Any]) -> None:
        """
        Register a new configuration.

        Args:
            name: Name of the configuration
            config: Configuration dictionary
        """
        self._validate_config(config)
        self._default_configs[name] = config
        # Clear cache for this config
        keys_to_remove = [
            k for k in self._config_cache.keys() if k.startswith(f"{name}:")
        ]
        for key in keys_to_remove:
            del self._config_cache[key]

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """
        Validate a rate limiting configuration.

        Args:
            config: Configuration to validate

        Raises:
            ImproperlyConfigured: If configuration is invalid
        """
        required_fields = ["rate"]

        # Check required fields
        for field in required_fields:
            if field not in config:
                raise ImproperlyConfigured(
                    f"Required field '{field}' missing in rate limit config"
                )

        # Validate rate format
        try:
            parse_rate(config["rate"])
        except ValueError as e:
            raise ImproperlyConfigured(f"Invalid rate format: {e}")

        # Validate key function
        if "key" in config:
            key = config["key"]
            if not (isinstance(key, str) or callable(key)):
                raise ImproperlyConfigured("Key must be a string or callable")

        # Validate skip_if function
        if "skip_if" in config:
            skip_if = config["skip_if"]
            if not callable(skip_if):
                raise ImproperlyConfigured("skip_if must be callable")

            # Check function signature
            sig = inspect.signature(skip_if)
            if len(sig.parameters) != 1:
                raise ImproperlyConfigured(
                    "skip_if function must accept exactly one parameter (request)"
                )

        # Validate algorithm
        if "algorithm" in config:
            valid_algorithms = ["sliding_window", "fixed_window", "token_bucket"]
            if config["algorithm"] not in valid_algorithms:
                raise ImproperlyConfigured(
                    f"Algorithm must be one of: {valid_algorithms}"
                )

        # Additional custom validations
        for validator_name, validator_func in self._validators.items():
            validator_func(config)

    def register_validator(
        self, name: str, validator: Callable[[Dict[str, Any]], None]
    ) -> None:
        """
        Register a custom configuration validator.

        Args:
            name: Name of the validator
            validator: Validator function that raises ImproperlyConfigured on error
        """
        self._validators[name] = validator

    def clear_cache(self) -> None:
        """Clear the configuration cache."""
        self._config_cache.clear()


class DynamicRateLimitConfig:
    """
    Dynamic rate limiting configuration that can change based on request context.

    Allows for context-aware rate limiting with different rules based on
    request characteristics, user attributes, or system state.
    """

    def __init__(self) -> None:
        """Initialize instance."""
        self._rules: List[Dict[str, Any]] = []
        self._default_config: Optional[Dict[str, Any]] = None

    def add_rule(
        self,
        condition: Callable[[HttpRequest], bool],
        config: Dict[str, Any],
        priority: int = 0,
    ) -> None:
        """
        Add a conditional rule for rate limiting.

        Args:
            condition: Function that returns True if this rule should apply
            config: Rate limiting configuration to use
            priority: Priority of this rule (higher = more important)
        """
        rule = {"condition": condition, "config": config, "priority": priority}
        self._rules.append(rule)
        # Sort by priority (descending)
        self._rules.sort(key=lambda x: x["priority"], reverse=True)

    def set_default_config(self, config: Dict[str, Any]) -> None:
        """
        Set the default configuration to use when no rules match.

        Args:
            config: Default rate limiting configuration
        """
        self._default_config = config

    def get_config_for_request(self, request: HttpRequest) -> Dict[str, Any]:
        """
        Get the appropriate configuration for a request.

        Args:
            request: The Django request object

        Returns:
            Rate limiting configuration dictionary
        """
        # Check rules in priority order
        for rule in self._rules:
            try:
                if rule["condition"](request):
                    return rule["config"]
            except Exception as e:
                logger.warning(f"Error evaluating rate limit rule condition: {e}")
                continue

        # Return default if no rules match
        if self._default_config:
            return self._default_config

        # Fallback to basic configuration
        return {"rate": "100/h", "key": "ip"}


# Predefined condition functions for common use cases
class RateLimitConditions:
    """
    Collection of predefined condition functions for dynamic rate limiting.
    """

    @staticmethod
    def is_authenticated(request: HttpRequest) -> bool:
        """Check if the user is authenticated."""
        return is_authenticated_user(request)

    @staticmethod
    def is_staff(request: HttpRequest) -> bool:
        """Check if the user is staff."""
        return is_authenticated_user(request) and getattr(
            request.user, "is_staff", False
        )

    @staticmethod
    def is_superuser(request: HttpRequest) -> bool:
        """Check if the user is a superuser."""
        return is_authenticated_user(request) and getattr(
            request.user, "is_superuser", False
        )

    @staticmethod
    def has_api_key(request: HttpRequest) -> bool:
        """Check if the request has an API key."""
        return bool(request.headers.get("X-API-Key"))

    @staticmethod
    def is_mobile(request: HttpRequest) -> bool:
        """Check if the request is from a mobile device."""
        user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
        mobile_indicators = ["mobile", "android", "iphone", "ipad", "tablet"]
        return any(indicator in user_agent for indicator in mobile_indicators)

    @staticmethod
    def is_bot(request: HttpRequest) -> bool:
        """Check if the request is from a bot."""
        user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
        bot_indicators = ["bot", "crawler", "spider", "scraper"]
        return any(indicator in user_agent for indicator in bot_indicators)

    @staticmethod
    def is_internal_request(request: HttpRequest) -> bool:
        """Check if the request is internal."""
        return request.META.get("HTTP_X_INTERNAL_REQUEST") == "true"

    @staticmethod
    def is_high_priority_path(request: HttpRequest) -> bool:
        """Check if the request path is high priority."""
        high_priority_paths = ["/api/health/", "/api/status/", "/admin/"]
        return any(request.path.startswith(path) for path in high_priority_paths)

    @classmethod
    def create_method_condition(
        cls, methods: List[str]
    ) -> Callable[[HttpRequest], bool]:
        """
        Create a condition that checks HTTP method.

        Args:
            methods: List of HTTP methods to match

        Returns:
            Condition function
        """
        methods_upper = [method.upper() for method in methods]

        def condition(request: HttpRequest) -> bool:
            return bool(request.method and request.method.upper() in methods_upper)

        return condition

    @classmethod
    def create_path_condition(
        cls, patterns: List[str]
    ) -> Callable[[HttpRequest], bool]:
        """
        Create a condition that checks request path patterns.

        Args:
            patterns: List of path patterns to match

        Returns:
            Condition function
        """

        def condition(request: HttpRequest) -> bool:
            return any(pattern in request.path for pattern in patterns)

        return condition

    @classmethod
    def create_header_condition(
        cls, header_name: str, header_value: str
    ) -> Callable[[HttpRequest], bool]:
        """
        Create a condition that checks for a specific header value.

        Args:
            header_name: Name of the header to check
            header_value: Expected value of the header

        Returns:
            Condition function
        """

        def condition(request: HttpRequest) -> bool:
            return request.headers.get(header_name) == header_value

        return condition


# Global configuration manager instance
config_manager = RateLimitConfigManager()


# Helper functions for easy configuration
def get_rate_limit_config(config_name: str, **overrides: Any) -> Dict[str, Any]:
    """
    Get a rate limiting configuration by name.

    Args:
        config_name: Name of the configuration
        **overrides: Configuration overrides

    Returns:
        Configuration dictionary
    """
    return config_manager.get_config(config_name, **overrides)


def register_rate_limit_config(name: str, config: Dict[str, Any]) -> None:
    """
    Register a new rate limiting configuration.

    Args:
        name: Name of the configuration
        config: Configuration dictionary
    """
    config_manager.register_config(name, config)


def create_dynamic_config() -> DynamicRateLimitConfig:
    """
    Create a new dynamic rate limiting configuration.

    Returns:
        DynamicRateLimitConfig instance
    """
    return DynamicRateLimitConfig()


# Example usage patterns
def create_api_config_with_tiers() -> DynamicRateLimitConfig:
    """
    Create a dynamic configuration for API endpoints with user tiers.

    Returns:
        Configured DynamicRateLimitConfig
    """
    dynamic_config = DynamicRateLimitConfig()

    # Premium users get higher limits
    dynamic_config.add_rule(
        condition=lambda request: (
            is_authenticated_user(request)
            and hasattr(request.user, "subscription_tier")
            and request.user.subscription_tier == "premium"
        ),
        config={"rate": "1000/h", "key": "user", "algorithm": "sliding_window"},
        priority=100,
    )

    # Staff users get even higher limits
    dynamic_config.add_rule(
        condition=RateLimitConditions.is_staff,
        config={"rate": "5000/h", "key": "user", "algorithm": "sliding_window"},
        priority=200,
    )

    # Default for authenticated users
    dynamic_config.add_rule(
        condition=RateLimitConditions.is_authenticated,
        config={"rate": "100/h", "key": "user", "algorithm": "sliding_window"},
        priority=50,
    )

    # Default for anonymous users
    dynamic_config.set_default_config(
        {"rate": "50/h", "key": "ip", "algorithm": "sliding_window"}
    )

    return dynamic_config
