"""
Centralized configuration management for Django Smart Ratelimit.

This module provides a settings abstraction layer that decouples the library
from Django's global settings, enabling easier testing and dependency injection.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured


@dataclass
class RateLimitSettings:
    """Centralized rate limiting configuration."""

    # Core
    enabled: bool = True

    # Backend configuration
    backend_class: str = "django_smart_ratelimit.backends.memory.MemoryBackend"
    backend_options: Dict[str, Any] = field(default_factory=dict)
    backend_config: Dict[str, Any] = field(default_factory=dict)  # Generic config

    # Specific Backend Configs
    redis_config: Dict[str, Any] = field(default_factory=dict)
    mongodb_config: Dict[str, Any] = field(default_factory=dict)

    # Multi-Backend
    multi_backends: list = field(default_factory=list)
    multi_backend_strategy: str = "first_healthy"

    # Behavior settings
    fail_open: bool = False
    key_prefix: str = "ratelimit:"
    default_algorithm: str = "sliding_window"
    default_limit: str = "100/m"
    align_window_to_clock: bool = True  # Clock-aligned windows by default

    # Error Handling
    log_exceptions: bool = True
    exception_handler: Optional[str] = None

    # Circuit breaker
    circuit_breaker_config: Dict[str, Any] = field(default_factory=dict)
    circuit_breaker_storage: str = "memory"
    circuit_breaker_redis_url: Optional[str] = None

    # Health Check
    health_check_interval: int = 30
    health_check_timeout: int = 5

    # Middleware
    middleware_config: Dict[str, Any] = field(default_factory=dict)

    # Memory Backend
    memory_max_keys: int = 10000
    memory_cleanup_interval: int = 300

    # Performance
    collect_metrics: bool = False

    # Custom/Dynamic Configs (RATELIMIT_CONFIG_*)
    custom_configs: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_django_settings(cls) -> "RateLimitSettings":
        """Load settings from Django configuration."""
        # Load custom configs
        custom_configs = {}
        for key in dir(django_settings):
            if key.startswith("RATELIMIT_CONFIG_"):
                name = key.replace("RATELIMIT_CONFIG_", "").lower()
                custom_configs[name] = getattr(django_settings, key)

        enabled = getattr(django_settings, "RATELIMIT_ENABLE", True)
        if not isinstance(enabled, bool):
            raise ImproperlyConfigured("RATELIMIT_ENABLE must be a boolean")

        return cls(
            enabled=enabled,
            backend_class=getattr(
                django_settings,
                "RATELIMIT_BACKEND",
                "django_smart_ratelimit.backends.MemoryBackend",
            ),
            backend_options=getattr(django_settings, "RATELIMIT_BACKEND_OPTIONS", {}),
            backend_config=getattr(django_settings, "RATELIMIT_BACKEND_CONFIG", {}),
            redis_config=getattr(django_settings, "RATELIMIT_REDIS", {}),
            mongodb_config=getattr(django_settings, "RATELIMIT_MONGODB", {}),
            multi_backends=getattr(django_settings, "RATELIMIT_MULTI_BACKENDS", [])
            or getattr(django_settings, "RATELIMIT_BACKENDS", []),
            multi_backend_strategy=getattr(
                django_settings, "RATELIMIT_MULTI_BACKEND_STRATEGY", "first_healthy"
            ),
            fail_open=getattr(django_settings, "RATELIMIT_FAIL_OPEN", False),
            key_prefix=getattr(django_settings, "RATELIMIT_KEY_PREFIX", "ratelimit:"),
            default_algorithm=getattr(
                django_settings, "RATELIMIT_ALGORITHM", "sliding_window"
            ),
            default_limit=getattr(django_settings, "RATELIMIT_DEFAULT_LIMIT", "100/m"),
            align_window_to_clock=getattr(
                django_settings, "RATELIMIT_ALIGN_WINDOW_TO_CLOCK", True
            ),
            log_exceptions=getattr(django_settings, "RATELIMIT_LOG_EXCEPTIONS", True),
            collect_metrics=getattr(
                django_settings, "RATELIMIT_COLLECT_METRICS", False
            ),
            exception_handler=getattr(
                django_settings, "RATELIMIT_EXCEPTION_HANDLER", None
            ),
            circuit_breaker_config=getattr(
                django_settings, "RATELIMIT_CIRCUIT_BREAKER", {}
            ),
            circuit_breaker_storage=getattr(
                django_settings, "RATELIMIT_CIRCUIT_BREAKER_STORAGE", "memory"
            ),
            circuit_breaker_redis_url=getattr(
                django_settings, "RATELIMIT_CIRCUIT_BREAKER_REDIS_URL", None
            ),
            health_check_interval=getattr(
                django_settings, "RATELIMIT_HEALTH_CHECK_INTERVAL", 30
            ),
            health_check_timeout=getattr(
                django_settings, "RATELIMIT_HEALTH_CHECK_TIMEOUT", 5
            ),
            middleware_config=getattr(django_settings, "RATELIMIT_MIDDLEWARE", {}),
            memory_max_keys=getattr(
                django_settings, "RATELIMIT_MEMORY_MAX_KEYS", 10000
            ),
            memory_cleanup_interval=getattr(
                django_settings, "RATELIMIT_MEMORY_CLEANUP_INTERVAL", 300
            ),
            custom_configs=custom_configs,
        )


# Global settings instance (lazy loaded)
_settings: Optional[RateLimitSettings] = None


def get_settings() -> RateLimitSettings:
    """Get the current rate limit settings."""
    # Always reload to support override_settings in tests
    # In production, we might want to cache this, but for now correctness is priority
    if _settings is None:
        return RateLimitSettings.from_django_settings()
    return _settings


def configure(settings: RateLimitSettings) -> None:
    """Override settings (useful for testing)."""
    global _settings
    _settings = settings


def reset_settings() -> None:
    """Reset settings to reload from Django."""
    global _settings
    _settings = None
