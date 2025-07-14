"""
Authentication utilities for django-smart-ratelimit.

This module provides standardized authentication-related utilities to reduce
code duplication and ensure consistent behavior across the package.
"""

from typing import Any, Dict, Optional

from django.http import HttpRequest


def is_authenticated_user(request: HttpRequest) -> bool:
    """
    Safe check for authenticated user.

    Args:
        request: Django HTTP request object

    Returns:
        True if user is authenticated, False otherwise
    """
    return hasattr(request, "user") and request.user.is_authenticated


def get_user_info(request: HttpRequest) -> Optional[Dict[str, Any]]:
    """
    Extract user information safely.

    Args:
        request: Django HTTP request object

    Returns:
        Dictionary with user information or None if not authenticated
    """
    if is_authenticated_user(request):
        return {
            "id": request.user.id,
            "username": request.user.username,
            "is_staff": request.user.is_staff,
            "is_superuser": request.user.is_superuser,
        }
    return None


def get_client_info(request: HttpRequest) -> Dict[str, Any]:
    """
    Extract client information from request.

    Args:
        request: Django HTTP request object

    Returns:
        Dictionary with client information
    """
    client_info = {
        "ip": request.META.get("REMOTE_ADDR", "unknown"),
        "user_agent": request.META.get("HTTP_USER_AGENT", "unknown"),
        "forwarded_for": request.META.get("HTTP_X_FORWARDED_FOR", ""),
        "real_ip": request.META.get("HTTP_X_REAL_IP", ""),
    }

    # Add user info if authenticated
    user_info = get_user_info(request)
    if user_info:
        client_info["user"] = user_info

    return client_info


def has_permission(request: HttpRequest, permission: str) -> bool:
    """
    Check if user has a specific permission.

    Args:
        request: Django HTTP request object
        permission: Permission string to check

    Returns:
        True if user has permission, False otherwise
    """
    if not is_authenticated_user(request):
        return False

    return request.user.has_perm(permission)


def is_staff_user(request: HttpRequest) -> bool:
    """
    Check if user is staff.

    Args:
        request: Django HTTP request object

    Returns:
        True if user is staff, False otherwise
    """
    return is_authenticated_user(request) and request.user.is_staff


def is_superuser(request: HttpRequest) -> bool:
    """
    Check if user is superuser.

    Args:
        request: Django HTTP request object

    Returns:
        True if user is superuser, False otherwise
    """
    return is_authenticated_user(request) and request.user.is_superuser


def get_user_role(request: HttpRequest) -> str:
    """
    Get user role as string.

    Args:
        request: Django HTTP request object

    Returns:
        User role string ('anonymous', 'user', 'staff', 'superuser')
    """
    if not is_authenticated_user(request):
        return "anonymous"

    if request.user.is_superuser:
        return "superuser"
    elif request.user.is_staff:
        return "staff"
    else:
        return "user"


def should_bypass_rate_limit(
    request: HttpRequest, bypass_staff: bool = False, bypass_superuser: bool = True
) -> bool:
    """
    Check if rate limiting should be bypassed for this user.

    Args:
        request: Django HTTP request object
        bypass_staff: Whether to bypass rate limiting for staff users
        bypass_superuser: Whether to bypass rate limiting for superusers

    Returns:
        True if rate limiting should be bypassed, False otherwise
    """
    if not is_authenticated_user(request):
        return False

    if bypass_superuser and request.user.is_superuser:
        return True

    if bypass_staff and request.user.is_staff:
        return True

    return False


def extract_user_identifier(request: HttpRequest) -> str:
    """
    Extract a unique identifier for the user.

    Args:
        request: Django HTTP request object

    Returns:
        Unique identifier string
    """
    if is_authenticated_user(request):
        return f"user:{request.user.id}"

    # Fallback to IP address
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


def is_internal_request(
    request: HttpRequest, internal_ips: Optional[list] = None
) -> bool:
    """
    Check if request comes from internal IP addresses.

    Args:
        request: Django HTTP request object
        internal_ips: List of internal IP addresses/ranges

    Returns:
        True if request is from internal IP, False otherwise
    """
    if internal_ips is None:
        internal_ips = ["127.0.0.1", "::1", "10.0.0.0/8", "192.168.0.0/16"]

    client_ip = request.META.get("REMOTE_ADDR", "")

    # Simple check for common internal IPs
    for internal_ip in internal_ips:
        if "/" in internal_ip:
            # Network range check would require ipaddress module
            # For now, do simple prefix check
            network_prefix = internal_ip.split("/")[0].rsplit(".", 1)[0]
            if client_ip.startswith(network_prefix):
                return True
        else:
            if client_ip == internal_ip:
                return True

    return False
