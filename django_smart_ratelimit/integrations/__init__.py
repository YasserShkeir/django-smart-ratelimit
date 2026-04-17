"""
Integrations with external frameworks and libraries.

This package provides adapters that integrate django-smart-ratelimit with
popular Django packages like Django REST Framework.
"""

__all__ = [
    "SmartRateLimitThrottle",
    "UserRateLimitThrottle",
    "AnonRateLimitThrottle",
    "ScopedRateLimitThrottle",
]

try:
    from .drf import (
        AnonRateLimitThrottle,
        ScopedRateLimitThrottle,
        SmartRateLimitThrottle,
        UserRateLimitThrottle,
    )
except ImportError:
    # DRF not installed; classes won't be available but package won't fail
    pass
