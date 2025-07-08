#!/usr/bin/env python3
"""
Custom Key Functions and Complex Rate Limiting Examples

This demonstrates advanced rate limiting scenarios with custom key functions,
complex business logic, and sophisticated rate limiting strategies.
"""

import hashlib
import re
from datetime import timedelta
from urllib.parse import urlparse

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django_smart_ratelimit import rate_limit


# Example 1: Geographic-based rate limiting
def geographic_key_function(request):
    """
    Generate rate limiting key based on geographic location.

    This uses IP geolocation to apply different rate limits
    based on the user's location.
    """
    ip = request.META.get("REMOTE_ADDR", "unknown")

    # Get country from IP (in production, use a geolocation service)
    country_code = request.headers.get("X-Country-Code", "unknown")

    # Apply different limits based on country
    if country_code:
        return f"geo:{country_code}:ip:{ip}"
    else:
        return f"ip:{ip}"


@rate_limit(key=geographic_key_function, rate="1000/h")
def geographic_api(request):
    """
    API with geographic-based rate limiting.

    Different countries may have different rate limits.
    """
    country_code = request.headers.get("X-Country-Code", "unknown")

    return JsonResponse(
        {
            "geo_data": "Geographic-based rate limited data",
            "country_code": country_code,
            "rate_limit": "Varies by country",
        }
    )


# Example 2: Device-based rate limiting
def device_key_function(request):
    """
    Generate rate limiting key based on device fingerprint.

    This creates a device fingerprint from User-Agent and other headers.
    """
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    accept_language = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    accept_encoding = request.META.get("HTTP_ACCEPT_ENCODING", "")

    # Create device fingerprint
    device_string = f"{user_agent}:{accept_language}:{accept_encoding}"
    device_hash = hashlib.md5(device_string.encode()).hexdigest()[:16]

    # Include IP for additional uniqueness
    ip = request.META.get("REMOTE_ADDR", "unknown")

    return f"device:{device_hash}:ip:{ip}"


@rate_limit(key=device_key_function, rate="500/h")
def device_api(request):
    """
    API with device-based rate limiting.

    Each unique device gets its own rate limit.
    """
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    return JsonResponse(
        {
            "device_data": "Device-based rate limited data",
            "user_agent": user_agent,
            "rate_limit": "500 requests per hour per device",
        }
    )


# Example 3: Request size-based rate limiting
def request_size_key_function(request):
    """
    Generate rate limiting key based on request size.

    This applies different rate limits based on request payload size.
    """
    content_length = int(request.META.get("CONTENT_LENGTH", 0))

    # Categorize by request size
    if content_length == 0:
        size_category = "empty"
    elif content_length < 1024:  # < 1KB
        size_category = "small"
    elif content_length < 1024 * 1024:  # < 1MB
        size_category = "medium"
    else:  # >= 1MB
        size_category = "large"

    ip = request.META.get("REMOTE_ADDR", "unknown")
    return f"size:{size_category}:ip:{ip}"


@csrf_exempt
@rate_limit(key=request_size_key_function, rate="100/h")
def request_size_api(request):
    """
    API with request size-based rate limiting.

    Different request sizes get different rate limits.
    """
    content_length = int(request.META.get("CONTENT_LENGTH", 0))

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
def time_based_key_function(request):
    """
    Generate rate limiting key based on time of day.

    This applies different rate limits based on the current time.
    """
    current_hour = timezone.now().hour

    # Define time periods
    if 6 <= current_hour < 12:
        time_period = "morning"
    elif 12 <= current_hour < 18:
        time_period = "afternoon"
    elif 18 <= current_hour < 22:
        time_period = "evening"
    else:
        time_period = "night"

    ip = request.META.get("REMOTE_ADDR", "unknown")
    return f"time:{time_period}:ip:{ip}"


@rate_limit(key=time_based_key_function, rate="500/h")
def time_based_api(request):
    """
    API with time-based rate limiting.

    Different time periods get different rate limits.
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
def referer_key_function(request):
    """
    Generate rate limiting key based on HTTP referer.

    This applies different rate limits based on the source of the request.
    """
    referer = request.META.get("HTTP_REFERER", "")

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
    ip = request.META.get("REMOTE_ADDR", "unknown")
    return f"ip:{ip}"


@rate_limit(key=referer_key_function, rate="1000/h")
def referer_api(request):
    """
    API with referer-based rate limiting.

    Different referer domains get different rate limits.
    """
    referer = request.META.get("HTTP_REFERER", "")

    return JsonResponse(
        {
            "referer_data": "Referer-based rate limited data",
            "referer": referer,
            "rate_limit": "1000 requests per hour per referer domain",
        }
    )


# Example 6: Method-based rate limiting
def method_key_function(request):
    """
    Generate rate limiting key based on HTTP method.

    This applies different rate limits based on the HTTP method.
    """
    method = request.method.upper()
    ip = request.META.get("REMOTE_ADDR", "unknown")

    return f"method:{method}:ip:{ip}"


@csrf_exempt
@rate_limit(key=method_key_function, rate="200/h")
def method_api(request):
    """
    API with method-based rate limiting.

    Different HTTP methods get different rate limits.
    """
    method = request.method.upper()

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
def content_type_key_function(request):
    """
    Generate rate limiting key based on content type.

    This applies different rate limits based on request content type.
    """
    content_type = request.META.get("CONTENT_TYPE", "").lower()

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

    ip = request.META.get("REMOTE_ADDR", "unknown")
    return f"content_type:{type_category}:ip:{ip}"


@csrf_exempt
@rate_limit(key=content_type_key_function, rate="300/h")
def content_type_api(request):
    """
    API with content-type based rate limiting.

    Different content types get different rate limits.
    """
    content_type = request.META.get("CONTENT_TYPE", "")

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
def complex_business_key_function(request):
    """
    Generate rate limiting key based on complex business logic.

    This demonstrates combining multiple factors for sophisticated rate limiting.
    """
    # Get various request attributes
    ip = request.META.get("REMOTE_ADDR", "unknown")
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    method = request.method.upper()

    # Check if it's a potential bot
    bot_indicators = ["bot", "crawler", "spider", "scraper"]
    is_bot = any(indicator in user_agent.lower() for indicator in bot_indicators)

    # Check if it's a high-risk IP (in production, use proper IP reputation service)
    high_risk_indicators = request.headers.get("X-High-Risk", "").lower() == "true"

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
def complex_business_api(request):
    """
    API with complex business logic rate limiting.

    Different request types get different rate limits based on risk assessment.
    """
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    # Assess request risk
    bot_indicators = ["bot", "crawler", "spider", "scraper"]
    is_bot = any(indicator in user_agent.lower() for indicator in bot_indicators)
    high_risk = request.headers.get("X-High-Risk", "").lower() == "true"

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
    elif request.method.upper() in ["POST", "PUT", "DELETE"]:
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
    key=geographic_key_function,
    rate="1000/h",
    algorithm="sliding_window",
    skip_if=lambda request: request.headers.get("X-Country-Code") == "US",
)
def geographic_api_advanced(request):
    """
    Advanced geographic API with sliding window and US bypass.

    Uses sliding window for smooth rate limiting, but bypasses
    rate limiting entirely for US-based requests.
    """
    country_code = request.headers.get("X-Country-Code", "unknown")
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
    key=device_key_function,
    rate="500/h",
    algorithm="fixed_window",
    skip_if=lambda request: "mobile"
    not in request.META.get("HTTP_USER_AGENT", "").lower(),
)
def device_api_selective(request):
    """
    Device-based rate limiting that only applies to mobile devices.

    Mobile devices are limited to 500 requests per hour using fixed window.
    Desktop/other devices are not rate limited.
    """
    user_agent = request.META.get("HTTP_USER_AGENT", "")
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


# Django URLs configuration example
"""
# urls.py

from django.urls import path
from . import custom_key_examples

urlpatterns = [
    # Custom key function examples
    path('api/custom/geographic/', custom_key_examples.geographic_api, name='custom_geographic'),
    path('api/custom/device/', custom_key_examples.device_api, name='custom_device'),
    path('api/custom/request-size/', custom_key_examples.request_size_api, name='custom_request_size'),
    path('api/custom/time-based/', custom_key_examples.time_based_api, name='custom_time_based'),
    path('api/custom/referer/', custom_key_examples.referer_api, name='custom_referer'),
    path('api/custom/method/', custom_key_examples.method_api, name='custom_method'),
    path('api/custom/content-type/', custom_key_examples.content_type_api, name='custom_content_type'),
    path('api/custom/business-logic/', custom_key_examples.complex_business_api, name='custom_business_logic'),
    path('api/custom/geographic-advanced/', custom_key_examples.geographic_api_advanced, name='custom_geographic_advanced'),
    path('api/custom/device-selective/', custom_key_examples.device_api_selective, name='custom_device_selective'),
]
"""

# Django settings configuration example
"""
# settings.py

# Custom key function rate limiting configuration
RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '100/h',
    'BACKEND': 'redis',
    'BLOCK': True,
    'RATE_LIMITS': {
        # Custom key function endpoints
        '/api/custom/geographic/': '1000/h',
        '/api/custom/device/': '500/h',
        '/api/custom/request-size/': '100/h',
        '/api/custom/time-based/': '500/h',
        '/api/custom/referer/': '1000/h',
        '/api/custom/method/': '200/h',
        '/api/custom/content-type/': '300/h',
        '/api/custom/business-logic/': '100/h',
        '/api/custom/geographic-advanced/': '1000/h',
        '/api/custom/device-selective/': '500/h',
    },
}

# IP reputation service configuration (example)
IP_REPUTATION_SERVICE = {
    'ENABLED': True,
    'API_KEY': 'your-api-key-here',
    'THRESHOLD': 0.7,  # Risk threshold
    'CACHE_TIMEOUT': 3600,  # Cache results for 1 hour
}
"""

if __name__ == "__main__":
    print("Custom Key Functions and Complex Rate Limiting Examples")
    print("=" * 60)
    print("This file demonstrates advanced rate limiting with custom key functions.")
    print("Modify the key functions to match your specific business requirements.")
    print("Consider using external services for IP reputation and geolocation.")
