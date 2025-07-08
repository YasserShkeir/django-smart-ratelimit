#!/usr/bin/env python3
"""
Multi-tenant Rate Limiting Examples

This demonstrates rate limiting in multi-tenant applications,
including tenant-based limits, tenant quotas, and hierarchical
rate limiting strategies.
"""

import hashlib
from datetime import timedelta

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django_smart_ratelimit import rate_limit


# Example 1: Basic tenant-based rate limiting
def tenant_key_function(request):
    """
    Generate rate limiting key based on tenant ID.

    This allows different rate limits for different tenants
    while providing fallback to user or IP-based limiting.
    """
    tenant_id = request.headers.get("X-Tenant-ID")
    if tenant_id:
        return f"tenant:{tenant_id}"

    # Fallback to user-based limiting
    if request.user.is_authenticated:
        return f"user:{request.user.id}"

    # Final fallback to IP-based limiting
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=tenant_key_function, rate="500/h")
def tenant_api(request):
    """
    Multi-tenant API with tenant-specific rate limiting.

    Each tenant gets 500 requests per hour.
    """
    tenant_id = request.headers.get("X-Tenant-ID")

    return JsonResponse(
        {
            "tenant_data": "Tenant-specific data",
            "tenant_id": tenant_id,
            "rate_limit": "500 requests per hour per tenant",
        }
    )


# Example 2: Tenant quota-based rate limiting
def tenant_quota_key(request):
    """
    Generate rate limiting key based on tenant quota tier.

    This allows different rate limits based on tenant subscription levels.
    """
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

    # Get tenant quota tier (in production, this would come from database)
    quota_tier = request.headers.get("X-Tenant-Quota", "basic")

    return f"tenant:{tenant_id}:quota:{quota_tier}"


@rate_limit(key=tenant_quota_key, rate="10000/h")  # Enterprise tier
def tenant_quota_api(request):
    """
    Tenant API with quota-based rate limiting.

    Different quota tiers get different rate limits:
    - Basic: 1000/hour
    - Professional: 5000/hour
    - Enterprise: 10000/hour
    """
    tenant_id = request.headers.get("X-Tenant-ID")
    quota_tier = request.headers.get("X-Tenant-Quota", "basic")

    # Define quota limits
    quota_limits = {
        "basic": "1000/hour",
        "professional": "5000/hour",
        "enterprise": "10000/hour",
    }

    return JsonResponse(
        {
            "tenant_data": "Quota-based tenant data",
            "tenant_id": tenant_id,
            "quota_tier": quota_tier,
            "rate_limit": quota_limits.get(quota_tier, "1000/hour"),
        }
    )


# Example 3: Hierarchical tenant rate limiting
def hierarchical_tenant_key(request):
    """
    Generate hierarchical rate limiting key for tenant organizations.

    This supports rate limiting at multiple levels:
    - Organization level
    - Tenant level within organization
    - User level within tenant
    """
    org_id = request.headers.get("X-Organization-ID")
    tenant_id = request.headers.get("X-Tenant-ID")

    if org_id and tenant_id:
        if request.user.is_authenticated:
            return f"org:{org_id}:tenant:{tenant_id}:user:{request.user.id}"
        else:
            return f"org:{org_id}:tenant:{tenant_id}"
    elif tenant_id:
        return f"tenant:{tenant_id}"
    elif request.user.is_authenticated:
        return f"user:{request.user.id}"
    else:
        return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=hierarchical_tenant_key, rate="2000/h")
def hierarchical_tenant_api(request):
    """
    API with hierarchical tenant rate limiting.

    Rate limits apply at multiple levels of the tenant hierarchy.
    """
    org_id = request.headers.get("X-Organization-ID")
    tenant_id = request.headers.get("X-Tenant-ID")

    return JsonResponse(
        {
            "hierarchical_data": "Multi-level tenant data",
            "organization_id": org_id,
            "tenant_id": tenant_id,
            "user_id": request.user.id if request.user.is_authenticated else None,
            "rate_limit": "2000 requests per hour at tenant level",
        }
    )


# Example 4: Tenant-specific feature rate limiting
def tenant_feature_key(request):
    """
    Generate rate limiting key for tenant-specific features.

    This allows different rate limits for different features
    within the same tenant.
    """
    tenant_id = request.headers.get("X-Tenant-ID")
    feature = request.headers.get("X-Feature", "default")

    if tenant_id:
        return f"tenant:{tenant_id}:feature:{feature}"
    else:
        return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}:feature:{feature}"


@rate_limit(key=tenant_feature_key, rate="100/h")
def tenant_feature_api(request):
    """
    API with tenant-specific feature rate limiting.

    Different features have different rate limits within the same tenant.
    """
    tenant_id = request.headers.get("X-Tenant-ID")
    feature = request.headers.get("X-Feature", "default")

    # Define feature-specific limits
    feature_limits = {
        "analytics": "50/hour",
        "exports": "20/hour",
        "imports": "10/hour",
        "reports": "100/hour",
        "default": "100/hour",
    }

    return JsonResponse(
        {
            "feature_data": f"Data for {feature} feature",
            "tenant_id": tenant_id,
            "feature": feature,
            "rate_limit": feature_limits.get(feature, "100/hour"),
        }
    )


# Example 5: Tenant API key-based rate limiting
def tenant_api_key_function(request):
    """
    Generate rate limiting key based on tenant API key.

    This allows rate limiting based on API keys that belong to tenants.
    """
    api_key = request.headers.get("X-API-Key")

    if api_key:
        # Hash the API key for privacy
        hashed_key = hashlib.sha256(api_key.encode()).hexdigest()[:16]

        # In production, look up tenant from API key in database
        # For example purposes, we'll extract tenant from a header
        tenant_id = request.headers.get("X-Tenant-ID")
        if tenant_id:
            return f"api_key:{hashed_key}:tenant:{tenant_id}"
        else:
            return f"api_key:{hashed_key}"

    # Fallback to IP-based limiting
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=tenant_api_key_function, rate="5000/h")
def tenant_api_key_endpoint(request):
    """
    Tenant API endpoint that uses API keys for rate limiting.

    Each tenant's API key gets its own rate limit.
    """
    api_key = request.headers.get("X-API-Key")
    tenant_id = request.headers.get("X-Tenant-ID")

    return JsonResponse(
        {
            "api_key_data": "API key-based tenant data",
            "tenant_id": tenant_id,
            "has_api_key": bool(api_key),
            "rate_limit": "5000 requests per hour per tenant API key",
        }
    )


# Example 6: Tenant subdomain-based rate limiting
def tenant_subdomain_key(request):
    """
    Generate rate limiting key based on tenant subdomain.

    This extracts tenant information from the subdomain.
    """
    host = request.get_host()

    # Extract tenant from subdomain (e.g., tenant1.example.com)
    if "." in host:
        subdomain = host.split(".")[0]

        # Skip common subdomains
        if subdomain not in ["www", "api", "admin"]:
            return f"subdomain:{subdomain}"

    # Fallback to IP-based limiting
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=tenant_subdomain_key, rate="1000/h")
def tenant_subdomain_api(request):
    """
    API with subdomain-based tenant rate limiting.

    Each tenant subdomain gets its own rate limit.
    """
    host = request.get_host()
    subdomain = host.split(".")[0] if "." in host else "unknown"

    return JsonResponse(
        {
            "subdomain_data": "Subdomain-based tenant data",
            "host": host,
            "tenant_subdomain": subdomain,
            "rate_limit": "1000 requests per hour per tenant subdomain",
        }
    )


# Example 7: Tenant usage tracking with rate limiting
@csrf_exempt
@require_http_methods(["GET", "POST"])
def tenant_usage_tracking(request):
    """
    Tenant usage tracking endpoint with rate limiting.

    This endpoint tracks tenant usage while applying rate limits.
    """
    tenant_id = request.headers.get("X-Tenant-ID")

    if not tenant_id:
        return JsonResponse({"error": "Tenant ID required"}, status=400)

    # Track usage in cache (in production, use proper storage)
    cache_key = f"tenant_usage:{tenant_id}:{timezone.now().date()}"
    current_usage = cache.get(cache_key, 0)

    # Apply rate limit using decorator
    @rate_limit(key=lambda req: f"usage:tenant:{tenant_id}", rate="1000/h")
    def process_request(req):
        # Increment usage counter
        cache.set(cache_key, current_usage + 1, timeout=86400)  # 24 hours

        return JsonResponse(
            {
                "usage_data": "Tenant usage tracked",
                "tenant_id": tenant_id,
                "daily_usage": current_usage + 1,
                "rate_limit": "1000 requests per hour for usage tracking",
            }
        )

    return process_request(request)


# Example: Tenant rate limiting with algorithm and skip_if
@rate_limit(
    key=tenant_key_function,
    rate="500/h",
    algorithm="sliding_window",
    skip_if=lambda request: request.headers.get("X-Tenant-ID") == "premium-tenant",
)
def tenant_api_advanced(request):
    """
    Advanced tenant API with sliding window and premium tenant bypass.

    Uses sliding window for smooth rate limiting, but bypasses
    rate limiting for premium tenants.
    """
    tenant_id = request.headers.get("X-Tenant-ID")
    is_premium = tenant_id == "premium-tenant"

    return JsonResponse(
        {
            "tenant_data": "Advanced tenant rate limiting",
            "tenant_id": tenant_id,
            "algorithm": "sliding_window",
            "bypassed": is_premium,
            "rate_limit": "No limit for premium, 500/h sliding window for others",
        }
    )


# Example: Hierarchical tenant with algorithm selection
@rate_limit(
    key=hierarchical_tenant_key,
    rate="2000/h",
    algorithm="fixed_window",
    skip_if=lambda request: request.headers.get("X-Organization-ID")
    == "enterprise-org",
)
def hierarchical_tenant_api_advanced(request):
    """
    Advanced hierarchical tenant API with fixed window and enterprise bypass.

    Uses fixed window to allow burst requests for batch operations.
    Enterprise organizations bypass rate limiting entirely.
    """
    org_id = request.headers.get("X-Organization-ID")
    tenant_id = request.headers.get("X-Tenant-ID")
    is_enterprise = org_id == "enterprise-org"

    return JsonResponse(
        {
            "hierarchical_data": "Advanced multi-level tenant data",
            "organization_id": org_id,
            "tenant_id": tenant_id,
            "user_id": request.user.id if request.user.is_authenticated else None,
            "algorithm": "fixed_window",
            "bypassed": is_enterprise,
            "rate_limit": "No limit for enterprise, 2000/h fixed window for others",
        }
    )


# Django URLs configuration example
"""
# urls.py

from django.urls import path
from . import tenant_rate_limiting

urlpatterns = [
    # Tenant-based rate limiting
    path('api/tenant/basic/', tenant_rate_limiting.tenant_api, name='tenant_basic'),
    path('api/tenant/quota/', tenant_rate_limiting.tenant_quota_api, name='tenant_quota'),
    path('api/tenant/hierarchical/', tenant_rate_limiting.hierarchical_tenant_api, name='tenant_hierarchical'),
    path('api/tenant/feature/', tenant_rate_limiting.tenant_feature_api, name='tenant_feature'),
    path('api/tenant/api-key/', tenant_rate_limiting.tenant_api_key_endpoint, name='tenant_api_key'),
    path('api/tenant/subdomain/', tenant_rate_limiting.tenant_subdomain_api, name='tenant_subdomain'),
    path('api/tenant/usage/', tenant_rate_limiting.tenant_usage_tracking, name='tenant_usage'),
]
"""

# Django settings configuration example
"""
# settings.py

# Multi-tenant rate limiting configuration
RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '100/h',
    'BACKEND': 'redis',
    'BLOCK': True,
    'RATE_LIMITS': {
        # Tenant-based endpoints with different limits
        '/api/tenant/basic/': '500/h',
        '/api/tenant/quota/': '10000/h',  # Will be limited by quota tier
        '/api/tenant/hierarchical/': '2000/h',
        '/api/tenant/feature/': '100/h',  # Will be limited by feature
        '/api/tenant/api-key/': '5000/h',
        '/api/tenant/subdomain/': '1000/h',
        '/api/tenant/usage/': '1000/h',
    },
}

# Cache configuration for tenant usage tracking
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}
"""

if __name__ == "__main__":
    print("Multi-tenant Rate Limiting Examples")
    print("=" * 40)
    print("This file demonstrates multi-tenant rate limiting patterns.")
    print("Configure tenant identification in your middleware or headers.")
    print("Use Redis cache for tenant usage tracking in production.")
