"""
Rate limiting middleware for Django applications.

This module provides middleware that can apply rate limiting to all requests
or specific patterns based on configuration.
"""

import time
from typing import Callable, Optional

from asgiref.sync import iscoroutinefunction

from django.http import HttpRequest, HttpResponse
from django.utils.decorators import sync_and_async_middleware

from .backends import get_backend
from .backends.utils import parse_rate
from .decorator import get_exception_handler
from .exceptions import BackendError, RateLimitException
from .key_functions import get_ip_key
from .utils import (
    HttpResponseTooManyRequests,
    add_rate_limit_headers,
    get_rate_for_path,
    get_rate_limit_error_message,
    load_function_from_string,
    should_skip_path,
    should_skip_static_media,
)


@sync_and_async_middleware
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
        from django_smart_ratelimit.config import get_settings

        settings = get_settings()
        self.enabled = settings.enabled  # Global enable/disable setting
        middleware_config = settings.middleware_config

        self.default_rate = middleware_config.get("DEFAULT_RATE", "100/m")
        self.backend_name = middleware_config.get("BACKEND", None)
        self.key_function = self._load_key_function(
            middleware_config.get("KEY_FUNCTION")
        )
        self.block = middleware_config.get("BLOCK", True)
        self.skip_paths = middleware_config.get("SKIP_PATHS", [])
        self.rate_limits = middleware_config.get("RATE_LIMITS", {})

        # Initialize backend
        self.backend = get_backend(self.backend_name)

        self.async_mode = iscoroutinefunction(self.get_response)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Process the request and apply rate limiting."""
        if self.async_mode:
            return self.__acall__(request)  # type: ignore[return-value]

        # Check if rate limiting is globally disabled via RATELIMIT_ENABLE setting
        if not self.enabled:
            return self.get_response(request)

        # Skip static and media files (uses Django's STATIC_URL/MEDIA_URL settings)
        # Security: Prevents rate limit bypass when custom prefixes are configured
        if should_skip_static_media(request):
            return self.get_response(request)

        # Check if path should be skipped based on configured patterns
        if should_skip_path(request.path, self.skip_paths):
            return self.get_response(request)

        # Get rate limit for this path
        rate = get_rate_for_path(request.path, self.rate_limits, self.default_rate)

        # Check if this is a path-specific rate limit (not the default)
        # If so, include the path in the key to avoid cross-contamination
        # between different rate limits
        is_path_specific = rate != self.default_rate

        # Generate key
        base_key = self.key_function(request)
        if is_path_specific:
            # Include path in key for path-specific limits
            key = f"{base_key}:{request.path.strip('/')}"
        else:
            key = base_key

        # Parse rate
        limit, period = parse_rate(rate)

        # Check rate limit
        try:
            current_count = self.backend.incr(key, period)
        except BackendError as e:
            # Handle backend errors based on configuration
            handler = get_exception_handler()
            return handler(request, e)

        # Mark that middleware has processed this request to prevent double-counting
        setattr(request, "_ratelimit_middleware_processed", True)
        setattr(request, "_ratelimit_middleware_limit", limit)
        setattr(
            request, "_ratelimit_middleware_remaining", max(0, limit - current_count)
        )

        if current_count > limit:
            if self.block:
                message = get_rate_limit_error_message(include_details=True)
                response = HttpResponseTooManyRequests(message)
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
            # Headers already exist (likely from decorator), check if middleware
            # is more restrictive
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

    async def __acall__(self, request: HttpRequest) -> HttpResponse:
        """Process the request and apply rate limiting asynchronously."""
        # Check if rate limiting is globally disabled via RATELIMIT_ENABLE setting
        if not self.enabled:
            return await self.get_response(request)

        # Skip static and media files (uses Django's STATIC_URL/MEDIA_URL settings)
        # Security: Prevents rate limit bypass when custom prefixes are configured
        if should_skip_static_media(request):
            return await self.get_response(request)

        # Check if path should be skipped based on configured patterns
        if should_skip_path(request.path, self.skip_paths):
            return await self.get_response(request)

        # Get rate limit for this path
        rate = get_rate_for_path(request.path, self.rate_limits, self.default_rate)

        # Check if this is a path-specific rate limit (not the default)
        # If so, include the path in the key to avoid cross-contamination
        # between different rate limits
        is_path_specific = rate != self.default_rate

        # Generate key
        base_key = self.key_function(request)
        if is_path_specific:
            # Include path in key for path-specific limits
            key = f"{base_key}:{request.path.strip('/')}"
        else:
            key = base_key

        # Parse rate
        limit, period = parse_rate(rate)

        # Check rate limit
        try:
            current_count = await self.backend.aincr(key, period)
        except BackendError as e:
            # Handle backend errors based on configuration
            handler = get_exception_handler()
            return handler(request, e)

        # Mark that middleware has processed this request to prevent double-counting
        setattr(request, "_ratelimit_middleware_processed", True)
        setattr(request, "_ratelimit_middleware_limit", limit)
        setattr(
            request, "_ratelimit_middleware_remaining", max(0, limit - current_count)
        )

        if current_count > limit:
            if self.block:
                message = get_rate_limit_error_message(include_details=True)
                # HttpResponseTooManyRequests is a subclass of HttpResponse, which is safe to return in async views
                response = HttpResponseTooManyRequests(message)
                add_rate_limit_headers(response, limit, 0, int(time.time() + period))
                return response

        # Process the request
        response = await self.get_response(request)

        # Only add rate limit headers if they haven't been set by a decorator
        # or if this middleware has a more restrictive limit
        # Note: Response might be streaming or async iterator in some contexts,
        # but django middleware usually processes the response object.
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

        return response

    def _load_key_function(self, key_function_path: Optional[str]) -> Callable:
        """Load the key function from settings or use default."""
        if not key_function_path:
            return default_key_function

        return load_function_from_string(key_function_path)

    def process_exception(
        self, request: HttpRequest, exception: Exception
    ) -> Optional[HttpResponse]:
        """Handle RateLimitException raised by views or other middleware."""
        if isinstance(exception, RateLimitException):
            handler = get_exception_handler()
            return handler(request, exception)
        return None


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
