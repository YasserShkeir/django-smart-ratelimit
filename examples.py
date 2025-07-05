#!/usr/bin/env python3
"""
Example usage of django-smart-ratelimit library.

This script demonstrates how to use the rate limiting decorator
and middleware in a Django application.

Created by Yasser Shkeir
"""

# This would normally be in your Django views.py file
from django.http import JsonResponse

from django_smart_ratelimit import rate_limit


# Example 1: Basic rate limiting by IP
@rate_limit(key="ip", rate="10/m")
def api_basic(request):
    """API endpoint limited to 10 requests per minute per IP."""
    return JsonResponse({"message": "Hello World", "status": "success"})


# Example 2: Rate limiting by user ID
@rate_limit(key="user", rate="100/h")
def api_user_limited(request):
    """API endpoint limited to 100 requests per hour per user."""
    return JsonResponse({"data": "User-specific data", "user_id": request.user.id})


# Example 3: Custom key function
def custom_key_function(request):
    """Generate a custom key based on user or IP."""
    if request.user.is_authenticated:
        return f"user:{request.user.id}"
    else:
        return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=custom_key_function, rate="50/m")
def api_smart_limited(request):
    """API endpoint with smart rate limiting."""
    return JsonResponse({"message": "Smart rate limited endpoint"})


# Example 4: Non-blocking rate limiting (just adds headers)
@rate_limit(key="ip", rate="5/m", block=False)
def api_non_blocking(request):
    """API endpoint that doesn't block but adds rate limit headers."""
    return JsonResponse({"message": "Non-blocking rate limited endpoint"})


# Example 5: Different rates for different endpoints
@rate_limit(key="user", rate="1000/h")
def api_high_limit(request):
    """High-traffic API endpoint."""
    return JsonResponse({"data": "High traffic data"})


@rate_limit(key="user", rate="5/m")
def api_sensitive(request):
    """Sensitive API endpoint with strict rate limiting."""
    return JsonResponse({"sensitive": "data"})


# Example Django settings.py configuration
REDIS_BACKEND_SETTINGS = """
# settings.py - Redis Backend Configuration

# Basic configuration
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
}

# Use sliding window algorithm for more accurate rate limiting
RATELIMIT_ALGORITHM = "sliding_window"

# Middleware configuration
MIDDLEWARE = [
    'django_smart_ratelimit.middleware.RateLimitMiddleware',
    # ... other middleware
]

RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '100/m',  # 100 requests per minute by default
    'BACKEND': 'redis',
    'BLOCK': True,
    'SKIP_PATHS': ['/admin/', '/health/', '/metrics/'],
    'RATE_LIMITS': {
        '/api/public/': '1000/h',    # Public API: 1000 requests per hour
        '/api/private/': '100/h',    # Private API: 100 requests per hour
        '/auth/login/': '5/m',       # Login: 5 attempts per minute
        '/auth/register/': '3/h',    # Registration: 3 attempts per hour
        '/upload/': '10/h',          # File uploads: 10 per hour
    },
    'KEY_FUNCTION': 'myapp.utils.custom_key_function',
}
"""

# Example Django settings.py configuration for Memory Backend
MEMORY_BACKEND_SETTINGS = """
# settings.py - Memory Backend Configuration

# Basic configuration
RATELIMIT_BACKEND = 'memory'

# Memory backend specific settings
RATELIMIT_MEMORY_MAX_KEYS = 10000        # Maximum number of keys to store
RATELIMIT_MEMORY_CLEANUP_INTERVAL = 300  # Cleanup interval in seconds

# Use sliding window algorithm for more accurate rate limiting
RATELIMIT_ALGORITHM = "sliding_window"

# Middleware configuration
MIDDLEWARE = [
    'django_smart_ratelimit.middleware.RateLimitMiddleware',
    # ... other middleware
]

RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '100/m',  # 100 requests per minute by default
    'BACKEND': 'memory',
    'BLOCK': True,
    'SKIP_PATHS': ['/admin/', '/health/', '/metrics/'],
    'RATE_LIMITS': {
        '/api/public/': '1000/h',    # Public API: 1000 requests per hour
        '/api/private/': '100/h',    # Private API: 100 requests per hour
        '/auth/login/': '5/m',       # Login: 5 attempts per minute
        '/auth/register/': '3/h',    # Registration: 3 attempts per hour
        '/upload/': '10/h',          # File uploads: 10 per hour
    },
}
"""

# Example URL configuration
EXAMPLE_URLS = """
# urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('api/basic/', views.api_basic, name='api_basic'),
    path('api/user/', views.api_user_limited, name='api_user'),
    path('api/smart/', views.api_smart_limited, name='api_smart'),
    path('api/non-blocking/', views.api_non_blocking, name='api_non_blocking'),
    path('api/high-limit/', views.api_high_limit, name='api_high_limit'),
    path('api/sensitive/', views.api_sensitive, name='api_sensitive'),
]
"""

if __name__ == "__main__":
    print("Django Smart Ratelimit Examples")
    print("=" * 40)
    print(
        "\nThis file contains example usage of the " "django-smart-ratelimit library."
    )
    print("Copy the functions and configurations into your Django application.")
    print("\nSettings configuration:")
    print("Redis Backend Configuration:")
    print(REDIS_BACKEND_SETTINGS)
    print("\nMemory Backend Configuration:")
    print(MEMORY_BACKEND_SETTINGS)
    print("\nURL configuration:")
    print(EXAMPLE_URLS)
    print("\nFor more information, see the README.md file.")
