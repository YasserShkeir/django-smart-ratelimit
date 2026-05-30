"""
Authentication utilities for django-smart-ratelimit.

This module provides standardized authentication-related utilities to reduce
code duplication and ensure consistent behavior across the package.
"""

import ipaddress
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
        user = request.user
        return {
            "id": getattr(user, "id", None),
            "username": getattr(user, "username", None),
            "is_staff": getattr(user, "is_staff", False),
            "is_superuser": getattr(user, "is_superuser", False),
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
    # These are purely diagnostic raw reads exposed for inspection/logging; they
    # intentionally report the unprocessed transport values. Do NOT use "ip" /
    # "forwarded_for" / "real_ip" from here for trust or rate-limit-identity
    # decisions — use django_smart_ratelimit.policy.get_client_ip for that.
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

    return getattr(request.user, "has_perm", lambda x: False)(permission)


def is_staff_user(request: HttpRequest) -> bool:
    """
    Check if user is staff.

    Args:
        request: Django HTTP request object

    Returns:
        True if user is staff, False otherwise
    """
    return is_authenticated_user(request) and getattr(request.user, "is_staff", False)


def is_superuser(request: HttpRequest) -> bool:
    """
    Check if user is superuser.

    Args:
        request: Django HTTP request object

    Returns:
        True if user is superuser, False otherwise
    """
    return is_authenticated_user(request) and getattr(
        request.user, "is_superuser", False
    )


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

    if getattr(request.user, "is_superuser", False):
        return "superuser"
    elif getattr(request.user, "is_staff", False):
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

    if bypass_superuser and getattr(request.user, "is_superuser", False):
        return True

    if bypass_staff and getattr(request.user, "is_staff", False):
        return True

    return False


def extract_user_identifier(request: HttpRequest) -> str:
    """
    Extract a unique identifier for the user.

    Args:
        request: Django HTTP request object

    Returns:
        Unique identifier string

    Note:
        When no authenticated user is available the identifier falls back to the
        client IP. That IP is resolved via
        :func:`django_smart_ratelimit.policy.get_client_ip` (rather than reading
        ``REMOTE_ADDR`` directly) so the rate-limit identity honors
        ``RATELIMIT_TRUSTED_PROXIES`` / ``RATELIMIT_TRUST_FORWARDED_HEADERS`` and
        is not trivially spoofable via forwarded headers.
    """
    # Lazy import to avoid an import cycle with the policy package.
    from .policy import get_client_ip

    if is_authenticated_user(request):
        user_id = getattr(request.user, "id", None)
        return f"user:{user_id}" if user_id else f"ip:{get_client_ip(request)}"

    # Fallback to IP address (proxy-trust aware).
    return f"ip:{get_client_ip(request)}"


def _ip_in_network(ip: str, network: str) -> bool:
    """
    Check if an IP address is within a network range.

    Args:
        ip: IP address string (e.g., "192.168.1.100")
        network: Network in CIDR notation (e.g., "192.168.0.0/16")

    Returns:
        True if IP is in the network, False otherwise
    """
    try:
        ip_obj = ipaddress.ip_address(ip)
        network_obj = ipaddress.ip_network(network, strict=False)
        return ip_obj in network_obj
    except ValueError:
        # Invalid IP or network format
        return False


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

    Note:
        This is a bypass/trust decision, so the client IP is resolved via
        :func:`django_smart_ratelimit.policy.get_client_ip` (proxy-trust aware)
        rather than reading ``REMOTE_ADDR`` directly. CIDR/range matching reuses
        :meth:`django_smart_ratelimit.policy.IPList.contains` so behavior matches
        the rest of the package's allow/deny handling.
    """
    # Lazy import to avoid an import cycle with the policy package.
    from .policy import IPList, get_client_ip

    if internal_ips is None:
        internal_ips = [
            "127.0.0.1",
            "::1",
            "10.0.0.0/8",
            "192.168.0.0/16",
            "172.16.0.0/12",
            "fc00::/7",
            "fe80::/10",
        ]

    client_ip = get_client_ip(request)

    if not client_ip or client_ip == "unknown":
        return False

    try:
        ip_list = IPList(list(internal_ips))
    except ValueError:
        # An invalid entry in internal_ips: fall back to per-entry matching so
        # one bad CIDR does not break the whole check (mirrors prior leniency).
        for internal_ip in internal_ips:
            try:
                if IPList([internal_ip]).contains(client_ip):
                    return True
            except ValueError:
                continue
        return False

    return ip_list.contains(client_ip)


def extract_jwt_claim(request: HttpRequest, claim: str) -> Optional[Any]:
    """
    Extract a specific claim from JWT in Authorization header.

    Args:
        request: Django HTTP request object
        claim: The claim key to extract

    Returns:
        The claim value or None if not found/invalid

    SECURITY WARNING:
        The JWT is decoded with ``verify_signature=False`` — its signature is
        NOT verified and its expiry/audience are NOT checked. The returned claim
        is therefore fully attacker-controllable: a client can forge any value.
        Do NOT use the result for authentication, authorization, or any trust
        decision. It is suitable only as a best-effort rate-limit/identification
        hint, and even then should be paired with the verified ``request.user``
        (populated by your authentication layer) whenever the decision is
        security-relevant. Signature verification must be handled by
        authentication middleware before the claim is trusted.
    """
    try:
        import jwt

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None

        parts = auth_header.split(" ")
        if len(parts) != 2:
            return None

        token = parts[1]
        # Decode without verification as we only need the claim for rate limiting/identification # noqa: E501
        # Verification should be handled by authentication middleware
        decoded = jwt.decode(token, options={"verify_signature": False})

        return decoded.get(claim)

    except (ImportError, Exception):
        return None
