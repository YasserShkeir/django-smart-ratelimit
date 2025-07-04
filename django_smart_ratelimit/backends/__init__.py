"""
Backend management for rate limiting storage.

This module provides the backend selection and initialization logic.
"""

from typing import Optional
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseBackend


def get_backend(backend_name: Optional[str] = None) -> BaseBackend:
    """
    Get the configured rate limiting backend.
    
    Args:
        backend_name: Specific backend to use, or None for default
        
    Returns:
        Configured backend instance
    """
    if backend_name is None:
        backend_name = getattr(settings, 'RATELIMIT_BACKEND', 'redis')
    
    if backend_name == 'redis':
        from .redis_backend import RedisBackend
        return RedisBackend()
    else:
        raise ImproperlyConfigured(f"Unknown backend: {backend_name}")


__all__ = ['get_backend', 'BaseBackend']
