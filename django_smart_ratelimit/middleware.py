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
from django.core.exceptions import ImproperlyConfigured

from .backends import get_backend


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
        if self._should_skip_path(request.path):
            return self.get_response(request)

        # Get rate limit for this path
        rate = self._get_rate_for_path(request.path)

        # Generate key
        key = self.key_function(request)

        # Parse rate
        limit, period = self._parse_rate(rate)

        # Check rate limit
        current_count = self.backend.incr(key, period)

        if current_count > limit:
            if self.block:
                response = HttpResponseTooManyRequests(
                    "Rate limit exceeded. Please try again later."
                )
                response.headers["X-RateLimit-Limit"] = str(limit)
                response.headers["X-RateLimit-Remaining"] = "0"
                response.headers["X-RateLimit-Reset"] = str(int(time.time() + period))
                return response

        # Process the request
        response = self.get_response(request)

        # Add rate limit headers
        if hasattr(response, "headers"):
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(
                max(0, limit - current_count)
            )
            response.headers["X-RateLimit-Reset"] = str(int(time.time() + period))

        return response

    def _should_skip_path(self, path: str) -> bool:
        """Check if the path should be skipped from rate limiting."""
        for skip_path in self.skip_paths:
            if path.startswith(skip_path):
                return True
        return False

    def _get_rate_for_path(self, path: str) -> str:
        """Get the rate limit for a specific path."""
        for path_pattern, rate in self.rate_limits.items():
            if path.startswith(path_pattern):
                return rate
        return self.default_rate

    def _load_key_function(self, key_function_path: Optional[str]) -> Callable:
        """Load the key function from settings or use default."""
        if not key_function_path:
            return default_key_function

        try:
            module_path, function_name = key_function_path.rsplit(".", 1)
            module = __import__(module_path, fromlist=[function_name])
            return getattr(module, function_name)
        except (ImportError, AttributeError) as e:
            raise ImproperlyConfigured(
                f"Cannot load key function {key_function_path}: {e}"
            ) from e

    def _parse_rate(self, rate: str) -> tuple[int, int]:
        """Parse rate limit string like "10/m" into (limit, period_seconds)."""
        try:
            limit_str, period_str = rate.split("/")
            limit = int(limit_str)

            period_map = {
                "s": 1,
                "m": 60,
                "h": 3600,
                "d": 86400,
            }

            if period_str not in period_map:
                raise ValueError(f"Unknown period: {period_str}")

            period = period_map[period_str]
            return limit, period

        except (ValueError, IndexError) as e:
            raise ImproperlyConfigured(f"Invalid rate format: {rate}") from e


def default_key_function(request: HttpRequest) -> str:
    """Generate default key function that uses the client IP address.

    Args:
        request: The Django request object

    Returns:
        Rate limit key based on client IP
    """
    # Get client IP, handling proxies
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR")

    return f"middleware:{ip}"


def user_key_function(request: HttpRequest) -> str:
    """
    Key function that uses the authenticated user ID.

    Args:
        request: The Django request object

    Returns:
        Rate limit key based on user ID or IP for anonymous users
    """
    if request.user.is_authenticated:
        return f"middleware:user:{request.user.id}"
    else:
        return default_key_function(request)
