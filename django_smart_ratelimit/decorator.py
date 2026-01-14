"""
Rate limiting decorator for Django views and functions.

This module provides the main @rate_limit decorator that can be applied
to Django views or any callable to enforce rate limiting.
"""

import functools
import importlib
import logging
import time
from typing import Any, Callable, Dict, Optional, Union, cast

from asgiref.sync import iscoroutinefunction, sync_to_async

from django.http import HttpResponse

from .algorithms import TokenBucketAlgorithm
from .backends import get_async_backend, get_backend
from .backends.utils import parse_rate, validate_rate_config
from .context import RateLimitContext
from .exceptions import BackendError
from .key_functions import generate_key
from .messages import ERROR_RATE_LIMIT_EXCEEDED
from .performance import get_metrics
from .utils import (
    HttpResponseTooManyRequests,
    add_rate_limit_headers,
    add_token_bucket_headers,
    get_rate_limit_error_message,
)

logger = logging.getLogger(__name__)


def default_exception_handler(request: Any, exception: Exception) -> HttpResponse:
    """Handle rate limit exceptions by default."""
    logger.error(f"Rate limit error: {exception}", exc_info=True)
    return HttpResponseTooManyRequests(ERROR_RATE_LIMIT_EXCEEDED)


def get_exception_handler() -> Callable:
    """Get configured exception handler or default."""
    from django_smart_ratelimit.config import get_settings

    settings = get_settings()
    handler_path = settings.exception_handler

    if handler_path:
        try:
            module_path, handler_name = handler_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            return getattr(module, handler_name)
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to import exception handler '{handler_path}': {e}")
            # Fallback to default

    return default_exception_handler


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


def _calculate_stable_reset_time_sliding_window(
    period: int, align_to_clock: bool = True
) -> int:
    """
    Calculate a stable reset time for sliding window algorithm.

    Instead of using the constantly moving window approach, we calculate a stable
    reset time based on fixed time buckets. This provides users with predictable
    reset times while maintaining the sliding window behavior for rate limiting.

    Args:
        period: Time period in seconds for the rate limit window
        align_to_clock: If True, align to clock boundaries. If False, use request time.

    Returns:
        Stable reset time as Unix timestamp
    """
    import time

    current_time = time.time()

    if align_to_clock:
        # Create stable time buckets based on the period (clock-aligned)
        # This ensures reset time changes predictably at clock boundaries
        bucket_start = int(current_time // period) * period
        reset_time = int(bucket_start + period)

        # If the calculated reset time is very close (within 5 seconds),
        # advance to the next bucket to give users reasonable time
        if reset_time - current_time < 5:
            reset_time += period
    else:
        # First-request aligned: reset time is simply current_time + period
        reset_time = int(current_time + period)

    return reset_time


def _get_reset_time(backend_instance: Any, limit_key: str, period: int) -> int:
    """Get reset time from backend with fallback."""
    # Get alignment setting
    try:
        from .config import get_settings

        align_to_clock = get_settings().align_window_to_clock
    except Exception:
        align_to_clock = True  # Default to clock-aligned

    try:
        reset_time = backend_instance.get_reset_time(limit_key)

        # Check if backend supports stable reset time for sliding window
        if hasattr(backend_instance, "get_stable_reset_time"):
            return backend_instance.get_stable_reset_time(limit_key, period)

        # For sliding window algorithms, provide stable reset time
        # by calculating when the oldest request in the window will expire
        if (
            hasattr(backend_instance, "_algorithm")
            and backend_instance._algorithm == "sliding_window"
        ):
            return _calculate_stable_reset_time_sliding_window(period, align_to_clock)

        return reset_time
    except (AttributeError, NotImplementedError) as e:
        logger.debug(f"Failed to get reset time from backend: {e}. Using fallback.")
        if align_to_clock:
            return _calculate_stable_reset_time_sliding_window(period, align_to_clock)
        return int(time.time() + period)


def _create_rate_limit_response(
    message: Optional[str] = None,
) -> HttpResponse:
    """Create a standard rate limit exceeded response."""
    if message is None:
        message = get_rate_limit_error_message(include_details=True)
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
    rate: Optional[str] = None,
    block: bool = True,
    backend: Optional[str] = None,
    skip_if: Optional[Callable] = None,
    algorithm: Optional[str] = None,
    algorithm_config: Optional[Dict[str, Any]] = None,
    settings: Optional[Any] = None,
) -> Callable:
    """Apply rate limiting to a view or function.

    Args:
        key: Rate limit key or callable that returns a key
        rate: Rate limit in format "10/m" (10 requests per minute).
              If None, uses default.
        block: If True, block requests that exceed the limit
        backend: Backend to use for rate limiting storage
        skip_if: Callable that returns True if rate limiting requests should be skipped
        algorithm: Algorithm to use ('sliding_window', 'fixed_window', 'token_bucket')
        algorithm_config: Configuration dict for the algorithm
        settings: Optional settings object (for dependency injection/testing)

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
        # Get settings if provided or load global
        _settings = settings
        if _settings is None:
            from .config import get_settings

            _settings = get_settings()

        _rate = rate
        if _rate is None:
            _rate = _settings.default_limit

        # Validate configuration early
        if algorithm is not None or algorithm_config is not None:
            validate_rate_config(_rate, algorithm, algorithm_config)

        if iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Check if rate limiting is globally disabled via RATELIMIT_ENABLE
                if not _settings.enabled:
                    return await func(*args, **kwargs)

                # Get the request object
                _request = _get_request_from_args(*args, **kwargs)
                if not _request:
                    return await func(*args, **kwargs)

                # Check skip_if condition
                if skip_if and callable(skip_if):
                    try:
                        should_skip = skip_if(_request)
                        if iscoroutinefunction(skip_if):
                            should_skip = await should_skip

                        if should_skip:
                            return await func(*args, **kwargs)
                    except Exception as e:
                        logger.warning(
                            "skip_if function failed: %s. Continuing.",
                            str(e),
                        )

                # Setup backend
                _backend = backend
                if _backend is None and settings is not None:
                    _backend = _settings.backend_class

                backend_instance = get_backend(_backend)
                if algorithm and hasattr(backend_instance, "config"):
                    backend_instance.config["algorithm"] = algorithm

                # Generate key
                limit_key = generate_key(key, _request, *args, **kwargs)
                if iscoroutinefunction(key):
                    # If key generation was async (unlikely with current implementation but possible)
                    # generate_key currently is sync.
                    pass

                # Resolve rate
                resolved_rate = _rate
                if callable(resolved_rate):
                    try:
                        resolved_rate = resolved_rate(None, _request)
                        if iscoroutinefunction(_rate):
                            resolved_rate = await resolved_rate
                    except TypeError:
                        resolved_rate = resolved_rate(_request)
                        if iscoroutinefunction(_rate):
                            resolved_rate = await resolved_rate

                limit, period = parse_rate(resolved_rate)

                # Check limit
                try:
                    # Use async increment if available
                    if hasattr(backend_instance, "aincr"):
                        current_count = await backend_instance.aincr(limit_key, period)
                    else:
                        current_count = await sync_to_async(backend_instance.incr)(
                            limit_key, period
                        )
                except BackendError as e:
                    # Handle backend errors
                    if not backend_instance.fail_open:
                        if _settings and _settings.exception_handler:
                            # Async handler support? Standard handler returns HttpResponse
                            handler = get_exception_handler()
                            return handler(_request, e)
                        else:
                            return _create_rate_limit_response(str(e))
                    current_count = 0

                # Check if limited
                if current_count > limit:
                    if block:
                        response = _create_rate_limit_response()
                        # We need reset time.
                        # backend.get_reset_time might be sync. Safe to call if it's just math/cache lookup?
                        # Ideally use async version if exists, or sync_to_async
                        reset_time = int(time.time() + period)
                        add_rate_limit_headers(response, limit, 0, reset_time)
                        return response

                # Call view
                response = await func(*args, **kwargs)

                # Add headers
                remaining = max(0, limit - current_count)
                reset_time = int(time.time() + period)

                if (
                    hasattr(response, "headers")
                    and "X-RateLimit-Limit" not in response.headers
                ):
                    add_rate_limit_headers(response, limit, remaining, reset_time)

                return response

        else:

            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Check if rate limiting is globally disabled via RATELIMIT_ENABLE
                if not _settings.enabled:
                    return func(*args, **kwargs)

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
                        logger.warning(
                            "skip_if function failed with error: %s. "
                            "Continuing with rate limiting.",
                            str(e),
                        )

                # Get the backend and configure algorithm
                _backend = backend
                if _backend is None and settings is not None:
                    _backend = _settings.backend_class

                backend_instance = get_backend(_backend)
                if algorithm and hasattr(backend_instance, "config"):
                    backend_instance.config["algorithm"] = algorithm

                # Generate the rate limit key and parse rate
                limit_key = generate_key(key, _request, *args, **kwargs)

                # Handle dynamic rate (callable)
                resolved_rate = _rate
                if callable(resolved_rate):
                    # Helper to call rate function with appropriate arguments
                    # Compatibility with django-ratelimit: func(group, request)
                    # But we don't strictly have 'group'. potentially pass key or None.
                    # Inspecting views.py: get_tier_rate(grupo, request)
                    try:
                        resolved_rate = resolved_rate(None, _request)
                    except TypeError:
                        # Fallback if function only takes one argument
                        try:
                            resolved_rate = resolved_rate(_request)
                        except TypeError:
                            # Last resort, maybe no args?
                            resolved_rate = resolved_rate()

                limit, period = parse_rate(resolved_rate)

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
    # Even though middleware processed the request, the decorator should still
    # track its own limit with its own key (they use different key patterns)

    ctx = RateLimitContext(
        key=limit_key,
        limit=limit,
        period=period,
        request=_request,
    )

    try:
        ctx = check_rate_limit(ctx, backend_instance)
    except BackendError as e:
        # Handle backend errors based on configuration
        handler = get_exception_handler()
        return handler(_request, e)

    # Check if the decorator's limit is exceeded
    if not ctx.allowed:
        if block:
            # Block the request and return 429
            return _handle_rate_limit_exceeded(
                backend_instance, limit_key, limit, period, block
            )
        else:
            # Non-blocking: execute function but mark as exceeded
            # Set a flag on the request to indicate rate limit was exceeded
            if args and hasattr(args[0], "META"):
                args[0].rate_limit_exceeded = True
            elif _request:
                _request.rate_limit_exceeded = True

            response = func(*args, **kwargs)
            reset_time: Union[int, float] = _get_reset_time(
                backend_instance, limit_key, period
            )
            add_rate_limit_headers(response, limit, 0, reset_time)
            return response

    # Execute the original function
    response = func(*args, **kwargs)

    # Update headers with the decorator's limit (this will override middleware headers)
    reset_time = ctx.reset_time or _get_reset_time(backend_instance, limit_key, period)
    add_rate_limit_headers(response, limit, ctx.remaining, reset_time)
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
                if _request:
                    _request.rate_limit_exceeded = True
                elif args and hasattr(args[0], "META"):
                    args[0].rate_limit_exceeded = True

                response = func(*args, **kwargs)
                add_token_bucket_headers(response, metadata, limit, period)
                return response

        # Execute the original function
        response = func(*args, **kwargs)
        add_token_bucket_headers(response, metadata, limit, period)
        return response

    except Exception as e:
        # If token bucket fails, fall back to standard rate limiting
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


def check_rate_limit(ctx: RateLimitContext, backend_instance: Any) -> RateLimitContext:
    """
    Check rate limit using context and backend.

    Args:
        ctx: The rate limit context
        backend_instance: The backend to use

    Returns:
        Updated context with result
    """
    start_time = time.time()
    try:
        # Check based on algorithm support in backend
        if hasattr(backend_instance, "increment"):
            current_count, remaining = backend_instance.increment(
                ctx.key, ctx.period, ctx.limit
            )
            ctx.current_count = current_count
            ctx.remaining = remaining
        else:
            # Basic incr
            current_count = backend_instance.incr(ctx.key, ctx.period)
            ctx.current_count = current_count
            ctx.remaining = max(0, ctx.limit - ctx.current_count)

        ctx.allowed = current_count <= ctx.limit
        ctx.reset_time = _get_reset_time(backend_instance, ctx.key, ctx.period)

    except Exception:
        # Re-raise to be handled by caller (who can decide on fail-open)
        raise

    ctx.check_duration = time.time() - start_time

    # Record metrics
    try:
        from .config import get_settings

        if get_settings().collect_metrics:
            get_metrics().record_request(
                key=ctx.key,
                allowed=ctx.allowed,
                duration_ms=ctx.check_duration * 1000,
                backend=backend_instance.__class__.__name__,
            )
    except Exception:
        pass  # nosec B110 - intentional: metrics should never break rate limiting

    return ctx


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
    # Create context
    ctx = RateLimitContext(
        request=_request,
        key=limit_key,
        limit=limit,
        period=period,
        backend_name=getattr(backend_instance, "name", str(type(backend_instance))),
    )

    try:
        ctx = check_rate_limit(ctx, backend_instance)
    except BackendError as e:
        handler = get_exception_handler()
        return handler(_request, e)

    # Attach context to request
    if _request:
        _request.ratelimit = ctx

    if not ctx.allowed:
        if block:
            response = _create_rate_limit_response()
            add_rate_limit_headers(response, ctx.limit, ctx.remaining, ctx.reset_time)
            return response
        else:
            # Add rate limit headers but don't block
            if _request:
                _request.rate_limit_exceeded = True
            elif args and hasattr(args[0], "META"):
                args[0].rate_limit_exceeded = True

            # Execute function
            response = func(*args, **kwargs)
            add_rate_limit_headers(response, ctx.limit, ctx.remaining, ctx.reset_time)
            return response

    # Execute the original function
    response = func(*args, **kwargs)

    # Add rate limit headers
    add_rate_limit_headers(
        response,
        ctx.limit,
        ctx.remaining,
        ctx.reset_time,
    )
    return response


def ratelimit_batch(
    checks: list[dict[str, Any]],
    block: bool = True,
    backend: Optional[str] = None,
) -> Callable:
    """
    Apply multiple rate limits in a batch.

    Args:
        checks: List of config dicts. Each dict must have 'rate' and 'key'.
               Optionally 'group' to Namespace the limit.
               Example: [
                   {"rate": "5/m", "key": "ip", "group": "ip_limit"},
                   {"rate": "100/h", "key": "user", "group": "user_limit"}
               ]
        block: If True, blocks if ANY limit is exceeded.
        backend: Backend to use.

    Returns:
        Decorated function.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _get_request_from_args(*args, **kwargs)
            if not request:
                return func(*args, **kwargs)

            backend_instance = get_backend(backend)

            # Prepare batch inputs
            batch_inputs = []
            parsed_configs = []

            for config in checks:
                rate_str = config.get("rate")
                key_func = config.get("key")

                # Check method constraint
                methods = config.get("method", None)
                if methods:
                    if isinstance(methods, str):
                        methods = [methods]
                    if request.method not in methods:
                        continue

                if not rate_str:
                    continue

                try:
                    limit, period = parse_rate(rate_str)
                    limit_key = generate_key(
                        cast(Union[str, Callable], key_func), request, *args, **kwargs
                    )

                    group = config.get("group")
                    if group:
                        limit_key = f"{group}:{limit_key}"

                    parsed_configs.append(config)
                    batch_inputs.append(
                        {"key": limit_key, "limit": limit, "period": period}
                    )
                except Exception as e:
                    logger.warning(f"Failed to prepare batch check item: {e}")
                    continue

            if not batch_inputs:
                return func(*args, **kwargs)

            try:
                # Execute batch check
                # BaseBackend.check_batch returns List[Tuple[bool, Dict]]
                results = backend_instance.check_batch(batch_inputs)
            except Exception as e:
                logger.error(f"Batch rate limit check failed: {e}")
                # Fail open
                return func(*args, **kwargs)

            # Analyze results
            blocked = False
            for i, (allowed, meta) in enumerate(results):
                if not allowed:
                    blocked = True
                    # We could inspect parsed_configs[i] here
                    break

            if blocked and block:
                return HttpResponseTooManyRequests(get_rate_limit_error_message())

            return func(*args, **kwargs)

        return wrapper

    return decorator


def aratelimit(
    key: Union[str, Callable] = "ip",
    rate: Optional[str] = None,
    method: Optional[Union[str, list]] = None,
    block: bool = True,
    backend: Optional[str] = None,
    **kwargs: Any,
) -> Callable:
    """
    Async rate limit decorator.

    Args:
        key: Rate limit key or callable
        rate: Rate limit string (e.g. "5/m")
        method: HTTP method(s) to apply limit to
        block: Whether to block on limit exceeded
        backend: Backend name (e.g. "redis").
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _get_request_from_args(*args, **kwargs)
            if not request:
                return await func(*args, **kwargs)

            # Check methods
            if method:
                methods = [method] if isinstance(method, str) else method
                if request.method not in methods:
                    return await func(*args, **kwargs)

            # Resolve rate
            rate_str = rate
            if rate_str is None:
                from .config import get_settings

                rate_str = get_settings().default_limit

            backend_instance = get_async_backend(backend)

            # Generate key and parse rate
            try:
                limit_key = generate_key(key, request, *args, **kwargs)
                limit, period = parse_rate(rate_str)
            except Exception as e:
                logger.warning(f"Async rate limit config error: {e}")
                return await func(*args, **kwargs)

            # Async check
            remaining = 0
            reset_time = int(time.time()) + period
            try:
                allowed, meta = await backend_instance.acheck_rate_limit(
                    limit_key, limit, period
                )
                # Extract remaining and reset from meta if available
                if meta:
                    remaining = meta.get("remaining", 0)
                    reset_time = meta.get("reset_time", reset_time)
            except Exception as e:
                logger.exception(f"Async backend check failed: {e}")
                allowed = True
                remaining = limit  # Assume full quota on error

            if not allowed and block:
                response = HttpResponseTooManyRequests(get_rate_limit_error_message())
                add_rate_limit_headers(response, limit, 0, reset_time)
                return response

            # Set flag on request for non-blocking mode
            if not allowed:
                request.rate_limit_exceeded = True

            # Call the view and add headers to response
            response = await func(*args, **kwargs)

            # Add rate limit headers to the response
            if hasattr(response, "__setitem__"):
                add_rate_limit_headers(response, limit, remaining, reset_time)

            return response

        return wrapper

    return decorator
