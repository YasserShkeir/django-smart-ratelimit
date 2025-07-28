#!/usr/bin/env python3
"""
Middleware Configuration Examples

This demonstrates how to configure and use the rate limiting middleware
for automatic protection of your Django application.
"""

from typing import Any, Optional

# settings.py configuration examples

# Example 1: Basic middleware configuration
BASIC_MIDDLEWARE_CONFIG = {
    "MIDDLEWARE": [
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
        # Add rate limiting middleware
        "django_smart_ratelimit.middleware.RateLimitMiddleware",
    ],
    # Basic rate limiting configuration
    "RATELIMIT_USE_CACHE": True,
    "RATELIMIT_CACHE_PREFIX": "rate_limit",
    "RATELIMIT_DEFAULT_BACKEND": "memory",
    # Global rate limiting rules
    "RATELIMIT_GLOBAL": {
        "rate": "1000/h",  # 1000 requests per hour per IP
        "key": "ip",
        "skip_if": lambda _request: _request.user.is_staff,  # Using Django's built-in is_staff check
    },
}


# Example 2: Advanced middleware configuration with multiple backends
ADVANCED_MIDDLEWARE_CONFIG = {
    # Backend configuration
    "RATELIMIT_BACKENDS": {
        "redis_primary": {
            "backend": "django_smart_ratelimit.backends.redis_backend.RedisBackend",
            "config": {
                "host": "localhost",
                "port": 6379,
                "db": 0,
                "password": None,
                "key_prefix": "ratelimit:",
            },
        },
        "database_fallback": {
            "backend": "django_smart_ratelimit.backends.database.DatabaseBackend",
            "config": {},
        },
        "mongodb_analytics": {
            "backend": "django_smart_ratelimit.backends.mongodb.MongoDBBackend",
            "config": {
                "host": "localhost",
                "port": 27017,
                "database": "ratelimit",
                "collection": "rate_limits",
            },
        },
    },
    # Multi-backend strategy
    "RATELIMIT_MULTI_BACKEND": {
        "backends": ["redis_primary", "database_fallback"],
        "strategy": "first_healthy",  # or 'all', 'majority'
        "health_check_interval": 60,  # seconds
    },
    # Different rate limits for different URL patterns
    "RATELIMIT_PATTERNS": [
        {
            "pattern": r"^/api/public/",
            "rate": "100/h",
            "key": "ip",
            "backend": "redis_primary",
        },
        {
            "pattern": r"^/api/auth/",
            "rate": "1000/h",
            "key": "user",
            "backend": "redis_primary",
            "skip_if": lambda _request: not hasattr(_request, "user")
            or not _request.user.is_authenticated,
        },
        {
            "pattern": r"^/api/admin/",
            "rate": "10000/h",
            "key": "user",
            "backend": "redis_primary",
            "skip_if": lambda _request: not _request.user.is_staff,
        },
        {
            "pattern": r"^/api/upload/",
            "rate": "10/h",  # Stricter limit for uploads
            "key": "ip",
            "methods": ["POST", "PUT"],
            "backend": "redis_primary",
        },
    ],
    # Global settings
    "RATELIMIT_GLOBAL": {
        "rate": "10000/h",  # Very high global limit
        "key": "ip",
        "backend": "database_fallback",
        "skip_if": lambda _request: _request.META.get("HTTP_X_BYPASS_RATELIMIT")
        == "secret_key",
    },
}


# Example 3: Environment-specific configurations

# Development settings
DEVELOPMENT_CONFIG = {
    "RATELIMIT_ENABLE": False,  # Disable rate limiting in development
    "RATELIMIT_DEFAULT_BACKEND": "memory",
}

# Testing settings
TESTING_CONFIG = {
    "RATELIMIT_ENABLE": True,
    "RATELIMIT_DEFAULT_BACKEND": "memory",
    "RATELIMIT_GLOBAL": {
        "rate": "10/m",  # Low limits for testing
        "key": "ip",
    },
}

# Production settings
PRODUCTION_CONFIG = {
    "RATELIMIT_ENABLE": True,
    "RATELIMIT_DEFAULT_BACKEND": "redis_primary",
    # Redis configuration for production
    "RATELIMIT_REDIS": {
        "host": "redis.production.example.com",
        "port": 6379,
        "db": 0,
        "password": "your-secure-password",
        "ssl": True,
        "ssl_cert_reqs": None,
        "connection_pool_kwargs": {
            "max_connections": 50,
            "retry_on_timeout": True,
        },
    },
    # Strict production limits
    "RATELIMIT_PATTERNS": [
        {
            "pattern": r"^/api/",
            "rate": "1000/h",
            "key": "ip",
            "block": True,  # Block instead of just logging
        }
    ],
    # Monitoring and logging
    "RATELIMIT_LOGGING": {
        "enabled": True,
        "level": "WARNING",
        "include_headers": ["User-Agent", "X-Forwarded-For"],
    },
}


# Example 4: Custom middleware class for advanced use cases
"""
# custom_middleware.py

from django_smart_ratelimit import RateLimitMiddleware
from django.http import JsonResponse
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

class CustomRateLimitMiddleware(RateLimitMiddleware):
    '''Custom rate limiting middleware with enhanced features.'''

    def rate_limit_exceeded_response(self, _request, rate_limit_info):
        '''Custom response when rate limit is exceeded.'''

        # Log the rate limit violation
        logger.warning(
            f"Rate limit exceeded for {_request.META.get('REMOTE_ADDR')} "
            f"on {_request.path}"
        )

        # Send notification for repeated violations
        if rate_limit_info.get('consecutive_violations', 0) > 5:
            self.send_abuse_notification(_request, rate_limit_info)

        # Custom JSON response
        response_data = {
            'error': 'Rate limit exceeded',
            'message': 'Too many requests. Please slow down.',
            'retry_after': rate_limit_info.get('retry_after', 60),
            'limit': rate_limit_info.get('limit'),
            'remaining': 0,
            'reset_time': rate_limit_info.get('reset_time')
        }

        response = JsonResponse(response_data, status=429)
        response['Retry-After'] = str(rate_limit_info.get('retry_after', 60))
        response['X-RateLimit-Limit'] = str(rate_limit_info.get('limit', ''))
        response['X-RateLimit-Remaining'] = '0'
        response['X-RateLimit-Reset'] = str(rate_limit_info.get('reset_time', ''))

        return response

    def send_abuse_notification(self, _request, rate_limit_info):
        '''Send notification for repeated rate limit violations.'''
        # Implementation would send email/webhook/etc.
        pass

    def get_rate_limit_key(self, _request):
        '''Custom key generation logic.'''
        # Use X-Forwarded-For header if behind a proxy
        x_forwarded_for = _request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = _request.META.get('REMOTE_ADDR')

        # Include user agent in key to prevent simple IP rotation
        user_agent_hash = hash(_request.META.get('HTTP_USER_AGENT', ''))

        return f"ip:{ip}:ua:{user_agent_hash}"
"""


# Example 5: URL pattern-specific configurations
URL_SPECIFIC_CONFIG = {
    "RATELIMIT_PATTERNS": [
        # Public API endpoints - moderate limits
        {
            "pattern": r"^/api/v1/public/",
            "rate": "100/h",
            "key": "ip",
            "methods": ["GET"],
        },
        # Authentication endpoints - stricter limits
        {
            "pattern": r"^/api/v1/auth/login/",
            "rate": "5/m",  # Prevent brute force
            "key": "ip",
            "methods": ["POST"],
        },
        # Password reset - very strict
        {
            "pattern": r"^/api/v1/auth/reset-password/",
            "rate": "3/h",
            "key": "ip",
            "methods": ["POST"],
        },
        # File uploads - resource intensive
        {
            "pattern": r"^/api/v1/upload/",
            "rate": "10/h",
            "key": lambda _request: (
                f"user:{_request.user.id}"
                if _request.user.is_authenticated
                else f"ip:{_request.META.get('REMOTE_ADDR')}"
            ),
            "methods": ["POST"],
        },
        # Search endpoints - can be expensive
        {
            "pattern": r"^/api/v1/search/",
            "rate": "60/h",
            "key": "ip",
            "methods": ["GET"],
        },
        # Admin endpoints - high limits for staff
        {
            "pattern": r"^/api/v1/admin/",
            "rate": "10000/h",
            "key": "user",
            "skip_if": lambda _request: not _request.user.is_staff,
        },
    ]
}


# Example 6: Middleware with algorithm and skip_if support via custom configuration
ALGORITHM_AWARE_MIDDLEWARE_CONFIG = {
    "MIDDLEWARE": [
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
        "django_smart_ratelimit.middleware.RateLimitMiddleware",
    ],
    # Middleware configuration with algorithm awareness
    "RATELIMIT_MIDDLEWARE": {
        "DEFAULT_RATE": "100/h",
        "BACKEND": "redis",
        "BLOCK": True,
        # Skip rate limiting for certain conditions
        "SKIP_IF": lambda _request: (
            _request.user.is_staff
            or _request.path.startswith("/admin/")
            or _request.META.get("HTTP_X_BYPASS_RATELIMIT") == "true"
        ),
        # Default algorithm for the middleware
        "ALGORITHM": "sliding_window",  # or 'fixed_window'
        # Path-specific configurations with algorithms
        "RATE_LIMITS": {
            "/api/upload/": {
                "rate": "10/h",
                "algorithm": "fixed_window",  # Allow bursts for uploads
            },
            "/api/search/": {
                "rate": "100/h",
                "algorithm": "sliding_window",  # Smooth for search
            },
            "/api/auth/": {
                "rate": "20/h",
                "algorithm": "sliding_window",
                "skip_if": lambda _request: _request.method == "GET",
            },
        },
        "SKIP_PATHS": ["/health/", "/metrics/", "/static/"],
    },
}


# Example 7: Custom key function that works with skip_if
def smart_key_function(_request: Any) -> Optional[str]:
    """
    Custom key function that considers user type and _request characteristics.
    """
    # Skip rate limiting for internal services
    if _request.META.get("HTTP_X_INTERNAL_SERVICE") == "true":
        return None  # Signal to skip rate limiting

    # Different keys for different user types
    if hasattr(_request, "user") and _request.user.is_authenticated:
        if _request.user.is_superuser:
            return None  # No rate limiting for superusers
        elif _request.user.is_staff:
            return f"staff:{_request.user.id}"
        else:
            return f"user:{_request.user.id}"
    else:
        # Anonymous users get IP-based limiting
        return f"ip:{_request.META.get('REMOTE_ADDR', 'unknown')}"


# Configuration using the custom key function
CUSTOM_KEY_MIDDLEWARE_CONFIG = {
    "RATELIMIT_MIDDLEWARE": {
        "DEFAULT_RATE": "100/h",
        "KEY_FUNCTION": "myapp.middleware.smart_key_function",
        "ALGORITHM": "sliding_window",
        "BLOCK": True,
        # Skip function that works with the key function
        "SKIP_IF": lambda _request: smart_key_function(_request) is None,
    }
}


if __name__ == "__main__":
    print("Middleware Configuration Examples")
    print("=================================")
    print("")
    print("This file contains examples of middleware configurations:")
    print("1. Basic middleware setup")
    print("2. Advanced multi-backend configuration")
    print("3. Environment-specific settings")
    print("4. Custom middleware class example")
    print("5. URL pattern-specific rate limiting")
    print("6. Middleware with algorithm and skip_if support")
    print("7. Custom key function example")
    print("")
    print("Use these configurations in your Django settings.py file")
    print("to enable automatic rate limiting protection.")
