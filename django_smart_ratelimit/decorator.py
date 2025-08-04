"""
Rate limiting decorator for Django views and functions.

This module provides the main @rate_limit decorator that can be applied
to Django views or any callable to enforce rate limiting.
"""

import functools
import logging
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


def _get_request_from_args(*args: Any, **kwargs: Any) -> Optional[Any]:
    """Extract request object from function arguments."""
    # For function-based views: request is first argument
    if args and hasattr(args[0], "META"):
        return args[0]
    # For class-based views/ViewSets: request is second argument after self
    elif len(args) > 1 and hasattr(args[1], "META"):
        return args[1]
    # Check kwargs for request (less common but possible)
    elif "request" in kwargs:
        return kwargs["request"]
    elif "_request" in kwargs:
        return kwargs["_request"]
    return None


def _get_reset_time(backend_instance: Any, limit_key: str, period: int) -> int:
    """Get reset time from backend with fallback."""
    try:
        return backend_instance.get_reset_time(limit_key)
    except (AttributeError, NotImplementedError):
        return int(time.time() + period)


def _create_rate_limit_response(
    message: str = "Rate limit exceeded. Please try again later.",
) -> HttpResponse:
    """Create a standard rate limit exceeded response."""
    return HttpResponseTooManyRequests(message)


def _handle_rate_limit_exceeded(
    backend_instance: Any, limit_key: str, limit: int, period: int, block: bool
) -> Optional[HttpResponse]:
    """Handle rate limit exceeded scenario."""
    if block:
        response = _create_rate_limit_response()
        reset_time = _get_reset_time(backend_instance, limit_key, period)
        add_rate_limit_headers(response, limit, 0, reset_time)
        return response
    return None


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
            # Get the request object
            _request = _get_request_from_args(*args, **kwargs)
            if not _request:
                # If no request found, skip rate limiting
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
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        "skip_if function failed with error: %s. "
                        "Continuing with rate limiting.",
                        str(e),
                    )

            # Get the backend and configure algorithm
            backend_instance = get_backend(backend)
            if algorithm and hasattr(backend_instance, "config"):
                backend_instance.config["algorithm"] = algorithm

            # Generate the rate limit key and parse rate
            limit_key = generate_key(key, _request, *args, **kwargs)
            limit, period = parse_rate(rate)

            # Handle middleware vs decorator scenarios
            if middleware_processed:
                return _handle_middleware_processed_request(
                    func,
                    _request,
                    args,
                    kwargs,
                    backend_instance,
                    limit_key,
                    limit,
                    period,
                    block,
                )

            # Handle algorithm-specific logic
            if algorithm == "token_bucket":
                return _handle_token_bucket_algorithm(
                    func,
                    _request,
                    args,
                    kwargs,
                    backend_instance,
                    limit_key,
                    limit,
                    period,
                    block,
                    algorithm_config,
                )

            # Standard rate limiting (sliding_window or fixed_window)
            return _handle_standard_rate_limiting(
                func,
                _request,
                args,
                kwargs,
                backend_instance,
                limit_key,
                limit,
                period,
                block,
            )

        return wrapper

    return decorator


def _handle_middleware_processed_request(
    func: Callable,
    _request: Any,
    args: tuple,
    kwargs: dict,
    backend_instance: Any,
    limit_key: str,
    limit: int,
    period: int,
    block: bool,
) -> Any:
    """Handle request when middleware has already processed it."""
    # Since middleware has already processed this request, we should not increment again
    # Just get the current count to check against the decorator's limit
    current_count = backend_instance.get_count(limit_key, period)

    # Check if the decorator's limit is exceeded
    if current_count > limit:
        return _handle_rate_limit_exceeded(
            backend_instance, limit_key, limit, period, block
        )

    # Execute the original function
    response = func(*args, **kwargs)

    # Calculate remaining based on the decorator's limit
    decorator_remaining = max(0, limit - current_count)
    reset_time = _get_reset_time(backend_instance, limit_key, period)

    # Update headers with the decorator's limit (this will override middleware headers)
    add_rate_limit_headers(response, limit, decorator_remaining, reset_time)
    return response


def _handle_token_bucket_algorithm(
    func: Callable,
    _request: Any,
    args: tuple,
    kwargs: dict,
    backend_instance: Any,
    limit_key: str,
    limit: int,
    period: int,
    block: bool,
    algorithm_config: Optional[Dict[str, Any]],
) -> Any:
    """Handle token bucket algorithm logic."""
    try:
        algorithm_instance = TokenBucketAlgorithm(algorithm_config)
        is_allowed, metadata = algorithm_instance.is_allowed(
            backend_instance, limit_key, limit, period
        )

        if not is_allowed:
            if block:
                return _create_rate_limit_response()
            else:
                # Add rate limit headers but don't block
                response = func(*args, **kwargs)
                add_token_bucket_headers(response, metadata, limit, period)
                return response

        # Execute the original function
        response = func(*args, **kwargs)
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
        # Fall back to standard algorithm
        return _handle_standard_rate_limiting(
            func,
            _request,
            args,
            kwargs,
            backend_instance,
            limit_key,
            limit,
            period,
            block,
        )


def _handle_standard_rate_limiting(
    func: Callable,
    _request: Any,
    args: tuple,
    kwargs: dict,
    backend_instance: Any,
    limit_key: str,
    limit: int,
    period: int,
    block: bool,
) -> Any:
    """Handle standard rate limiting (sliding_window or fixed_window)."""
    current_count = backend_instance.incr(limit_key, period)

    if current_count > limit:
        rate_limit_response = _handle_rate_limit_exceeded(
            backend_instance, limit_key, limit, period, block
        )
        if rate_limit_response:
            return rate_limit_response
        else:
            # Add rate limit headers but don't block
            response = func(*args, **kwargs)
            reset_time = _get_reset_time(backend_instance, limit_key, period)
            add_rate_limit_headers(response, limit, 0, reset_time)
            return response

    # Execute the original function
    response = func(*args, **kwargs)

    # Add rate limit headers
    reset_time = _get_reset_time(backend_instance, limit_key, period)
    add_rate_limit_headers(
        response,
        limit,
        max(0, limit - current_count),
        reset_time,
    )
    return response
