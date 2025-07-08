"""
Rate limiting decorator for Django views and functions.

This module provides the main @rate_limit decorator that can be applied
to Django views or any callable to enforce rate limiting.
"""

import functools
import logging
import time
from typing import Any, Callable, Optional, Union

from django.http import HttpRequest, HttpResponse

# Compatibility for Django < 4.2
try:
    from django.http import HttpResponseTooManyRequests  # type: ignore
except ImportError:

    class HttpResponseTooManyRequests(HttpResponse):  # type: ignore
        """HTTP 429 Too Many Requests response class."""

        status_code = 429


from django.core.exceptions import ImproperlyConfigured

from .backends import get_backend


def rate_limit(
    key: Union[str, Callable],
    rate: str,
    block: bool = True,
    backend: Optional[str] = None,
    skip_if: Optional[Callable] = None,
    algorithm: Optional[str] = None,
) -> Callable:
    """Apply rate limiting to a view or function.

    Args:
        key: Rate limit key or callable that returns a key
        rate: Rate limit in format "10/m" (10 requests per minute)
        block: If True, block requests that exceed the limit
        backend: Backend to use for rate limiting storage
        skip_if: Callable that returns True if rate limiting should be skipped
        algorithm: Algorithm to use ('sliding_window' or 'fixed_window')

    Returns:
        Decorated function with rate limiting applied

    Example:
        @rate_limit(key='user:{user.id}', rate='10/m')
        def my_view(request):
            return HttpResponse("Hello World")
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Get the request object
            request = None
            if args and hasattr(args[0], "META"):
                request = args[0]
            elif "request" in kwargs:
                request = kwargs["request"]

            if not request:
                # If no request found, skip rate limiting
                return func(*args, **kwargs)

            # Check skip_if condition
            if skip_if and callable(skip_if):
                try:
                    if skip_if(request):
                        return func(*args, **kwargs)
                except Exception as e:
                    # If skip_if fails, log the error and continue with rate limiting
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        "skip_if function failed with error: %s. "
                        "Continuing with rate limiting.",
                        str(e),
                    )

            # Get the backend
            backend_instance = get_backend(backend)

            # Set algorithm if specified and backend supports it
            if algorithm and hasattr(backend_instance, "config"):
                backend_instance.config["algorithm"] = algorithm

            # Generate the rate limit key
            limit_key = _generate_key(key, request, *args, **kwargs)

            # Parse rate limit
            limit, period = _parse_rate(rate)

            # Check rate limit
            current_count = backend_instance.incr(limit_key, period)

            if current_count > limit:
                if block:
                    return HttpResponseTooManyRequests(
                        "Rate limit exceeded. Please try again later."
                    )
                else:
                    # Add rate limit headers but don't block
                    response = func(*args, **kwargs)
                    if hasattr(response, "headers"):
                        response.headers["X-RateLimit-Limit"] = str(limit)
                        response.headers["X-RateLimit-Remaining"] = "0"
                        response.headers["X-RateLimit-Reset"] = str(
                            int(time.time() + period)
                        )
                    return response

            # Execute the original function
            response = func(*args, **kwargs)

            # Add rate limit headers
            if hasattr(response, "headers"):
                response.headers["X-RateLimit-Limit"] = str(limit)
                response.headers["X-RateLimit-Remaining"] = str(
                    max(0, limit - current_count)
                )
                response.headers["X-RateLimit-Reset"] = str(int(time.time() + period))

            return response

        return wrapper

    return decorator


def _generate_key(
    key: Union[str, Callable], request: HttpRequest, *args: Any, **kwargs: Any
) -> str:
    """Generate the rate limit key from the provided key template or callable."""
    if callable(key):
        return key(request, *args, **kwargs)

    # Simple template substitution
    if isinstance(key, str):
        if key == "ip":
            # Get IP address from request
            ip = request.META.get("REMOTE_ADDR", "unknown")
            return f"ip:{ip}"
        elif key == "user":
            # Get user ID from request
            if hasattr(request, "user") and request.user.is_authenticated:
                return f"user:{request.user.id}"
            else:
                # Fall back to IP if user is not authenticated
                ip = request.META.get("REMOTE_ADDR", "unknown")
                return f"ip:{ip}"
        else:
            # For other keys, return as-is
            return key

    raise ImproperlyConfigured(f"Invalid key type: {type(key)}")


def _parse_rate(rate: str) -> tuple[int, int]:
    """
    Parse rate limit string like "10/m" into (limit, period_seconds).

    Supported formats:
    - "10/s" - 10 requests per second
    - "100/m" - 100 requests per minute
    - "1000/h" - 1000 requests per hour
    - "10000/d" - 10000 requests per day
    """
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
        raise ImproperlyConfigured(
            f"Invalid rate format: {rate}. Use format like '10/m'"
        ) from e
