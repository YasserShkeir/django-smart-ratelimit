"""
Rate limiting middleware for Django applications.

This module provides middleware that can apply rate limiting to all requests
or specific patterns based on configuration.
"""

import time
from typing import Callable, Optional

from django.http import HttpRequest, HttpResponse

# Compatibility for Django < 4.2
try:
    from django.http import HttpResponseTooManyRequests  # type: ignore
except ImportError:

    class HttpResponseTooManyRequests(HttpResponse):  # type: ignore
        """HTTP 429 Too Many Requests response class."""

        status_code = 429


from django.conf import settings

from .backends import get_backend
from .utils import (
    add_rate_limit_headers,
    get_ip_key,
    get_rate_for_path,
    load_function_from_string,
    parse_rate,
    should_skip_path,
)


class RateLimitMiddleware:
    """Middleware for applying rate limiting to Django requests.

    Configuration in settings.py:

    RATELIMIT_MIDDLEWARE = {
        'DEFAULT_RATE': '100/m',  # 100 requests per minute
        'BACKEND': 'redis',
        'KEY_FUNCTION': (
            'django_smart_ratelimit.middleware.default_key_function'
        ),
        'BLOCK': True,
        'SKIP_PATHS': ['/admin/', '/api/health/'],
        'RATE_LIMITS': {
            '/api/': '1000/h',  # Different rate for API endpoints
            '/auth/login/': '5/m',  # Stricter rate for login
        }
    }
    """

    def __init__(self, get_response: Callable):
        """Initialize the middleware with configuration."""
        self.get_response = get_response

        # Load configuration
        config = getattr(settings, "RATELIMIT_MIDDLEWARE", {})

        self.default_rate = config.get("DEFAULT_RATE", "100/m")
        self.backend_name = config.get("BACKEND", None)
        self.key_function = self._load_key_function(config.get("KEY_FUNCTION"))
        self.block = config.get("BLOCK", True)
        self.skip_paths = config.get("SKIP_PATHS", [])
        self.rate_limits = config.get("RATE_LIMITS", {})

        # Initialize backend
        self.backend = get_backend(self.backend_name)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Process the request and apply rate limiting."""
        # Check if path should be skipped
        if should_skip_path(request.path, self.skip_paths):
            return self.get_response(request)

        # Get rate limit for this path
        rate = get_rate_for_path(request.path, self.rate_limits, self.default_rate)

        # Generate key
        key = self.key_function(request)

        # Parse rate
        limit, period = parse_rate(rate)

        # Check rate limit
        current_count = self.backend.incr(key, period)

        # Mark that middleware has processed this request to prevent double-counting
        request._ratelimit_middleware_processed = True  # type: ignore[attr-defined]
        request._ratelimit_middleware_limit = limit  # type: ignore[attr-defined]
        request._ratelimit_middleware_remaining = max(0, limit - current_count)  # type: ignore[attr-defined]

        if current_count > limit:
            if self.block:
                response = HttpResponseTooManyRequests(
                    "Rate limit exceeded. Please try again later."
                )
                add_rate_limit_headers(response, limit, 0, int(time.time() + period))
                return response

        # Process the request
        response = self.get_response(request)

        # Only add rate limit headers if they haven't been set by a decorator
        # or if this middleware has a more restrictive limit
        if (
            not hasattr(response, "headers")
            or "X-RateLimit-Limit" not in response.headers
        ):
            # Add rate limit headers
            add_rate_limit_headers(
                response,
                limit,
                max(0, limit - current_count),
                int(time.time() + period),
            )
        else:
            # Headers already exist (likely from decorator), check if middleware is more restrictive
            existing_limit = int(
                response.headers.get("X-RateLimit-Limit", float("inf"))
            )
            existing_remaining = int(
                response.headers.get("X-RateLimit-Remaining", float("inf"))
            )

            # If middleware is more restrictive, update headers
            middleware_remaining = max(0, limit - current_count)
            if limit < existing_limit or middleware_remaining < existing_remaining:
                add_rate_limit_headers(
                    response, limit, middleware_remaining, int(time.time() + period)
                )

        return response

    def _load_key_function(self, key_function_path: Optional[str]) -> Callable:
        """Load the key function from settings or use default."""
        if not key_function_path:
            return default_key_function

        return load_function_from_string(key_function_path)


def default_key_function(request: HttpRequest) -> str:
    """Generate default key function that uses the client IP address.

    Args:
        request: The Django request object

    Returns:
        Rate limit key based on client IP
    """
    ip_key = get_ip_key(request)
    # Replace 'ip:' prefix with 'middleware:' to distinguish from decorator usage
    return ip_key.replace("ip:", "middleware:")


def user_key_function(request: HttpRequest) -> str:
    """
    Key function that uses the authenticated user ID.

    Args:
        request: The Django request object

    Returns:
        Rate limit key based on user ID or IP for anonymous users
    """
    if request.user.is_authenticated:
        return f"middleware:user:{getattr(request.user, 'id', None)}"
    else:
        return default_key_function(request)
