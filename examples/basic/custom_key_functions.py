#!/usr/bin/env python3
"""
Custom Key Functions and Complex Rate Limiting Examples

This demonstrates advanced rate limiting scenarios with custom key functions,
complex business logic, and sophisticated rate limiting strategies.
"""

import re
from urllib.parse import urlparse

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from django_smart_ratelimit import (  # New centralized utilities
    device_fingerprint_key,
    geographic_key,
    get_api_key_key,
    get_device_fingerprint_key,
    get_ip_key,
    get_jwt_key,
    get_tenant_key,
    get_user_key,
    is_authenticated_user,
    rate_limit,
    time_aware_key,
)


# Example 1: Geographic-based rate limiting
# Using centralized geographic_key function
@rate_limit(key=geographic_key, rate="1000/h")
def geographic_api(_request: HttpRequest) -> JsonResponse:
    """
    API with geographic-based rate limiting.

    Different countries may have different rate limits.
    Uses the centralized geographic_key function.
    """
    country_code = _request.headers.get("X-Country-Code", "unknown")

    return JsonResponse(
        {
            "geo_data": "Geographic-based rate limited data",
            "country_code": country_code,
            "rate_limit": "Varies by country",
        }
    )


# Example 2: Device-based rate limiting
# Using centralized device_fingerprint_key function
@rate_limit(key=device_fingerprint_key, rate="500/h")
def device_api(_request: HttpRequest) -> JsonResponse:
    """
    API with device-based rate limiting.

    Each unique device gets its own rate limit.
    Uses the centralized device_fingerprint_key function.
    """
    user_agent = _request.META.get("HTTP_USER_AGENT", "")

    return JsonResponse(
        {
            "device_data": "Device-based rate limited data",
            "user_agent": user_agent,
            "rate_limit": "500 requests per hour per device",
        }
    )


# Example 3: Request size-based rate limiting
def request_size_key_function(_request: HttpRequest) -> str:
    """
    Generate rate limiting key based on _request size.

    This applies different rate limits based on _request payload size.
    """
    content_length = int(_request.META.get("CONTENT_LENGTH", 0))

    # Categorize by _request size
    if content_length == 0:
        size_category = "empty"
    elif content_length < 1024:  # < 1KB
        size_category = "small"
    elif content_length < 1024 * 1024:  # < 1MB
        size_category = "medium"
    else:  # >= 1MB
        size_category = "large"

    ip = _request.META.get("REMOTE_ADDR", "unknown")
    return f"size:{size_category}:ip:{ip}"


@csrf_exempt
@rate_limit(key=request_size_key_function, rate="100/h")
def request_size_api(_request: HttpRequest) -> JsonResponse:
    """
    API with _request size-based rate limiting.

    Different _request sizes get different rate limits.
    """
    content_length = int(_request.META.get("CONTENT_LENGTH", 0))

    # Define size-based limits
    size_limits = {
        "empty": "1000/hour",
        "small": "500/hour",
        "medium": "100/hour",
        "large": "10/hour",
    }

    size_category = "empty"
    if content_length > 0:
        if content_length < 1024:
            size_category = "small"
        elif content_length < 1024 * 1024:
            size_category = "medium"
        else:
            size_category = "large"

    return JsonResponse(
        {
            "size_data": "Size-based rate limited data",
            "content_length": content_length,
            "size_category": size_category,
            "rate_limit": size_limits.get(size_category, "100/hour"),
        }
    )


# Example 4: Time-based rate limiting
# Using centralized time_aware_key function
@rate_limit(key=time_aware_key, rate="500/h")
def time_based_api(_request: HttpRequest) -> JsonResponse:
    """
    API with time-based rate limiting.

    Different time periods get different rate limits.
    Uses the centralized time_aware_key function.
    """
    current_hour = timezone.now().hour

    # Define time-based limits
    time_limits = {
        "morning": "1000/hour",  # Higher limit during business hours
        "afternoon": "1000/hour",
        "evening": "500/hour",
        "night": "200/hour",  # Lower limit at night
    }

    time_period = "night"
    if 6 <= current_hour < 12:
        time_period = "morning"
    elif 12 <= current_hour < 18:
        time_period = "afternoon"
    elif 18 <= current_hour < 22:
        time_period = "evening"

    return JsonResponse(
        {
            "time_data": "Time-based rate limited data",
            "current_hour": current_hour,
            "time_period": time_period,
            "rate_limit": time_limits.get(time_period, "200/hour"),
        }
    )


# Example 5: Referer-based rate limiting
def referer_key_function(_request: HttpRequest) -> str:
    """
    Generate rate limiting key based on HTTP referer.

    This applies different rate limits based on the source of the _request.
    """
    referer = _request.META.get("HTTP_REFERER", "")

    if referer:
        # Parse referer domain
        try:
            parsed_url = urlparse(referer)
            domain = parsed_url.netloc.lower()

            # Clean up domain (remove www, port numbers)
            domain = re.sub(r"^www\.", "", domain)
            domain = re.sub(r":\d+$", "", domain)

            return f"referer:{domain}"
        except:
            pass

    # Fallback to IP-based limiting
    ip = _request.META.get("REMOTE_ADDR", "unknown")
    return f"ip:{ip}"


@rate_limit(key=referer_key_function, rate="1000/h")
def referer_api(_request: HttpRequest) -> JsonResponse:
    """
    API with referer-based rate limiting.

    Different referer domains get different rate limits.
    """
    referer = _request.META.get("HTTP_REFERER", "")

    return JsonResponse(
        {
            "referer_data": "Referer-based rate limited data",
            "referer": referer,
            "rate_limit": "1000 requests per hour per referer domain",
        }
    )


# Example 6: Method-based rate limiting
def method_key_function(_request: HttpRequest) -> str:
    """
    Generate rate limiting key based on HTTP method.

    This applies different rate limits based on the HTTP method.
    """
    method = (_request.method or "GET").upper()
    ip = _request.META.get("REMOTE_ADDR", "unknown")

    return f"method:{method}:ip:{ip}"


@csrf_exempt
@rate_limit(key=method_key_function, rate="200/h")
def method_api(_request: HttpRequest) -> JsonResponse:
    """
    API with method-based rate limiting.

    Different HTTP methods get different rate limits.
    """
    method = (_request.method or "GET").upper()

    # Define method-based limits
    method_limits = {
        "GET": "1000/hour",
        "POST": "200/hour",
        "PUT": "100/hour",
        "DELETE": "50/hour",
        "PATCH": "100/hour",
    }

    return JsonResponse(
        {
            "method_data": f"Method-based rate limited data for {method}",
            "method": method,
            "rate_limit": method_limits.get(method, "200/hour"),
        }
    )


# Example 7: Content-type based rate limiting
def content_type_key_function(_request: HttpRequest) -> str:
    """
    Generate rate limiting key based on content type.

    This applies different rate limits based on _request content type.
    """
    content_type = _request.META.get("CONTENT_TYPE", "").lower()

    # Categorize content types
    if "json" in content_type:
        type_category = "json"
    elif "xml" in content_type:
        type_category = "xml"
    elif "form" in content_type:
        type_category = "form"
    elif "multipart" in content_type:
        type_category = "multipart"
    else:
        type_category = "other"

    ip = _request.META.get("REMOTE_ADDR", "unknown")
    return f"content_type:{type_category}:ip:{ip}"


@csrf_exempt
@rate_limit(key=content_type_key_function, rate="300/h")
def content_type_api(_request: HttpRequest) -> JsonResponse:
    """
    API with content-type based rate limiting.

    Different content types get different rate limits.
    """
    content_type = _request.META.get("CONTENT_TYPE", "")

    # Define content-type based limits
    content_type_limits = {
        "json": "500/hour",
        "xml": "300/hour",
        "form": "400/hour",
        "multipart": "100/hour",  # Lower limit for file uploads
        "other": "200/hour",
    }

    type_category = "other"
    if "json" in content_type.lower():
        type_category = "json"
    elif "xml" in content_type.lower():
        type_category = "xml"
    elif "form" in content_type.lower():
        type_category = "form"
    elif "multipart" in content_type.lower():
        type_category = "multipart"

    return JsonResponse(
        {
            "content_type_data": "Content-type based rate limited data",
            "content_type": content_type,
            "type_category": type_category,
            "rate_limit": content_type_limits.get(type_category, "200/hour"),
        }
    )


# Example 8: Complex business logic rate limiting
def complex_business_key_function(_request: HttpRequest) -> str:
    """
    Generate rate limiting key based on complex business logic.

    This demonstrates combining multiple factors for sophisticated rate limiting.
    """
    # Get various _request attributes
    ip = _request.META.get("REMOTE_ADDR", "unknown")
    user_agent = _request.META.get("HTTP_USER_AGENT", "")
    method = (_request.method or "GET").upper()

    # Check if it's a potential bot
    bot_indicators = ["bot", "crawler", "spider", "scraper"]
    is_bot = any(indicator in user_agent.lower() for indicator in bot_indicators)

    # Check if it's a high-risk IP (in production, use proper IP reputation service)
    high_risk_indicators = _request.headers.get("X-High-Risk", "").lower() == "true"

    # Generate key based on risk level
    if is_bot:
        return f"bot:{ip}"
    elif high_risk_indicators:
        return f"high_risk:{ip}"
    elif method in ["POST", "PUT", "DELETE"]:
        return f"write_method:{ip}"
    else:
        return f"normal:{ip}"


@rate_limit(key=complex_business_key_function, rate="100/h")
def complex_business_api(_request: HttpRequest) -> JsonResponse:
    """
    API with complex business logic rate limiting.

    Different _request types get different rate limits based on risk assessment.
    """
    user_agent = _request.META.get("HTTP_USER_AGENT", "")

    # Assess _request risk
    bot_indicators = ["bot", "crawler", "spider", "scraper"]
    is_bot = any(indicator in user_agent.lower() for indicator in bot_indicators)
    high_risk = _request.headers.get("X-High-Risk", "").lower() == "true"

    # Define risk-based limits
    risk_limits = {
        "bot": "10/hour",
        "high_risk": "50/hour",
        "write_method": "100/hour",
        "normal": "500/hour",
    }

    risk_category = "normal"
    if is_bot:
        risk_category = "bot"
    elif high_risk:
        risk_category = "high_risk"
    elif (_request.method or "GET").upper() in ["POST", "PUT", "DELETE"]:
        risk_category = "write_method"

    return JsonResponse(
        {
            "business_data": "Complex business logic rate limited data",
            "risk_category": risk_category,
            "is_bot": is_bot,
            "high_risk": high_risk,
            "rate_limit": risk_limits.get(risk_category, "100/hour"),
        }
    )


# Example: Using algorithm parameter with custom key functions
@rate_limit(
    key=geographic_key,
    rate="1000/h",
    algorithm="sliding_window",
    skip_if=lambda _request: _request.headers.get("X-Country-Code") == "US",
)
def geographic_api_advanced(_request: HttpRequest) -> JsonResponse:
    """
    Advanced geographic API with sliding window and US bypass.

    Uses sliding window for smooth rate limiting, but bypasses
    rate limiting entirely for US-based requests.
    """
    country_code = _request.headers.get("X-Country-Code", "unknown")
    is_us = country_code == "US"

    return JsonResponse(
        {
            "geo_data": "Advanced geographic rate limiting",
            "country_code": country_code,
            "algorithm": "sliding_window",
            "bypassed": is_us,
            "rate_limit": "No limit for US, 1000/h sliding window for others",
        }
    )


# Example: Device-based with algorithm selection
@rate_limit(
    key=device_fingerprint_key,
    rate="500/h",
    algorithm="fixed_window",
    skip_if=lambda _request: "mobile"
    not in _request.META.get("HTTP_USER_AGENT", "").lower(),
)
def device_api_selective(_request: HttpRequest) -> JsonResponse:
    """
    Device-based rate limiting that only applies to mobile devices.

    Mobile devices are limited to 500 requests per hour using fixed window.
    Desktop/other devices are not rate limited.
    """
    user_agent = _request.META.get("HTTP_USER_AGENT", "")
    is_mobile = "mobile" in user_agent.lower()

    return JsonResponse(
        {
            "device_data": "Device-selective rate limiting",
            "is_mobile": is_mobile,
            "algorithm": "fixed_window",
            "rate_limited": is_mobile,
            "rate_limit": "500/h for mobile, unlimited for desktop",
        }
    )


# =============================================================================
# NEW UTILITY FUNCTION EXAMPLES
# =============================================================================


# Example: JWT-based rate limiting
def jwt_rate_limit_example(_request: HttpRequest) -> str:
    """Rate limit based on JWT subject claim."""
    return get_jwt_key(_request, jwt_field="sub")


@rate_limit(key=jwt_rate_limit_example, rate="100/h")
def jwt_protected_view(_request: HttpRequest) -> JsonResponse:
    """View protected by JWT-based rate limiting."""
    return JsonResponse({"message": "Hello authenticated user!"})


# Example: API Key rate limiting
def api_key_rate_limit_example(_request: HttpRequest) -> str:
    """Rate limit based on API key."""
    return get_api_key_key(_request, header_name="X-API-Key")


@rate_limit(key=api_key_rate_limit_example, rate="1000/h")
def api_endpoint(_request: HttpRequest) -> JsonResponse:
    """API endpoint with API key rate limiting."""
    return JsonResponse({"data": "Your API response"})


# Example: Multi-tenant rate limiting
def tenant_rate_limit_example(_request: HttpRequest) -> str:
    """Rate limit per tenant organization."""
    return get_tenant_key(_request, tenant_field="org_id")


@rate_limit(key=tenant_rate_limit_example, rate="500/h")
def tenant_dashboard(_request: HttpRequest) -> JsonResponse:
    """Tenant dashboard with per-organization limits."""
    return JsonResponse({"tenant_data": "Organization specific data"})


# Example: Device fingerprint rate limiting
@rate_limit(key=get_device_fingerprint_key, rate="50/h")
def public_api(_request: HttpRequest) -> JsonResponse:
    """Public API with device fingerprint rate limiting."""
    return JsonResponse({"public_data": "Publicly available information"})


# Example: Composite key function using utilities
def composite_utility_key(_request: HttpRequest) -> str:
    """
    Composite key that uses multiple utility functions.

    Priority:
    1. API Key (if present)
    2. JWT token (if present)
    3. User ID (if authenticated)
    4. Device fingerprint
    5. IP address (fallback)
    """
    # Try API key first
    try:
        api_key = get_api_key_key(_request)
        if not api_key.startswith("ip:"):  # Check if we got a valid API key
            return api_key
    except:
        pass

    # Try JWT token
    try:
        jwt_key = get_jwt_key(_request)
        if not jwt_key.startswith("ip:"):  # Check if we got a valid JWT
            return jwt_key
    except:
        pass

    # Try authenticated user
    try:
        user_key = get_user_key(_request)
        if not user_key.startswith("ip:"):  # Check if we got a valid user
            return user_key
    except:
        pass

    # Try device fingerprint for anonymous users
    try:
        return get_device_fingerprint_key(_request)
    except:
        # Fallback to IP
        return get_ip_key(_request)


@rate_limit(key=composite_utility_key, rate="200/h")
def smart_rate_limited_view(_request: HttpRequest) -> JsonResponse:
    """View with intelligent composite rate limiting using utilities."""
    return JsonResponse({"message": "Smart rate limiting applied"})


# Example: Role-based rate limiting with utilities
def role_based_utility_key(_request: HttpRequest) -> str:
    """Rate limit based on user role using utility functions."""
    if is_authenticated_user(_request):
        # Check if user is admin/staff
        if _request.user.is_staff:
            return f"admin:{get_user_key(_request)}"
        elif hasattr(_request.user, "subscription_tier"):
            # Premium users get different limits
            tier = getattr(_request.user, "subscription_tier", "basic")
            return f"{tier}:{get_user_key(_request)}"
        else:
            return f"basic:{get_user_key(_request)}"

    # Anonymous users - use device fingerprint if possible
    try:
        return f"anonymous:{get_device_fingerprint_key(_request)}"
    except:
        return f"anonymous:{get_ip_key(_request)}"


@rate_limit(key=role_based_utility_key, rate="1000/h")
def role_protected_api(_request: HttpRequest) -> JsonResponse:
    """API with role-based rate limiting using utilities."""
    return JsonResponse({"role_data": "Role-specific content"})


# Example: Geographic + utility combination
def geographic_utility_key(_request: HttpRequest) -> str:
    """Geographic rate limiting enhanced with utility functions."""
    # Get country from headers (Cloudflare, etc.)
    country = _request.META.get("HTTP_CF_IPCOUNTRY", "unknown")

    # Use the IP utility function for consistent IP extraction
    ip_key = get_ip_key(_request)

    return f"geo:{country}:{ip_key}"


@rate_limit(key=geographic_utility_key, rate="100/h")
def geo_enhanced_content(_request: HttpRequest) -> JsonResponse:
    """Content with enhanced geographic rate limiting."""
    return JsonResponse({"content": "Enhanced geographically rate-limited content"})


# IP reputation service configuration (example)
IP_REPUTATION_SERVICE = {
    "ENABLED": True,
    "API_KEY": "your-api-key-here",
    "THRESHOLD": 0.7,  # Risk threshold
    "CACHE_TIMEOUT": 3600,  # Cache results for 1 hour
}

if __name__ == "__main__":
    print("Custom Key Functions and Complex Rate Limiting Examples")
    print("=" * 60)
    print("This file demonstrates advanced rate limiting with custom key functions.")
    print("Modify the key functions to match your specific business requirements.")
    print("Consider using external services for IP reputation and geolocation.")
