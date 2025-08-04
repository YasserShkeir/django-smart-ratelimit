"""
Example views demonstrating fixed rate limiting behavior and debugging.

This module shows how to properly configure rate limiting to avoid
common issues like double-counting and header mismatches.

Fixes for GitHub issue #6:
https://github.com/YasserShkeir/django-smart-ratelimit/issues/6
- Request counts increasing by 2-3 per request
- Header values not matching configured limits
- Rate limiting occurring too early
"""

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from django_smart_ratelimit import debug_ratelimit_status, format_debug_info, rate_limit
from django_smart_ratelimit.utils import should_skip_common_browser_requests


# Example 1: Properly handling browser secondary requests (SECURE VERSION)
@rate_limit(
    key="ip",
    rate="10/m",
    skip_if=should_skip_common_browser_requests,  # Use secure utility function
)
@require_http_methods(["GET", "POST"])
def browser_friendly_api(request):
    """
    API endpoint that properly handles browser secondary requests.

    Uses secure utility function that respects configured STATIC_URL
    and MEDIA_URL settings to prevent rate limit bypass.
    """
    return JsonResponse(
        {
            "message": "This endpoint won't count favicon or preflight requests",
            "method": request.method,
            "path": request.path,
        }
    )


# Example 1b: Manual skip condition (if you need custom logic)
@rate_limit(
    key="ip",
    rate="10/m",
    skip_if=lambda req: (
        # Skip common browser secondary requests
        req.path in ["/favicon.ico", "/robots.txt", "/apple-touch-icon.png"]
        # SECURITY: Use actual configured static/media URLs instead of hardcoded paths
        or req.path.startswith(getattr(settings, "STATIC_URL", "/static/"))
        or req.path.startswith(getattr(settings, "MEDIA_URL", "/media/"))
        or req.method in ["OPTIONS", "HEAD"]
        or
        # Skip internal requests
        req.headers.get("X-Internal-Request") == "true"
    ),
)
@require_http_methods(["GET", "POST"])
def browser_friendly_api_manual(request):
    """
    API endpoint demonstrating manual skip condition with security considerations.

    Note: Prefer using should_skip_common_browser_requests() utility function
    unless you need custom skip logic.
    """
    return JsonResponse(
        {
            "message": "This endpoint uses manual skip condition",
            "method": request.method,
            "path": request.path,
        }
    )


# Example 2: Debug endpoint to troubleshoot rate limiting issues
def debug_rate_limiting(request):
    """Debug endpoint to check rate limiting status."""
    debug_info = debug_ratelimit_status(request)

    return JsonResponse(
        {
            "debug_info": debug_info,
            "formatted_debug": format_debug_info(debug_info),
        }
    )


# Example 3: API endpoint with proper rate limiting
@rate_limit(
    key=lambda req: (
        f"user:{req.user.id}"
        if req.user.is_authenticated
        else f"ip:{req.META.get('REMOTE_ADDR')}"
    ),
    rate="100/h",  # 100 requests per hour
    skip_if=lambda req: req.user.is_staff if hasattr(req, "user") else False,
)
def api_endpoint_with_proper_config(request):
    """
    Example API endpoint with proper rate limiting configuration.

    - Uses user ID for authenticated users, IP for anonymous
    - Skips rate limiting for staff users
    - Won't double-count if middleware is also configured
    """
    user_info = "authenticated" if request.user.is_authenticated else "anonymous"

    return JsonResponse(
        {
            "message": f"API response for {user_info} user",
            "user_id": getattr(request.user, "id", None),
            "is_staff": getattr(request.user, "is_staff", False),
        }
    )


# Example 4: Demonstration of middleware vs decorator coordination
@rate_limit(key="user", rate="5/m")  # Strict decorator limit
def endpoint_with_both_middleware_and_decorator(request):
    """
    This endpoint demonstrates how decorator and middleware work together.

    If middleware is configured with a higher limit (e.g., 100/h = ~1.67/m),
    the decorator's stricter limit (5/m) will take precedence.

    The response headers will reflect the decorator's limit to avoid confusion.
    """
    return JsonResponse(
        {
            "message": "This endpoint has both middleware and decorator applied",
            "decorator_limit": "5/m",
            "note": "Headers will show the decorator limit (more restrictive)",
        }
    )


# Example 5: Testing helper view
def test_rate_limit_behavior(request):
    """
    Helper view for testing rate limiting behavior.

    Use this with tools like Postman or curl to test rate limiting
    without browser interference.
    """
    debug_info = debug_ratelimit_status(request)

    # Get current counts from debug info
    backend_counts = debug_info.get("backend_counts", {})

    return JsonResponse(
        {
            "test_info": {
                "message": "Use this endpoint to test rate limiting",
                "recommendations": [
                    "Test with Postman/curl, not browsers",
                    "Check X-RateLimit-* headers in response",
                    "Monitor the debug_info for backend state",
                ],
            },
            "current_state": {
                "path": request.path,
                "method": request.method,
                "middleware_processed": debug_info.get("middleware_processed", False),
                "backend_counts": backend_counts,
            },
            "headers_explanation": {
                "X-RateLimit-Limit": "Maximum requests allowed in the time window",
                "X-RateLimit-Remaining": "Requests remaining in current window",
                "X-RateLimit-Reset": "Unix timestamp when the window resets",
            },
        }
    )


# Example 6: URL patterns for Django
"""
Add these to your urls.py:

from django.urls import path
from . import views

urlpatterns = [
    path('api/test/', views.browser_friendly_api, name='browser_friendly_api'),
    path('api/debug/', views.debug_rate_limiting, name='debug_rate_limiting'),
    path('api/endpoint/', views.api_endpoint_with_proper_config, name='api_endpoint'),
    path('api/mixed/', views.endpoint_with_both_middleware_and_decorator, name='mixed_endpoint'),
    path('api/test-behavior/', views.test_rate_limit_behavior, name='test_behavior'),
]
"""

# Example 7: Settings configuration to avoid conflicts
"""
# settings.py

# Option A: Use only middleware (global rate limiting)
RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '1000/h',
    'RATE_LIMITS': {
        '/api/': '100/h',
        '/api/auth/': '10/h',
    },
    'SKIP_PATHS': [
        '/favicon.ico',
        '/robots.txt',
        # Use actual configured URLs instead of hardcoded paths for security
        STATIC_URL,  # Will use settings.STATIC_URL (e.g., '/static/' or '/assets/')
        MEDIA_URL,   # Will use settings.MEDIA_URL (e.g., '/media/' or '/uploads/')
        '/admin/',
    ]
}

# Option B: Use middleware + decorator with proper coordination
RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '10000/h',  # Very generous global limit
    'SKIP_PATHS': [
        '/api/',  # Skip API paths handled by decorators
        '/favicon.ico',
        '/robots.txt',
        STATIC_URL,  # Use configured static URL
        MEDIA_URL,   # Use configured media URL
        '/admin/',
    ]
}

# Then use @rate_limit decorator on individual API endpoints

# Security Note: Always use settings.STATIC_URL and settings.MEDIA_URL
# instead of hardcoded '/static/' and '/media/' paths to prevent
# bypassing rate limits when these settings are customized.
"""
