"""
Common key functions for django-smart-ratelimit.

This module provides standardized key generation functions that can be used
across examples, tests, and user applications to reduce code duplication
and ensure consistent behavior.
"""

import hashlib
import logging
from typing import Any, Callable, List, Optional, Union

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest

logger = logging.getLogger(__name__)


def get_ip_key(request: HttpRequest) -> str:
    """
    Extract IP address from request for use as rate limiting key.

    Args:
        request: Django HTTP request object

    Returns:
        IP address string formatted as 'ip:{address}'
    """
    # Try various headers to get real IP (considering proxies)
    ip_headers = [
        "HTTP_CF_CONNECTING_IP",  # Cloudflare
        "HTTP_X_FORWARDED_FOR",  # Standard proxy header
        "HTTP_X_REAL_IP",  # Nginx proxy
        "REMOTE_ADDR",  # Direct connection
    ]

    for header in ip_headers:
        ip = request.META.get(header)
        if ip:
            # Handle comma-separated IPs (X-Forwarded-For)
            if "," in ip:
                ip = ip.split(",")[0].strip()
            if ip and ip != "unknown":
                return f"ip:{ip}"

    return "ip:unknown"


def get_user_key(request: HttpRequest) -> str:
    """
    Extract user ID from request for use as rate limiting key.

    Args:
        request: Django HTTP request object

    Returns:
        User ID string formatted as 'user:{id}' or falls back to IP
    """
    if hasattr(request, "user") and request.user.is_authenticated:
        user_id = getattr(request.user, "id", None)
        return f"user:{user_id}" if user_id else get_ip_key(request)
    else:
        # Fall back to IP for anonymous users
        return get_ip_key(request)


def get_api_key_key(request: HttpRequest, header_name: str = "X-API-Key") -> str:
    """
    Extract API key from request headers.

    Args:
        request: Django HTTP request object
        header_name: Header name containing API key

    Returns:
        API key-based rate limit key or falls back to IP
    """
    api_key = request.META.get(f'HTTP_{header_name.upper().replace("-", "_")}')
    if api_key:
        return f"api_key:{api_key}"

    # Fallback to user or IP if no API key
    return get_user_key(request)


def get_jwt_key(request: HttpRequest, jwt_field: str = "sub") -> str:
    """
    Extract JWT-based key from request headers.

    Args:
        request: Django HTTP request object
        jwt_field: JWT field to use as key (default: 'sub')

    Returns:
        JWT-based key string or falls back to IP
    """
    try:
        import jwt

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove 'Bearer ' prefix
            decoded = jwt.decode(token, options={"verify_signature": False})

            if jwt_field in decoded:
                return f"jwt:{jwt_field}:{decoded[jwt_field]}"

    except (ImportError, Exception) as e:
        # Catch Exception to handle jwt.InvalidTokenError if jwt is installed
        if not isinstance(e, ImportError):
            logger.debug(f"JWT extraction failed: {e}")

    # Fallback to IP if JWT extraction fails
    return get_ip_key(request)


def get_client_identifier(request: HttpRequest, identifier_type: str = "auto") -> str:
    """
    Get client identifier based on specified type.

    Args:
        request: Django HTTP request object
        identifier_type: Type of identifier ('ip', 'user', 'session', 'auto')

    Returns:
        Client identifier string
    """
    if identifier_type == "ip":
        return get_ip_key(request)
    elif identifier_type == "user":
        return get_user_key(request)
    elif identifier_type == "session":
        session_key = getattr(request.session, "session_key", None)
        if session_key:
            return f"session:{session_key}"
        else:
            return get_ip_key(request)  # Fallback to IP
    elif identifier_type == "auto":
        # Auto-select based on authentication status
        return get_user_key(request)
    else:
        raise ImproperlyConfigured(f"Invalid identifier_type: {identifier_type}")


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
    return get_user_key(request)


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


def get_tenant_key(request: HttpRequest, tenant_field: str = "tenant_id") -> str:
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


def get_device_fingerprint_key(request: HttpRequest) -> str:
    """
    Generate device fingerprint-based rate limiting key.

    Generate a key based on device characteristics from request headers.

    Args:
        request: Django HTTP request object

    Returns:
        Rate limiting key string based on device fingerprint
    """
    # Collect identifying headers
    fingerprint_data = [
        request.META.get("HTTP_USER_AGENT", ""),
        request.META.get("HTTP_ACCEPT_LANGUAGE", ""),
        request.META.get("HTTP_ACCEPT_ENCODING", ""),
        request.META.get("HTTP_DNT", ""),  # Do Not Track
    ]

    # Create hash of combined data
    combined = "|".join(fingerprint_data)
    fingerprint = hashlib.sha256(combined.encode(), usedforsecurity=False).hexdigest()[
        :16
    ]

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
    return get_api_key_key(request, header_name)


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


def generate_key(
    key: Union[str, Callable], request: HttpRequest, *args: Any, **kwargs: Any
) -> str:
    """
    Generate rate limit key from template or callable.

    Args:
        key: Key template string or callable function
        request: Django HTTP request object
        *args: Additional arguments passed from decorator
        **kwargs: Additional keyword arguments passed from decorator

    Returns:
        Generated rate limit key string

    Raises:
        ImproperlyConfigured: If key type is invalid
    """
    if callable(key):
        return key(request, *args, **kwargs)

    if isinstance(key, str):
        # Handle common key patterns
        if key == "ip":
            return get_ip_key(request)
        elif key == "user":
            return get_user_key(request)
        elif key.startswith("user:") and hasattr(request, "user"):
            # Handle user-based templates like "user:{user.id}"
            if request.user.is_authenticated:
                user_id = getattr(request.user, "id", None)
                return f"user:{user_id}" if user_id else get_ip_key(request)
            else:
                return get_ip_key(request)  # Fallback to IP
        elif key.startswith("ip:"):
            # Handle IP-based templates
            return get_ip_key(request)
        elif key.startswith("header:"):
            # Handle header-based keys
            header_name = key.split(":", 1)[1]
            meta_key = f"HTTP_{header_name.upper().replace('-', '_')}"
            value = request.META.get(meta_key, "")
            return f"header:{header_name}:{value}"
        elif key.startswith("get:"):
            # Handle GET parameter keys
            param_name = key.split(":", 1)[1]
            value = request.GET.get(param_name, "")
            return f"get:{param_name}:{value}"
        else:
            # Return key as-is for other patterns
            return key

    raise ImproperlyConfigured(f"Invalid key type: {type(key)}")
