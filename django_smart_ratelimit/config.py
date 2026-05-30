"""
Centralized configuration management for Django Smart Ratelimit.

This module provides a settings abstraction layer that decouples the library
from Django's global settings, enabling easier testing and dependency injection.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured
from django.test.signals import setting_changed


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

    # Client IP / proxy trust. When ``trusted_proxies`` is set (a list of
    # IP/CIDR strings), forwarded headers (X-Forwarded-For, CF-Connecting-IP,
    # X-Real-IP) are only honored for requests arriving from a trusted proxy,
    # and the real client is taken as the right-most non-trusted entry of the
    # X-Forwarded-For chain. When it is not set, ``trust_forwarded_headers``
    # controls whether forwarded headers are trusted at all (default True keeps
    # the historical behavior; set False to use REMOTE_ADDR only).
    trusted_proxies: Optional[list] = None
    trust_forwarded_headers: bool = True

    # Error Handling
    log_exceptions: bool = True
    exception_handler: Optional[str] = None

    # Custom response for rate limit exceeded (429)
    # Can be a dotted path to a callable: (request) -> HttpResponse
    # or a template name string to render (e.g. "429.html")
    ratelimit_response_handler: Optional[str] = None

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
                "django_smart_ratelimit.backends.memory.MemoryBackend",
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
            trusted_proxies=getattr(django_settings, "RATELIMIT_TRUSTED_PROXIES", None),
            trust_forwarded_headers=getattr(
                django_settings, "RATELIMIT_TRUST_FORWARDED_HEADERS", True
            ),
            log_exceptions=getattr(django_settings, "RATELIMIT_LOG_EXCEPTIONS", True),
            collect_metrics=getattr(
                django_settings, "RATELIMIT_COLLECT_METRICS", False
            ),
            exception_handler=getattr(
                django_settings, "RATELIMIT_EXCEPTION_HANDLER", None
            ),
            ratelimit_response_handler=getattr(
                django_settings, "RATELIMIT_RESPONSE_HANDLER", None
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


# Explicitly-configured settings (via configure(), mainly for tests).
_settings: Optional[RateLimitSettings] = None
# Lazily-built cache of settings loaded from Django. Rebuilding scans
# dir(django_settings) for RATELIMIT_CONFIG_* on every call, so caching it
# removes a measurable per-request cost. The cache is invalidated whenever a
# RATELIMIT_* setting changes (which covers override_settings/the pytest-django
# settings fixture in tests); in production, settings do not change, so the
# object is built once.
_cached_settings: Optional[RateLimitSettings] = None


def get_settings() -> RateLimitSettings:
    """Get the current rate limit settings (cached)."""
    if _settings is not None:
        return _settings
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = RateLimitSettings.from_django_settings()
    return _cached_settings


def configure(settings: RateLimitSettings) -> None:
    """Override settings (useful for testing)."""
    global _settings
    _settings = settings


def reset_settings() -> None:
    """Reset settings to reload from Django."""
    global _settings, _cached_settings
    _settings = None
    _cached_settings = None


def _invalidate_settings_cache(
    *, setting: Optional[str] = None, **_kwargs: Any
) -> None:
    """Drop the cached settings when a RATELIMIT_* setting changes.

    Connected to Django's ``setting_changed`` signal so ``override_settings``
    and the pytest-django ``settings`` fixture stay correct while production
    keeps the cache warm.
    """
    global _cached_settings
    if setting is None or setting.startswith("RATELIMIT"):
        _cached_settings = None


# Invalidate the cache on any relevant settings change.
setting_changed.connect(_invalidate_settings_cache)
