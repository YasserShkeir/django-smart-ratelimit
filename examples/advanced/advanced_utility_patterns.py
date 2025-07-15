"""
Advanced utility usage patterns and real-world examples.

This module demonstrates practical applications of the utility functions
in complex scenarios and production-ready implementations.
"""

import logging

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django_smart_ratelimit import (
    RateLimitMiddleware,
    get_api_key_key,
    get_client_identifier,
    get_device_fingerprint_key,
    get_ip_key,
    get_jwt_key,
    is_exempt_request,
    rate_limit,
)

logger = logging.getLogger(__name__)


# =============================================================================
# PRODUCTION-READY KEY FUNCTIONS
# =============================================================================


def intelligent_api_key(_request: HttpRequest) -> str:
    """
    Production-ready API key function with comprehensive fallback strategy.

    Priority:
    1. API Key from multiple possible headers
    2. JWT token (if valid)
    3. Authenticated user (with role consideration)
    4. Session-based (for web apps)
    5. Device fingerprint (for anonymous tracking)
    6. IP address (ultimate fallback)
    """
    # Try multiple API key headers
    api_headers = ["X-API-Key", "Authorization", "X-Auth-Token"]
    for header in api_headers:
        try:
            api_key = get_api_key_key(_request, header_name=header)
            if not api_key.startswith("ip:"):
                logger.debug(f"Using API key from {header}")
                return api_key
        except Exception:
            continue

    # Try JWT token
    try:
        jwt_key = get_jwt_key(_request, jwt_field="sub")
        if not jwt_key.startswith("ip:"):
            logger.debug("Using JWT-based key")
            return jwt_key
    except Exception:
        pass

    # Try authenticated user with role
    if hasattr(_request, "user") and _request.user.is_authenticated:
        role = "admin" if _request.user.is_staff else "user"
        logger.debug(f"Using authenticated user key with role: {role}")
        return f"{role}:user:{_request.user.id}"

    # Try session for web applications
    if hasattr(_request, "session") and _request.session.session_key:
        logger.debug("Using session-based key")
        return f"session:{_request.session.session_key}"

    # Try device fingerprint for anonymous users
    try:
        device_key = get_device_fingerprint_key(_request)
        logger.debug("Using device fingerprint")
        return device_key
    except Exception:
        pass

    # Ultimate fallback to IP
    logger.debug("Falling back to IP-based key")
    return get_ip_key(_request)


def security_aware_key(_request: HttpRequest) -> str:
    """
    Security-focused key function that considers threat indicators.

    This function implements additional security checks and can apply
    different rate limits based on threat assessment.
    """
    ip_key = get_ip_key(_request)
    user_agent = _request.META.get("HTTP_USER_AGENT", "")

    # Check for suspicious patterns
    suspicious_indicators = [
        "bot",
        "crawler",
        "scraper",
        "scan",
        "hack",
        "exploit",
        "attack",
        "malware",
        "virus",
    ]

    is_suspicious = any(
        indicator in user_agent.lower() for indicator in suspicious_indicators
    )

    # Check for missing or suspicious headers
    missing_headers = not all(
        [
            _request.META.get("HTTP_USER_AGENT"),
            _request.META.get("HTTP_ACCEPT"),
            _request.META.get("HTTP_ACCEPT_LANGUAGE"),
        ]
    )

    if is_suspicious or missing_headers:
        logger.warning(f"Suspicious _request detected from {ip_key}")
        return f"suspicious:{ip_key}"

    # For normal requests, use standard identification
    if hasattr(_request, "user") and _request.user.is_authenticated:
        return f"trusted:user:{_request.user.id}"

    return f"normal:{ip_key}"


def business_tier_key(_request: HttpRequest) -> str:
    """
    Business logic-aware key function for SaaS applications.

    Implements different rate limits based on:
    - Subscription tier
    - Account status
    - Usage quotas
    - Special privileges
    """
    if hasattr(_request, "user") and _request.user.is_authenticated:
        user = _request.user

        # Check for admin/staff privileges
        if user.is_staff or user.is_superuser:
            return f"staff:user:{user.id}"

        # Check subscription tier (assuming a profile model)
        if hasattr(user, "profile"):
            profile = user.profile
            tier = getattr(profile, "subscription_tier", "free")

            # Check account status
            is_suspended = getattr(profile, "is_suspended", False)
            if is_suspended:
                return f"suspended:user:{user.id}"

            # Check if user has exceeded quotas
            usage_percent = getattr(profile, "usage_percent", 0)
            if usage_percent > 95:
                return f"quota_exceeded:{tier}:user:{user.id}"

            return f"{tier}:user:{user.id}"

        # Default authenticated user
        return f"basic:user:{user.id}"

    # Anonymous users get device fingerprint if possible
    try:
        return f"anonymous:{get_device_fingerprint_key(_request)}"
    except Exception:
        return f"anonymous:{get_ip_key(_request)}"


def multi_tenant_key(_request: HttpRequest) -> str:
    """
    Multi-tenant application key function.

    Handles rate limiting in multi-tenant SaaS applications where
    limits should be applied per tenant organization.
    """
    # Try to get tenant from various sources
    tenant_id = None

    # Method 1: From URL parameters
    tenant_id = _request.GET.get("tenant_id") or _request.GET.get("org_id")

    # Method 2: From custom headers
    if not tenant_id:
        tenant_id = _request.META.get("HTTP_X_TENANT_ID")

    # Method 3: From subdomain
    if not tenant_id:
        host = _request.META.get("HTTP_HOST", "")
        if "." in host:
            subdomain = host.split(".")[0]
            if subdomain and subdomain != "www":
                tenant_id = subdomain

    # Method 4: From user's organization
    if not tenant_id and hasattr(_request, "user") and _request.user.is_authenticated:
        if hasattr(_request.user, "organization"):
            tenant_id = _request.user.organization.id

    if tenant_id:
        # Include user context within tenant
        if hasattr(_request, "user") and _request.user.is_authenticated:
            return f"tenant:{tenant_id}:user:{_request.user.id}"
        else:
            # Anonymous user within tenant
            return f"tenant:{tenant_id}:{get_ip_key(_request)}"

    # No tenant context - fall back to standard key
    return get_client_identifier(_request, "auto")


# =============================================================================
# ADVANCED DECORATORS WITH UTILITY INTEGRATION
# =============================================================================


@rate_limit(key=intelligent_api_key, rate="1000/h")
@csrf_exempt
@require_http_methods(["GET", "POST"])
def intelligent_api_endpoint(_request):
    """
    API endpoint with intelligent rate limiting that adapts to different
    authentication methods and user types.
    """
    return JsonResponse(
        {
            "message": "API response with intelligent rate limiting",
            "key_type": "intelligent",
            "timestamp": "2024-01-01T00:00:00Z",
        }
    )


@rate_limit(key=security_aware_key, rate="100/h")
def security_focused_api(_request):
    """
    API endpoint with security-aware rate limiting that applies
    stricter limits to suspicious requests.
    """
    key = security_aware_key(_request)

    # Adjust response based on threat level
    if key.startswith("suspicious:"):
        return JsonResponse(
            {
                "message": "Limited access due to security assessment",
                "status": "restricted",
            },
            status=200,
        )

    return JsonResponse({"message": "Full access granted", "status": "normal"})


@rate_limit(
    key=business_tier_key,
    rate="500/h",
    algorithm="token_bucket",
    algorithm_config={"bucket_size": 1000},
)
def business_api_endpoint(_request):
    """
    Business API with tier-based rate limiting and token bucket
    for burst handling in premium tiers.
    """
    return JsonResponse(
        {"message": "Business API response", "features": "full", "tier": "premium"}
    )


@rate_limit(key=multi_tenant_key, rate="2000/h")
def tenant_api_endpoint(_request):
    """
    Multi-tenant API endpoint where rate limits are applied
    per tenant organization.
    """
    return JsonResponse(
        {"message": "Tenant-specific API response", "isolation": "per_tenant"}
    )


# =============================================================================
# MIDDLEWARE INTEGRATION EXAMPLES
# =============================================================================


class EnhancedRateLimitMiddleware(RateLimitMiddleware):
    """
    Enhanced middleware that uses utility functions for more
    sophisticated rate limiting logic.
    """

    def __call__(self, _request):
        # Check for exemptions using utility function
        exempt_paths = ["/health/", "/metrics/", "/admin/"]
        exempt_ips = ["127.0.0.1", "::1"]  # localhost

        if is_exempt_request(_request, exempt_paths, exempt_ips):
            return self.get_response(_request)

        # Use intelligent key generation
        _request._rate_limit_key = intelligent_api_key(_request)

        # Apply different rates based on endpoint type
        if _request.path.startswith("/api/v1/"):
            rate = "1000/h"
        elif _request.path.startswith("/api/v2/"):
            rate = "2000/h"  # Higher limits for newer API
        elif _request.path.startswith("/auth/"):
            rate = "10/m"  # Stricter for auth endpoints
        else:
            self.default_rate

        # Continue with standard middleware processing
        return super().__call__(_request)


# =============================================================================
# CONDITIONAL RATE LIMITING
# =============================================================================


def conditional_rate_limit_key(_request: HttpRequest) -> str:
    """
    Conditional rate limiting based on _request characteristics.
    """
    # Different limits for different HTTP methods
    method = _request.method

    if method in ["POST", "PUT", "PATCH", "DELETE"]:
        # Stricter limits for write operations
        prefix = "write"
    else:
        # More lenient for read operations
        prefix = "read"

    base_key = get_client_identifier(_request, "auto")
    return f"{prefix}:{base_key}"


@rate_limit(key=conditional_rate_limit_key, rate="100/h")
def crud_api_endpoint(_request):
    """
    CRUD API with different rate limits for read vs write operations.
    """
    if _request.method == "GET":
        return JsonResponse({"data": "read operation"})
    else:
        return JsonResponse({"status": "write operation completed"})


# =============================================================================
# TIME-BASED DYNAMIC RATE LIMITING
# =============================================================================


def time_based_key(_request: HttpRequest) -> str:
    """
    Time-based rate limiting that adjusts based on time of day.
    """
    from datetime import datetime

    import pytz

    # Get current hour in UTC
    now = datetime.now(pytz.UTC)
    hour = now.hour

    # Business hours (9 AM - 5 PM UTC)
    if 9 <= hour <= 17:
        time_prefix = "business_hours"
    # Peak hours (6 PM - 10 PM UTC)
    elif 18 <= hour <= 22:
        time_prefix = "peak_hours"
    # Off hours
    else:
        time_prefix = "off_hours"

    base_key = get_client_identifier(_request, "auto")
    return f"{time_prefix}:{base_key}"


# Note: You would typically apply different rates based on time
@rate_limit(key=time_based_key, rate="200/h")
def time_sensitive_api(_request):
    """
    API with time-based rate limiting adjustments.
    """
    return JsonResponse(
        {"message": "Time-aware rate limiting applied", "hour": "current_hour_info"}
    )


# =============================================================================
# GEOGRAPHIC RATE LIMITING
# =============================================================================


def geographic_rate_limit_key(_request: HttpRequest) -> str:
    """
    Geographic rate limiting using various IP geolocation sources.
    """
    # Try Cloudflare country header
    country = _request.META.get("HTTP_CF_IPCOUNTRY")

    # Try other common headers
    if not country:
        country = _request.META.get("HTTP_X_COUNTRY_CODE")

    # Default to unknown
    if not country:
        country = "unknown"

    base_key = get_ip_key(_request)
    return f"geo:{country}:{base_key}"


@rate_limit(key=geographic_rate_limit_key, rate="500/h")
def geo_aware_api(_request):
    """
    API with geographic rate limiting considerations.
    """
    country = _request.META.get("HTTP_CF_IPCOUNTRY", "unknown")

    return JsonResponse(
        {
            "message": "Geographic rate limiting applied",
            "country": country,
            "status": "success",
        }
    )


# =============================================================================
# USAGE TRACKING AND ANALYTICS
# =============================================================================


def analytics_aware_key(_request: HttpRequest) -> str:
    """
    Key function that enables usage analytics and tracking.
    """
    base_key = get_client_identifier(_request, "auto")

    # Add _request tracking info
    endpoint = _request.path.split("/")[1] if _request.path != "/" else "root"
    method = _request.method.lower()

    # Create composite key for analytics
    analytics_key = f"analytics:{endpoint}:{method}:{base_key}"

    # Log for analytics (in production, send to analytics service)
    logger.info(f"API Request: {analytics_key}")

    return analytics_key


@rate_limit(key=analytics_aware_key, rate="1000/h")
def analytics_tracked_api(_request):
    """
    API endpoint with built-in usage analytics tracking.
    """
    return JsonResponse({"message": "Request tracked for analytics", "tracked": True})
