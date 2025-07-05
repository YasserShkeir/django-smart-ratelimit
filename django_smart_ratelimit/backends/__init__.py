"""
Backend management for rate limiting storage.

This module provides the backend selection and initialization logic.
"""

from typing import Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseBackend

# Backend instance cache
_backend_instances = {}


def get_backend(backend_name: Optional[str] = None) -> BaseBackend:
    """
    Get the configured rate limiting backend.

    Args:
        backend_name: Specific backend to use, or None for default

    Returns:
        Configured backend instance (cached for reuse)
    """
    if backend_name is None:
        backend_name = getattr(settings, "RATELIMIT_BACKEND", "redis")

    # Return cached instance if available
    if backend_name in _backend_instances:
        return _backend_instances[backend_name]

    # Create new instance based on backend name
    if backend_name == "redis":
        from .redis_backend import RedisBackend
        backend = RedisBackend()
    elif backend_name == "memory":
        from .memory import MemoryBackend
        backend = MemoryBackend()
    else:
        raise ImproperlyConfigured(f"Unknown backend: {backend_name}")

    # Cache the instance
    _backend_instances[backend_name] = backend
    return backend


def clear_backend_cache():
    """Clear the backend instance cache. Useful for testing."""
    global _backend_instances
    _backend_instances.clear()


__all__ = ["get_backend", "BaseBackend", "clear_backend_cache"]
