#!/usr/bin/env python3
"""
Advanced Rate Limiting Examples

This demonstrates advanced rate limiting scenarios including
custom key functions, complex business logic, and sophisticated
rate limiting strategies.
"""

import hashlib

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone

from django_smart_ratelimit import is_authenticated_user, rate_limit, tenant_aware_key


# Example 1: API Key-based rate limiting
def api_key_based_key(_request):
    """
    Generate rate limiting key based on API key or fallback to IP.

    This allows different rate limits for different API keys,
    while still protecting against abuse from non-API-key users.
    """
    api_key = _request.headers.get("X-API-Key")
    if api_key:
        # Hash the API key for privacy
        hashed_key = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        return f"api_key:{hashed_key}"
    return f"ip:{_request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=api_key_based_key, rate="1000/h")
def api_with_keys(_request):
    """
    API endpoint that uses API keys for rate limiting.

    Users with valid API keys get higher limits (1000/hour).
    Users without API keys are limited by IP address.
    """
    api_key = _request.headers.get("X-API-Key")

    return JsonResponse(
        {
            "message": "API key-based rate limited endpoint",
            "has_api_key": bool(api_key),
            "rate_limit": "1000/hour with API key, or IP-based limit without",
        }
    )


# Example 2: Tenant-based rate limiting
# Using centralized tenant_aware_key function
@rate_limit(key=tenant_aware_key, rate="10000/h")
def api_tenant_based(_request):
    """
    Multi-tenant API with tenant-specific rate limiting.

    Each tenant gets 10,000 requests per hour.
    Falls back to user or IP-based limiting if no tenant ID.
    Uses the centralized tenant_aware_key function.
    """
    tenant_id = _request.headers.get("X-Tenant-ID")

    return JsonResponse(
        {
            "message": "Tenant-based rate limiting",
            "tenant_id": tenant_id,
            "rate_limit": "10,000/hour per tenant",
        }
    )


# Example 3: Dynamic rate limiting based on user tier
def user_tier_key(_request):
    """
    Generate key that includes user tier for different rate limits.
    """
    if not is_authenticated_user(_request):
        return f"anonymous:{_request.META.get('REMOTE_ADDR', 'unknown')}"

    # Get user tier from profile (example)
    user_tier = getattr(_request.user, "tier", "basic")
    return f"user:{_request.user.id}:tier:{user_tier}"


def get_rate_for_user(_request):
    """
    Dynamically determine rate limit based on user tier.
    """
    if not is_authenticated_user(_request):
        return "10/h"  # Anonymous users

    user_tier = getattr(_request.user, "tier", "basic")
    rate_limits = {"basic": "100/h", "premium": "1000/h", "enterprise": "10000/h"}
    return rate_limits.get(user_tier, "100/h")


@rate_limit(key=user_tier_key, rate=get_rate_for_user)
def api_tiered_access(_request):
    """
    API with different rate limits based on user tier.

    - Anonymous: 10/hour
    - Basic users: 100/hour
    - Premium users: 1,000/hour
    - Enterprise users: 10,000/hour
    """
    if _request.user.is_authenticated:
        tier = getattr(_request.user, "tier", "basic")
        user_info = f"User {_request.user.id} (tier: {tier})"
    else:
        tier = "anonymous"
        user_info = "Anonymous user"

    return JsonResponse(
        {
            "message": "Tiered rate limiting",
            "user": user_info,
            "tier": tier,
            "rate_limit": get_rate_for_user(_request),
        }
    )


# Example 4: Geographic rate limiting
def geographic_key(_request):
    """
    Rate limit based on geographic location.

    This could be useful for preventing abuse from specific regions
    or providing different service levels by geography.
    """
    # Get country from IP (you'd use a GeoIP library in practice)
    country = _request.META.get("HTTP_CF_IPCOUNTRY", "unknown")  # Cloudflare header
    ip = _request.META.get("REMOTE_ADDR", "unknown")
    return f"country:{country}:ip:{ip}"


@rate_limit(key=geographic_key, rate="1000/h")
def api_geographic(_request):
    """
    API with geographic-based rate limiting.

    Rate limits are applied per country per IP address.
    """
    country = _request.META.get("HTTP_CF_IPCOUNTRY", "unknown")

    return JsonResponse(
        {
            "message": "Geographic rate limiting",
            "country": country,
            "rate_limit": "1000/hour per country per IP",
        }
    )


# Example 5: Burst protection with sliding window
@rate_limit(key="ip", rate="100/h", algorithm="sliding_window")  # Long-term limit
@rate_limit(key="ip", rate="10/m", algorithm="sliding_window")  # Burst protection
def api_burst_protection(_request):
    """
    API with both burst protection and long-term limits.

    - Short-term: 10 requests per minute (burst protection)
    - Long-term: 100 requests per hour (overall limit)
    """
    return JsonResponse(
        {
            "message": "Burst protection active",
            "limits": [
                "10 requests per minute (burst protection)",
                "100 requests per hour (long-term limit)",
            ],
        }
    )


# Example 6: Custom rate limiting with business logic
def should_skip_rate_limit(_request):
    """
    Complex business logic to determine if rate limiting should be skipped.
    """
    # Skip for internal services
    if _request.META.get("HTTP_X_INTERNAL_SERVICE") == "true":
        return True

    # Skip for premium users during off-peak hours
    if (
        _request.user.is_authenticated
        and getattr(_request.user, "tier", "basic") == "premium"
    ):
        current_hour = timezone.now().hour
        # Off-peak hours: 10 PM to 6 AM
        if current_hour >= 22 or current_hour <= 6:
            return True

    # Skip for users with recent purchases
    if _request.user.is_authenticated:
        recent_purchase = cache.get(f"recent_purchase:{_request.user.id}")
        if recent_purchase:
            return True

    return False


@rate_limit(key="ip", rate="50/h", skip_if=should_skip_rate_limit)
def api_complex_logic(_request):
    """
    API with complex business logic for rate limiting.

    Rate limiting is skipped for:
    - Internal services
    - Premium users during off-peak hours
    - Users with recent purchases
    """
    skip_reason = None

    if _request.META.get("HTTP_X_INTERNAL_SERVICE") == "true":
        skip_reason = "Internal service"
    elif (
        _request.user.is_authenticated
        and getattr(_request.user, "tier", "basic") == "premium"
    ):
        current_hour = timezone.now().hour
        if current_hour >= 22 or current_hour <= 6:
            skip_reason = "Premium user during off-peak hours"
    elif _request.user.is_authenticated:
        recent_purchase = cache.get(f"recent_purchase:{_request.user.id}")
        if recent_purchase:
            skip_reason = "Recent purchase"

    return JsonResponse(
        {
            "message": "Complex rate limiting logic",
            "rate_limited": skip_reason is None,
            "skip_reason": skip_reason,
            "base_limit": "50/hour per IP",
        }
    )


# Example: Algorithm selection for different use cases
@rate_limit(key="ip", rate="100/h", algorithm="sliding_window")
def api_smooth_limiting(_request):
    """
    API with sliding window algorithm for smooth rate limiting.

    Sliding window provides even distribution of requests across time,
    preventing burst behavior at window boundaries.
    """
    return JsonResponse(
        {
            "message": "Smooth rate limiting with sliding window",
            "algorithm": "sliding_window",
            "behavior": "Even distribution across time window",
        }
    )


@rate_limit(key="ip", rate="100/h", algorithm="fixed_window")
def api_burst_limiting(_request):
    """
    API with fixed window algorithm for burst-tolerant rate limiting.

    Fixed window allows bursts at the beginning of each window,
    which can be useful for batch operations or periodic tasks.
    """
    return JsonResponse(
        {
            "message": "Burst-tolerant rate limiting with fixed window",
            "algorithm": "fixed_window",
            "behavior": "Allows bursts at window start",
        }
    )


# Example: Conditional rate limiting with skip_if
@rate_limit(key="ip", rate="50/h", skip_if=lambda _request: _request.user.is_superuser)
def api_admin_bypass(_request):
    """
    API that bypasses rate limiting for superusers.

    Regular users are limited to 50 requests per hour,
    but superusers have unlimited access.
    """
    user_type = "superuser" if _request.user.is_superuser else "regular"
    is_limited = "No" if _request.user.is_superuser else "Yes (50/hour)"

    return JsonResponse(
        {
            "message": "Admin bypass example",
            "user_type": user_type,
            "rate_limited": is_limited,
        }
    )


# Example: Complex skip_if logic
def should_skip_rate_limit(_request):
    """
    Complex logic to determine if rate limiting should be skipped.

    This could include checking user permissions, API key validity,
    time of day, system load, etc.
    """
    # Skip for staff users
    if _request.user.is_staff:
        return True

    # Skip for internal IP addresses
    ip = _request.META.get("REMOTE_ADDR", "")
    if ip.startswith("192.168.") or ip.startswith("10."):
        return True

    # Skip for requests with valid admin API key
    api_key = _request.headers.get("X-Admin-Key")
    if api_key == "your-admin-key":  # In production, use proper validation
        return True

    # Skip during maintenance windows (example)
    from django.utils import timezone

    hour = timezone.now().hour
    if 2 <= hour <= 4:  # 2-4 AM maintenance window
        return True

    return False


@rate_limit(
    key="ip", rate="20/m", algorithm="sliding_window", skip_if=should_skip_rate_limit
)
def api_complex_bypass(_request):
    """
    API with complex bypass logic.

    Rate limiting can be bypassed based on:
    - User permissions (staff)
    - IP address (internal networks)
    - API key presence
    - Time of day (maintenance window)
    """
    bypass_reasons = []

    if _request.user.is_staff:
        bypass_reasons.append("staff user")

    ip = _request.META.get("REMOTE_ADDR", "")
    if ip.startswith("192.168.") or ip.startswith("10."):
        bypass_reasons.append("internal IP")

    if _request.headers.get("X-Admin-Key"):
        bypass_reasons.append("admin API key")

    from django.utils import timezone

    hour = timezone.now().hour
    if 2 <= hour <= 4:
        bypass_reasons.append("maintenance window")

    return JsonResponse(
        {
            "message": "Complex bypass logic",
            "rate_limited": "No" if bypass_reasons else "Yes (20/min)",
            "bypass_reasons": bypass_reasons,
            "algorithm": "sliding_window",
        }
    )


if __name__ == "__main__":
    print("Advanced Rate Limiting Examples")
    print("===============================")
    print("")
    print("This file contains examples of advanced rate limiting patterns:")
    print("1. API key-based rate limiting")
    print("2. Multi-tenant rate limiting")
    print("3. Dynamic rate limits based on user tier")
    print("4. Geographic rate limiting")
    print("5. Burst protection with multiple time windows")
    print("6. Complex business logic for conditional rate limiting")
    print("")
    print("These examples show how to implement sophisticated rate limiting")
    print("strategies for complex applications and business requirements.")
