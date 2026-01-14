"""
Backend management for rate limiting storage.

This module provides the backend selection and initialization logic.
"""

from typing import Dict, Optional

from django.core.exceptions import ImproperlyConfigured

from .base import BaseBackend
from .factory import BackendFactory

# Backend instance cache
_backend_instances: Dict[str, BaseBackend] = {}


def get_backend(backend_name: Optional[str] = None) -> BaseBackend:
    """
    Get the configured rate limiting backend.

    Args:
        backend_name: Specific backend to use, or None for default

    Returns:
        Configured backend instance (cached for reuse)
    """
    from django_smart_ratelimit.config import get_settings

    settings = get_settings()

    if backend_name is None:
        # Check if multi-backend is configured
        if settings.multi_backends:
            backend_name = "multi"
        else:
            backend_name = settings.backend_class

    # Return cached instance if available
    if backend_name in _backend_instances:
        return _backend_instances[backend_name]

    # Create new instance based on backend name
    backend: BaseBackend
    kwargs = {}

    # Special handling for parameter-heavy backends
    if backend_name == "multi":
        kwargs = {
            "backends": settings.multi_backends,
            "fallback_strategy": settings.multi_backend_strategy,
            "health_check_interval": settings.health_check_interval,
        }

    try:
        backend = BackendFactory.create_backend(backend_name, **kwargs)

        # Validate dependency requirements
        if backend_name == "mongodb":
            from .mongodb import pymongo

            if pymongo is None:
                raise ImproperlyConfigured(
                    "MongoDB backend requires the pymongo package. "
                    "Install it with: pip install pymongo"
                )

    except (ImportError, AttributeError, ValueError, TypeError) as e:
        raise ImproperlyConfigured(f"Failed to initialize backend {backend_name}: {e}")

    # Cache the instance
    _backend_instances[backend_name] = backend
    return backend


def get_async_backend(backend_name: Optional[str] = None) -> BaseBackend:
    """
    Get an async-compatible rate limiting backend.

    If backend is 'redis', returns AsyncRedisBackend.
    Otherwise returns the standard backend which has async wrapper methods.
    """
    from django_smart_ratelimit.config import get_settings

    settings = get_settings()

    if backend_name is None:
        backend_name = settings.backend_class

    if backend_name == "redis":
        # Force use of AsyncRedisBackend for redis
        return get_backend("async_redis")

    # For others, use standard backend (wrappers)
    return get_backend(backend_name)


def clear_backend_cache() -> None:
    """Clear the backend instance cache. Useful for testing."""
    _backend_instances.clear()


__all__ = ["get_backend", "get_async_backend", "BaseBackend", "clear_backend_cache"]
