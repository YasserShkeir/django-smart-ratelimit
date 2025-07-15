"""
Common key functions for django-smart-ratelimit.

This module provides standardized key generation functions that can be used
across examples, tests, and user applications to reduce code duplication
and ensure consistent behavior.
"""

from typing import List, Optional

from django.http import HttpRequest

from .utils import get_ip_key


def user_or_ip_key(request: HttpRequest) -> str:
    """
    Generate rate limiting key based on user ID or IP address.

    Returns user ID if authenticated, otherwise falls back to IP address.
    This is the most common rate limiting pattern.

    Args:
        request: Django HTTP request object

    Returns:
        Rate limiting key string
    """
    if hasattr(request, "user") and request.user.is_authenticated:
        return f"user:{getattr(request.user, 'id', None)}"
    return get_ip_key(request)


def user_role_key(request: HttpRequest) -> str:
    """
    Generate rate limiting key with user role information.

    Includes user role (staff/user) in the key for role-based rate limiting.

    Args:
        request: Django HTTP request object

    Returns:
        Rate limiting key string with role information
    """
    if hasattr(request, "user") and request.user.is_authenticated:
        role = "staff" if getattr(request.user, "is_staff", False) else "user"
        return f"{getattr(request.user, 'id', None)}:{role}"
    return get_ip_key(request)


def geographic_key(request: HttpRequest) -> str:
    """
    Generate geographic-based rate limiting key.

    Combines geographic information with user/IP for location-based rate limiting.
    Requires appropriate headers (e.g., from Cloudflare).

    Args:
        request: Django HTTP request object

    Returns:
        Rate limiting key string with geographic information
    """
    country = request.META.get("HTTP_CF_IPCOUNTRY", "unknown")
    base_key = user_or_ip_key(request)
    return f"geo:{country}:{base_key}"


def tenant_aware_key(request: HttpRequest, tenant_field: str = "tenant_id") -> str:
    """
    Generate multi-tenant aware rate limiting key.

    Includes tenant information in the key for multi-tenant applications.

    Args:
        request: Django HTTP request object
        tenant_field: Field name to extract tenant ID from

    Returns:
        Rate limiting key string with tenant information
    """
    tenant_id = None

    # Try to get tenant from various sources
    tenant_id = request.GET.get(tenant_field)

    if not tenant_id:
        header_name = f'HTTP_{tenant_field.upper().replace("-", "_")}'
        tenant_id = request.META.get(header_name)

    if not tenant_id and hasattr(request, "user") and request.user.is_authenticated:
        tenant_id = getattr(request.user, tenant_field, None)

    if tenant_id:
        base_key = user_or_ip_key(request)
        return f"tenant:{tenant_id}:{base_key}"

    return user_or_ip_key(request)


def composite_key(request: HttpRequest, strategies: Optional[List[str]] = None) -> str:
    """
    Generate composite rate limiting key using multiple strategies.

    Args:
        request: Django HTTP request object
        strategies: List of strategy names to try in order
                   Default: ['user', 'ip']

    Returns:
        Rate limiting key string using the first successful strategy
    """
    if strategies is None:
        strategies = ["user", "ip"]

    for strategy in strategies:
        if (
            strategy == "user"
            and hasattr(request, "user")
            and request.user.is_authenticated
        ):
            return f"user:{getattr(request.user, 'id', None)}"
        elif strategy == "ip":
            return get_ip_key(request)
        elif strategy == "session":
            session_key = getattr(request.session, "session_key", None)
            if session_key:
                return f"session:{session_key}"

    # Fallback to IP if all strategies fail
    return get_ip_key(request)


def device_fingerprint_key(request: HttpRequest) -> str:
    """
    Generate device fingerprint-based rate limiting key.

    Generate a key based on device characteristics from request headers.

    Args:
        request: Django HTTP request object

    Returns:
        Rate limiting key string based on device fingerprint
    """
    import hashlib

    # Collect identifying headers
    fingerprint_data = [
        request.META.get("HTTP_USER_AGENT", ""),
        request.META.get("HTTP_ACCEPT_LANGUAGE", ""),
        request.META.get("HTTP_ACCEPT_ENCODING", ""),
        request.META.get("HTTP_DNT", ""),  # Do Not Track
    ]

    # Create hash of combined data
    combined = "|".join(fingerprint_data)
    fingerprint = hashlib.md5(combined.encode(), usedforsecurity=False).hexdigest()[:16]

    return f"device:{fingerprint}"


def api_key_aware_key(request: HttpRequest, header_name: str = "X-API-Key") -> str:
    """
    Generate API key aware rate limiting key.

    Use API key if present, otherwise falls back to user or IP.

    Args:
        request: Django HTTP request object
        header_name: Header name containing API key

    Returns:
        Rate limiting key string with API key or fallback
    """
    api_key = request.META.get(f'HTTP_{header_name.upper().replace("-", "_")}')
    if api_key:
        return f"api_key:{api_key}"

    return user_or_ip_key(request)


def time_aware_key(request: HttpRequest, time_window: str = "hour") -> str:
    """
    Generate time-aware rate limiting key.

    Include time window in the key for time-based rate limiting patterns.

    Args:
        request: Django HTTP request object
        time_window: Time window ('hour', 'day', 'week', 'month')

    Returns:
        Rate limiting key string with time information
    """
    from datetime import datetime

    now = datetime.now()

    if time_window == "hour":
        time_str = now.strftime("%Y-%m-%d-%H")
    elif time_window == "day":
        time_str = now.strftime("%Y-%m-%d")
    elif time_window == "week":
        time_str = now.strftime("%Y-%W")
    elif time_window == "month":
        time_str = now.strftime("%Y-%m")
    else:
        time_str = now.strftime("%Y-%m-%d-%H")

    base_key = user_or_ip_key(request)
    return f"time:{time_window}:{time_str}:{base_key}"


# Legacy compatibility - these can be imported by old code
def user_or_ip_key_legacy(group: str, request: HttpRequest) -> str:
    """Provide legacy compatibility for old-style key functions."""
    return user_or_ip_key(request)


def user_role_key_legacy(group: str, request: HttpRequest) -> str:
    """Provide legacy compatibility for old-style key functions."""
    return user_role_key(request)
