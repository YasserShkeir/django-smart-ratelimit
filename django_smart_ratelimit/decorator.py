"""
Rate limiting decorator for Django views and functions.

This module provides the main @rate_limit decorator that can be applied
to Django views or any callable to enforce rate limiting.
"""

import functools
import time
from typing import Any, Callable, Dict, Optional, Union

from django.http import HttpResponse

from .algorithms import TokenBucketAlgorithm
from .backends import get_backend
from .utils import (
    add_rate_limit_headers,
    add_token_bucket_headers,
    generate_key,
    parse_rate,
    validate_rate_config,
)

# Compatibility for Django < 4.2
try:
    from django.http import HttpResponseTooManyRequests  # type: ignore
except ImportError:

    class HttpResponseTooManyRequests(HttpResponse):  # type: ignore
        """HTTP 429 Too Many Requests response class."""

        status_code = 429


def rate_limit(
    key: Union[str, Callable],
    rate: str,
    block: bool = True,
    backend: Optional[str] = None,
    skip_if: Optional[Callable] = None,
    algorithm: Optional[str] = None,
    algorithm_config: Optional[Dict[str, Any]] = None,
) -> Callable:
    """Apply rate limiting to a view or function.

    Args:
        key: Rate limit key or callable that returns a key
        rate: Rate limit in format "10/m" (10 requests per minute)
        block: If True, block requests that exceed the limit
        backend: Backend to use for rate limiting storage
        skip_if: Callable that returns True if rate limiting should be skipped
        algorithm: Algorithm to use ('sliding_window', 'fixed_window', 'token_bucket')
        algorithm_config: Configuration dict for the algorithm

    Returns:
        Decorated function with rate limiting applied

    Examples:
        # Basic rate limiting
        @rate_limit(key='user:{user.id}', rate='10/m')
        def my_view(_request):
            return HttpResponse("Hello World")

        # Token bucket with burst capability
        @rate_limit(
            key='api_key:{_request.api_key}',
            rate='10/m',
            algorithm='token_bucket',
            algorithm_config={'bucket_size': 20}
        )
        def api_view(_request):
            return JsonResponse({'status': 'ok'})
    """

    def decorator(func: Callable) -> Callable:
        # Validate configuration early
        if algorithm is not None or algorithm_config is not None:
            validate_rate_config(rate, algorithm, algorithm_config)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Get the _request object
            _request = None
            if args and hasattr(args[0], "META"):
                _request = args[0]
            elif "_request" in kwargs:
                _request = kwargs["_request"]

            if not _request:
                # If no _request found, skip rate limiting
                return func(*args, **kwargs)

            # Check if middleware has already processed this request
            # to avoid double-counting
            middleware_processed = getattr(
                _request, "_ratelimit_middleware_processed", False
            )

            # Check skip_if condition
            if skip_if and callable(skip_if):
                try:
                    if skip_if(_request):
                        return func(*args, **kwargs)
                except Exception as e:
                    # Log the error but don't break the request
                    import logging

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
            limit_key = generate_key(key, _request, *args, **kwargs)

            # Parse rate limit
            limit, period = parse_rate(rate)

            # If middleware already processed this request, check if we need
            # to apply more restrictive limits
            if middleware_processed:
                # Get current count without incrementing again
                try:
                    current_count = backend_instance.get_count(limit_key)
                except AttributeError:
                    # Fallback for backends that don't support get_count
                    current_count = 0

                # Check if the decorator's limit is exceeded
                if current_count > limit:
                    if block:
                        response = HttpResponseTooManyRequests(
                            "Rate limit exceeded. Please try again later."
                        )
                        add_rate_limit_headers(
                            response, limit, 0, int(time.time() + period)
                        )
                        return response

                # Execute the original function
                response = func(*args, **kwargs)

                # Calculate remaining based on the decorator's limit (more restrictive)
                decorator_remaining = max(0, limit - current_count)

                # Update headers with the decorator's limit (which is more restrictive)
                add_rate_limit_headers(
                    response,
                    limit,  # Use decorator limit, not effective_limit
                    decorator_remaining,
                    int(time.time() + period),
                )

                return response

            # Parse rate limit
            limit, period = parse_rate(rate)

            # Handle algorithm-specific logic
            if algorithm == "token_bucket":
                # Use token bucket algorithm
                try:
                    algorithm_instance = TokenBucketAlgorithm(algorithm_config)
                    is_allowed, metadata = algorithm_instance.is_allowed(
                        backend_instance, limit_key, limit, period
                    )

                    if not is_allowed:
                        if block:
                            return HttpResponseTooManyRequests(
                                "Rate limit exceeded. Please try again later."
                            )
                        else:
                            # Add rate limit headers but don't block
                            response = func(*args, **kwargs)
                            add_token_bucket_headers(response, metadata, limit, period)
                            return response

                    # Execute the original function
                    response = func(*args, **kwargs)

                    # Add rate limit headers
                    add_token_bucket_headers(response, metadata, limit, period)

                    return response

                except Exception as e:
                    # If token bucket fails, fall back to standard rate limiting
                    logger = logging.getLogger(__name__)
                    logger.error(
                        "Token bucket algorithm failed with error: %s. "
                        "Falling back to standard rate limiting.",
                        str(e),
                    )
                    # Continue with standard algorithm below

            # Standard rate limiting (sliding_window or fixed_window)
            current_count = backend_instance.incr(limit_key, period)

            if current_count > limit:
                if block:
                    return HttpResponseTooManyRequests(
                        "Rate limit exceeded. Please try again later."
                    )
                else:
                    # Add rate limit headers but don't block
                    response = func(*args, **kwargs)
                    add_rate_limit_headers(
                        response, limit, 0, int(time.time() + period)
                    )
                    return response

            # Execute the original function
            response = func(*args, **kwargs)

            # Add rate limit headers
            add_rate_limit_headers(
                response,
                limit,
                max(0, limit - current_count),
                int(time.time() + period),
            )

            return response

        return wrapper

    return decorator
