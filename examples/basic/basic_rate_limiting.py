#!/usr/bin/env python3
"""
Basic Rate Limiting Examples

This demonstrates the most common rate limiting scenarios using
django-smart-ratelimit decorators.
"""


from django.http import HttpRequest, JsonResponse

from django_smart_ratelimit import is_authenticated_user, rate_limit


# Example 1: Basic IP-based rate limiting
@rate_limit(key="ip", rate="10/m")
def api_basic_ip(_request: HttpRequest) -> JsonResponse:
    """
    API endpoint limited to 10 requests per minute per IP address.

    This is the most common rate limiting pattern - limiting requests
    based on the client's IP address.
    """
    return JsonResponse(
        {
            "message": "Hello World",
            "status": "success",
            "rate_limit": "10 requests per minute per IP",
        }
    )


# Example 2: User-based rate limiting
@rate_limit(key="user", rate="100/h")
def api_user_limited(_request: HttpRequest) -> JsonResponse:
    """
    API endpoint limited to 100 requests per hour per authenticated user.

    This pattern is useful when you want different limits for different users
    or want to allow higher limits for authenticated users.
    """
    if not is_authenticated_user(_request):
        return JsonResponse({"error": "Authentication required"}, status=401)

    return JsonResponse(
        {
            "data": "User-specific data",
            "user_id": _request.user.id,
            "rate_limit": "100 requests per hour per user",
        }
    )


# Example 3: Combining multiple rate limits
@rate_limit(key="ip", rate="100/h")  # General IP limit
@rate_limit(key="user", rate="1000/h")  # Higher limit for authenticated users
def api_combined_limits(_request: HttpRequest) -> JsonResponse:
    """
    Multiple rate limits applied to the same endpoint.

    Both limits must be satisfied for the _request to proceed.
    This allows for both IP-based and user-based protection.
    """
    user_info = (
        "anonymous"
        if not is_authenticated_user(_request)
        else f"user_{_request.user.id}"
    )

    return JsonResponse(
        {
            "message": "Combined rate limiting active",
            "user": user_info,
            "limits": [
                "100 requests per hour per IP",
                "1000 requests per hour per user (if authenticated)",
            ],
        }
    )


# Example 4: Skip rate limiting for specific conditions
@rate_limit(key="ip", rate="10/m", skip_if=lambda _request: _request.user.is_staff)
def api_skip_for_staff(_request: HttpRequest) -> JsonResponse:
    """
    Rate limiting that can be bypassed for certain users.

    Staff users are not subject to rate limiting.
    Regular users are limited to 10 requests per minute.
    """
    user_type = "staff" if _request.user.is_staff else "regular user"
    rate_limited = "No" if _request.user.is_staff else "Yes (10/min)"

    return JsonResponse(
        {
            "message": "Staff bypass example",
            "user_type": user_type,
            "rate_limited": rate_limited,
        }
    )


# Example 5: Using different algorithms
@rate_limit(key="ip", rate="20/m", algorithm="sliding_window")
def api_sliding_window(_request: HttpRequest) -> JsonResponse:
    """
    API with sliding window algorithm.

    Sliding window provides smoother rate limiting by distributing
    requests evenly across the time window.
    """
    return JsonResponse(
        {
            "message": "Sliding window algorithm",
            "algorithm": "sliding_window",
            "rate_limit": "20 requests per minute (smoothly distributed)",
        }
    )


@rate_limit(key="ip", rate="20/m", algorithm="fixed_window")
def api_fixed_window(_request: HttpRequest) -> JsonResponse:
    """
    API with fixed window algorithm.

    Fixed window allows burst requests at the start of each window
    but provides hard boundaries.
    """
    return JsonResponse(
        {
            "message": "Fixed window algorithm",
            "algorithm": "fixed_window",
            "rate_limit": "20 requests per minute (allows bursts)",
        }
    )


# Example 6: Custom error response
def custom_rate_limit_response(_request: HttpRequest) -> JsonResponse:
    """Custom response when rate limit is exceeded."""
    return JsonResponse(
        {
            "error": "Rate limit exceeded",
            "message": "Please slow down your requests",
            "retry_after": 60,  # seconds
        },
        status=429,
    )


@rate_limit(key="ip", rate="5/m", block=True)
def api_custom_error(_request: HttpRequest) -> JsonResponse:
    """
    API with custom rate limit exceeded response.

    When rate limit is exceeded, returns a custom JSON response
    instead of the default Django response.
    """
    return JsonResponse(
        {"message": "Request successful", "rate_limit": "5 requests per minute per IP"}
    )


if __name__ == "__main__":
    print("Basic Rate Limiting Examples")
    print("=============================")
    print("")
    print("This file contains examples of basic rate limiting patterns:")
    print("1. IP-based rate limiting")
    print("2. User-based rate limiting")
    print("4. Combining multiple rate limits")
    print("5. Skipping rate limits for specific conditions")
    print("6. Using different algorithms (sliding window, fixed window)")
    print("7. Custom error responses for rate limit exceeded")
    print("")
    print("To use these examples, include them in your Django views.py file")
    print("and add the corresponding URL patterns to your urls.py file.")
