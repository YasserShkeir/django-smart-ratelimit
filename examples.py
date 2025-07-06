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


# Example 3: Custom key function with API keys
def api_key_based_key(request):
    """Generate key based on API key or IP."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"api_key:{api_key}"
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=api_key_based_key, rate="1000/h")
def api_with_keys(request):
    """API endpoint that uses API keys for rate limiting."""
    return JsonResponse({"message": "API key-based rate limited endpoint"})


# Example 4: Custom tenant-based rate limiting
def tenant_key_function(request):
    """Generate key based on tenant ID from headers."""
    tenant_id = request.headers.get("X-Tenant-ID")
    if tenant_id:
        return f"tenant:{tenant_id}"
    # Fallback to user or IP
    if request.user.is_authenticated:
        return f"user:{request.user.id}"
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=tenant_key_function, rate="500/h")
def tenant_api(request):
    """Multi-tenant API with tenant-specific rate limiting."""
    return JsonResponse({"tenant_data": "Tenant-specific data"})


# Example 5: Database model-based key
def custom_user_key(request):
    """Generate key using custom user model."""
    # Example: Using a custom User model or profile
    if hasattr(request, "custom_user") and request.custom_user:
        return f"custom_user:{request.custom_user.id}"
    elif request.user.is_authenticated:
        return f"django_user:{request.user.id}"
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=custom_user_key, rate="100/h")
def custom_user_api(request):
    """API using custom user identification."""
    return JsonResponse({"message": "Custom user-based rate limiting"})


# Example 6: JWT-based rate limiting
def jwt_subject_key(request):
    """Extract user ID from JWT token."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            # Note: In production, properly verify the JWT signature
            # pip install PyJWT
            import base64
            import json

            token = auth_header.split(" ")[1]
            # Decode JWT payload (without verification for example)
            payload_part = token.split(".")[1]
            # Add padding if needed
            payload_part += "=" * (4 - len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part))
            return f"jwt_sub:{payload.get('sub', 'unknown')}"
        except Exception:
            pass
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=jwt_subject_key, rate="200/h")
def jwt_protected_api(request):
    """JWT-protected API with token-based rate limiting."""
    return JsonResponse({"protected_data": "JWT-protected endpoint"})


# Example 7: Non-blocking rate limiting (just adds headers)
@rate_limit(key="ip", rate="5/m", block=False)
def api_non_blocking(request):
    """API endpoint that doesn't block but adds rate limit headers."""
    return JsonResponse({"message": "Non-blocking rate limited endpoint"})


# Example 8: Different rates for different endpoints
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

# Example Django settings.py configuration for Database Backend
DATABASE_BACKEND_SETTINGS = """
# settings.py - Database Backend Configuration

# Basic configuration
RATELIMIT_BACKEND = 'database'

# Database backend specific settings
RATELIMIT_DATABASE_CLEANUP_THRESHOLD = 1000  # Cleanup threshold for entries

# Use sliding window algorithm for more accurate rate limiting
RATELIMIT_ALGORITHM = "sliding_window"

# Add to INSTALLED_APPS
INSTALLED_APPS = [
    # ... your other apps
    'django_smart_ratelimit',
]

# Run migrations
# python manage.py makemigrations django_smart_ratelimit
# python manage.py migrate

# Middleware configuration
MIDDLEWARE = [
    'django_smart_ratelimit.middleware.RateLimitMiddleware',
    # ... other middleware
]

RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '100/m',  # 100 requests per minute by default
    'BACKEND': 'database',
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

# Management commands for cleanup
# python manage.py cleanup_ratelimit --dry-run
# python manage.py cleanup_ratelimit --older-than 24  # Clean entries older than 24h
"""

# Example URL configuration
EXAMPLE_URLS = """
# urls.py

from django.urls import path
from . import views

urlpatterns = [
    # Basic examples
    path('api/basic/', views.api_basic, name='api_basic'),
    path('api/user/', views.api_user_limited, name='api_user'),
    path('api/non-blocking/', views.api_non_blocking, name='api_non_blocking'),

    # Advanced key-based examples
    path('api/keys/', views.api_with_keys, name='api_keys'),
    path('api/tenant/', views.tenant_api, name='tenant_api'),
    path('api/custom-user/', views.custom_user_api, name='custom_user_api'),
    path('api/jwt/', views.jwt_protected_api, name='jwt_api'),

    # Different rate limits
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
    print("\nDatabase Backend Configuration:")
    print(DATABASE_BACKEND_SETTINGS)
    print("\nURL configuration:")
    print(EXAMPLE_URLS)
    print("\nFor more information, see the README.md file.")
