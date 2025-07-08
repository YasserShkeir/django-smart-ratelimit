"""
Backend management for rate limiting storage.

This module provides the backend selection and initialization logic.
"""

from typing import Dict, Optional

from django.conf import settings
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
    if backend_name is None:
        # Check if multi-backend is configured
        if hasattr(settings, "RATELIMIT_BACKENDS") and settings.RATELIMIT_BACKENDS:
            backend_name = "multi"
        else:
            backend_name = getattr(settings, "RATELIMIT_BACKEND", "redis")

    # Return cached instance if available
    if backend_name in _backend_instances:
        return _backend_instances[backend_name]

    # Create new instance based on backend name
    backend: BaseBackend
    if backend_name == "redis":
        from .redis_backend import RedisBackend

        backend = RedisBackend()
    elif backend_name == "memory":
        from .memory import MemoryBackend

        backend = MemoryBackend()
    elif backend_name == "database":
        from .database import DatabaseBackend

        backend = DatabaseBackend()
    elif backend_name == "mongodb":
        from .mongodb import MongoDBBackend, pymongo

        if pymongo is None:
            raise ImproperlyConfigured(
                "MongoDB backend requires the pymongo package. "
                "Install it with: pip install pymongo"
            )
        backend = MongoDBBackend()
    elif backend_name == "multi":
        from .multi import MultiBackend

        backend = MultiBackend()
    else:
        # Try to create backend using factory for full path
        try:
            # Check if it's a simple name or full path
            if "." not in backend_name:
                raise ImproperlyConfigured(f"Unknown backend: {backend_name}")
            backend = BackendFactory.create_backend(backend_name)
        except (ImportError, AttributeError, ValueError):
            raise ImproperlyConfigured(f"Unknown backend: {backend_name}")

    # Cache the instance
    _backend_instances[backend_name] = backend
    return backend


def clear_backend_cache() -> None:
    """Clear the backend instance cache. Useful for testing."""
    _backend_instances.clear()


__all__ = ["get_backend", "BaseBackend", "clear_backend_cache"]
