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

from .adaptive import AdaptiveRateLimiter, get_adaptive_limiter
from .algorithms import TokenBucketAlgorithm
from .backends import get_async_backend, get_backend
from .backends.utils import parse_rate, validate_rate_config
from .context import RateLimitContext
from .exceptions import BackendError, KeyGenerationError
from .key_functions import generate_key
from .messages import ERROR_RATE_LIMIT_EXCEEDED
from .performance import get_metrics
from .pipeline import (
    POLICY_ALLOW,
    POLICY_DENY,
    apply_policy_lists,
    handle_shadow_decision,
    resolve_effective_rate,
)
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


# In-process cache for first-request-aligned reset times. When
# ``align_window_to_clock`` is False, the very first request in a window
# establishes a reset_time of ``now + period``; subsequent calls within that
# window must return the SAME value, otherwise X-RateLimit-Reset drifts
# forward on every call and clients can never sleep accurately. This dict
# is keyed by ``limit_key`` and stores ``(reset_time, expires_at)``. Entries
# are pruned when they're past their reset_time, which bounds the dict size
# at roughly the number of currently-active rate-limit keys.
_reset_time_guard = __import__("threading").Lock()
_reset_time_cache: Dict[str, tuple] = {}


def _get_first_aligned_reset_time(limit_key: str, period: int) -> int:
    """Return the cached first-request reset time, computing it if absent.

    Across calls within the same window we want the SAME timestamp returned —
    that's what makes ``Retry-After`` and ``X-RateLimit-Reset`` honest. Across
    workers, multiple workers may compute slightly different reset times for
    the same key (each worker has its own cache); that's an acceptable price
    for keeping this hot path lock-free per worker. Operators who need
    cross-worker stability should switch to ``align_window_to_clock=True``,
    which is the default.
    """
    now = time.time()
    cached = _reset_time_cache.get(limit_key)
    if cached and cached[0] > now:
        return int(cached[0])

    with _reset_time_guard:
        # Re-check under the guard in case a concurrent caller filled it.
        cached = _reset_time_cache.get(limit_key)
        if cached and cached[0] > now:
            return int(cached[0])

        reset_time = int(now + period)
        _reset_time_cache[limit_key] = (reset_time, reset_time)

        # Opportunistic cleanup: drop any entries whose reset has already
        # passed. We do this inside the guard while we hold it. Bounded at
        # 64 evictions per call so a giant cache can't stall a single
        # request.
        if len(_reset_time_cache) > 256:
            stale = [k for k, v in _reset_time_cache.items() if v[1] <= now][:64]
            for k in stale:
                _reset_time_cache.pop(k, None)

        return reset_time


def _calculate_stable_reset_time_sliding_window(
    period: int,
    align_to_clock: bool = True,
    limit_key: Optional[str] = None,
) -> int:
    """
    Calculate a stable reset time for sliding window algorithm.

    Two stability modes are supported:

    * ``align_to_clock=True`` (default): compute reset time from the current
      clock-aligned bucket boundary. Stable across workers and processes
      because everyone agrees on the wall clock; recommended for production.

    * ``align_to_clock=False``: use first-request semantics — the reset time
      is ``now + period`` for the first caller, and subsequent callers within
      the same window get back the cached value. ``limit_key`` MUST be
      provided in this mode; without it we cannot key the cache and would
      regress to the old drifting behavior. If it's missing we fall back to
      the clock-aligned calculation as a safer default.

    Args:
        period: Time period in seconds for the rate limit window
        align_to_clock: If True, align to clock boundaries. If False, use
            first-request time anchored per ``limit_key``.
        limit_key: Required when ``align_to_clock=False``; ignored otherwise.

    Returns:
        Stable reset time as Unix timestamp
    """
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
        return reset_time

    if limit_key:
        return _get_first_aligned_reset_time(limit_key, period)

    # No key to anchor first-request alignment — return the drifting
    # ``now + period`` value. This preserves backward compatibility for
    # direct callers that pass no key; use _get_reset_time() or supply a
    # limit_key to opt into stable Retry-After values.
    return int(current_time + period)


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
            return _calculate_stable_reset_time_sliding_window(
                period, align_to_clock, limit_key=limit_key
            )

        return reset_time
    except (AttributeError, NotImplementedError) as e:
        logger.debug(f"Failed to get reset time from backend: {e}. Using fallback.")
        if align_to_clock:
            return _calculate_stable_reset_time_sliding_window(
                period, align_to_clock, limit_key=limit_key
            )
        # First-request-aligned fallback: cache by limit_key so repeat callers
        # within the window see the same Retry-After.
        return _get_first_aligned_reset_time(limit_key, period)


def _create_rate_limit_response(
    message: Optional[str] = None,
    request: Optional[Any] = None,
    response_callback: Optional[Callable] = None,
) -> HttpResponse:
    """Create a rate limit exceeded response.

    Supports custom responses via:
    1. A ``response_callback`` callable passed to the decorator
    2. A global ``RATELIMIT_RESPONSE_HANDLER`` setting (dotted path to
       a callable or a template name like ``"429.html"``)
    3. Content-negotiated JSON when the request Accept header is
       ``application/json``
    4. The default plain-text 429 response

    Args:
        message: Optional override message.
        request: The Django request (used for content negotiation).
        response_callback: A callable ``(request) -> HttpResponse``.
    """
    # 1. Per-decorator callback
    if response_callback is not None:
        try:
            return response_callback(request)
        except Exception as e:
            logger.warning("Custom response_callback failed: %s", e)

    # 2. Global handler from settings
    try:
        from .config import get_settings

        handler_path = get_settings().ratelimit_response_handler
        if handler_path:
            response = _invoke_global_response_handler(handler_path, request)
            if response is not None:
                return response
    except Exception as e:
        logger.warning("Global RATELIMIT_RESPONSE_HANDLER failed: %s", e)

    # 3. Content negotiation: return JSON for API clients
    if request is not None:
        accept = getattr(request, "META", {}).get("HTTP_ACCEPT", "")
        if "application/json" in accept:
            from django.http import JsonResponse

            body: Dict[str, Any] = {
                "detail": "Rate limit exceeded. Please try again later.",
            }
            return JsonResponse(body, status=429)

    # 4. Default plain-text
    if message is None:
        message = get_rate_limit_error_message(include_details=True)
    return HttpResponseTooManyRequests(message)


def _invoke_global_response_handler(
    handler_path: str, request: Optional[Any]
) -> Optional[HttpResponse]:
    """Invoke the globally configured response handler.

    ``handler_path`` can be either:
    * A dotted path to a callable (e.g. ``"myapp.views.rate_limited"``)
    * A template name (e.g. ``"429.html"``) \u2014 rendered with status 429.
    """
    # Try as a callable first
    if "." in handler_path and not handler_path.endswith((".html", ".htm", ".txt")):
        try:
            module_path, fn_name = handler_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            handler = getattr(module, fn_name)
            return handler(request)
        except (ImportError, AttributeError, TypeError):
            pass

    # Try as a template name
    try:
        from django.template.loader import render_to_string

        html = render_to_string(handler_path, request=request)
        return HttpResponse(html, status=429, content_type="text/html")
    except Exception:
        return None


def _handle_rate_limit_exceeded(
    backend_instance: Any,
    limit_key: str,
    limit: int,
    period: int,
    block: bool,
    request: Optional[Any] = None,
    response_callback: Optional[Callable] = None,
) -> Optional[HttpResponse]:
    """Handle rate limit exceeded scenario."""
    if block:
        response = _create_rate_limit_response(
            request=request, response_callback=response_callback
        )
        reset_time = _get_reset_time(backend_instance, limit_key, period)
        add_rate_limit_headers(response, limit, 0, reset_time)
        return response
    return None


def _apply_adaptive_limit(
    adaptive: Optional[Union[str, AdaptiveRateLimiter]], base_limit: int
) -> int:
    """
    Apply adaptive rate limiting to get the effective limit.

    Args:
        adaptive: Name of registered AdaptiveRateLimiter, an instance, or None.
        base_limit: The base limit from the rate string.

    Returns:
        The effective limit (adjusted by adaptive limiter if provided).
    """
    if adaptive is None:
        return base_limit

    limiter: Optional[AdaptiveRateLimiter] = None

    if isinstance(adaptive, str):
        # Look up registered limiter by name
        limiter = get_adaptive_limiter(adaptive)
        if limiter is None:
            logger.warning(
                f"Adaptive rate limiter '{adaptive}' not found. "
                f"Using base limit {base_limit}."
            )
            return base_limit
    elif isinstance(adaptive, AdaptiveRateLimiter):
        limiter = adaptive
    else:
        logger.warning(
            f"Invalid adaptive parameter type: {type(adaptive)}. "
            f"Expected str or AdaptiveRateLimiter. Using base limit {base_limit}."
        )
        return base_limit

    try:
        effective_limit = limiter.get_effective_limit()
        logger.debug(
            f"Adaptive rate limit: base={base_limit}, "
            f"effective={effective_limit}, load={limiter.get_current_load():.2f}"
        )
        return effective_limit
    except Exception as e:
        logger.warning(
            f"Failed to get adaptive limit: {e}. Using base limit {base_limit}."
        )
        return base_limit


def rate_limit(
    key: Union[str, Callable],
    rate: Optional[str] = None,
    block: bool = True,
    backend: Optional[str] = None,
    skip_if: Optional[Callable] = None,
    algorithm: Optional[str] = None,
    algorithm_config: Optional[Dict[str, Any]] = None,
    settings: Optional[Any] = None,
    adaptive: Optional[Union[str, AdaptiveRateLimiter]] = None,
    response_callback: Optional[Callable] = None,
    cost: Union[int, Callable[..., int]] = 1,
    shadow: bool = False,
    allow_list: Any = None,
    deny_list: Any = None,
) -> Callable:
    """Apply rate limiting to a view or function.

    Args:
        key: Rate limit key or callable that returns a key. Since v3.0.0, a
            callable that returns an empty string or None raises
            ``KeyGenerationError`` instead of silently collapsing onto a
            shared bucket. If you want to skip rate limiting for a specific
            request, use ``skip_if=`` instead.
        rate: Rate limit in format "10/m" (10 requests per minute).
              If None, uses default. Note: When using adaptive rate limiting,
              this value is used as the period only; the limit is determined
              by the AdaptiveRateLimiter.
        block: If True, block requests that exceed the limit
        backend: Backend to use for rate limiting storage
        skip_if: Callable that returns True if rate limiting requests should be skipped
        algorithm: Algorithm to use ('sliding_window', 'fixed_window', 'token_bucket')
        algorithm_config: Configuration dict for the algorithm
        settings: Optional settings object (for dependency injection/testing)
        adaptive: Name of registered AdaptiveRateLimiter or an instance.
                  When provided, the rate limit is dynamically adjusted based
                  on system load. The 'rate' parameter's limit is ignored and
                  replaced with the adaptive limiter's effective limit.
        response_callback: Optional callable ``(request) -> HttpResponse`` for
            custom 429 responses. Overrides the global
            ``RATELIMIT_RESPONSE_HANDLER`` setting.
        cost: **New in v3.0.0** — cost of each request (default 1). Accepts an
            int or a callable ``(request) -> int``. Useful for weighted rate
            limits where expensive operations consume more of the budget.
            Currently honored by token_bucket algorithm natively and by
            standard algorithms via repeated increments.
        shadow: **New in v3.0.0** — when True, rate-limit decisions are
            evaluated and logged (including OTel events) but never actually
            enforced. Use this to roll out a new limit safely: observe what
            would be blocked before flipping to enforcement.
        allow_list: **New in v3.0.0** — CIDR allow-list of IPs that bypass
            rate limiting entirely. Accepts an :class:`IPList`, iterable of
            CIDRs, file path, or URL.
        deny_list: **New in v3.0.0** — CIDR deny-list of IPs to block before
            rate limiting runs. Takes precedence over allow_list.


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

        # Adaptive rate limiting based on system load
        from django_smart_ratelimit.adaptive import create_adaptive_limiter
        create_adaptive_limiter("api", base_limit=100, min_limit=10, max_limit=200)

        @rate_limit(key='ip', rate='100/m', adaptive='api')
        def api_view(_request):
            return JsonResponse({'status': 'ok'})

        # Shadow mode for safe rollout (v3.0.0)
        @rate_limit(key='ip', rate='10/m', shadow=True)
        def my_view(_request):
            ...

        # Cost-based weighted limiting (v3.0.0)
        @rate_limit(
            key='user', rate='100/m',
            cost=lambda req: 5 if req.path.startswith('/export') else 1,
        )
        def my_view(_request):
            ...
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

                # Allow/deny list policy — evaluated before rate check so a
                # deny-listed IP is blocked immediately and an allow-listed IP
                # skips the backend entirely. In shadow mode a deny still logs
                # but passes through so operators can tune the list safely.
                policy = apply_policy_lists(
                    _request, allow_list=allow_list, deny_list=deny_list
                )
                if policy == POLICY_ALLOW:
                    return await func(*args, **kwargs)
                if policy == POLICY_DENY:
                    if shadow:
                        handle_shadow_decision(
                            allowed=False,
                            shadow=True,
                            request=_request,
                            key="deny_list",
                            limit=0,
                            remaining=0,
                            algorithm="policy",
                            backend="decorator",
                        )
                    else:
                        response = _create_rate_limit_response(
                            request=_request,
                            response_callback=response_callback,
                        )
                        add_rate_limit_headers(response, 0, 0, int(time.time()))
                        return response

                # Setup backend
                _backend = backend
                if _backend is None and settings is not None:
                    _backend = _settings.backend_class

                backend_instance = get_backend(_backend)
                if algorithm and hasattr(backend_instance, "config"):
                    backend_instance.config["algorithm"] = algorithm

                # Resolve key + rate + cost + adaptive in one place (v3 pipeline)
                try:
                    resolved = resolve_effective_rate(
                        key=key,
                        rate=_rate,
                        request=_request,
                        args=args,
                        kwargs=kwargs,
                        adaptive=adaptive,
                        cost=cost,
                    )
                except KeyGenerationError:
                    # Configuration error — let it surface so callers fix it.
                    raise

                limit_key = resolved.key
                limit = resolved.limit
                period = resolved.period
                request_cost = resolved.cost

                # Check limit
                try:
                    # Use async increment if available
                    if hasattr(backend_instance, "aincr"):
                        current_count = await backend_instance.aincr(
                            limit_key, period, request_cost
                        )
                    else:
                        current_count = await sync_to_async(backend_instance.incr)(
                            limit_key, period, request_cost
                        )
                except TypeError:
                    # Backend's incr doesn't accept cost yet (pre-v3 custom
                    # backend). Fall back to single-token incr and repeat if
                    # cost > 1 so weighted limiting still works.
                    if hasattr(backend_instance, "aincr"):
                        current_count = await backend_instance.aincr(limit_key, period)
                    else:
                        current_count = await sync_to_async(backend_instance.incr)(
                            limit_key, period
                        )
                    for _ in range(request_cost - 1):
                        if hasattr(backend_instance, "aincr"):
                            current_count = await backend_instance.aincr(
                                limit_key, period
                            )
                        else:
                            current_count = await sync_to_async(backend_instance.incr)(
                                limit_key, period
                            )
                except BackendError as e:
                    # Handle backend errors
                    if not backend_instance.fail_open:
                        if _settings and _settings.exception_handler:
                            handler = get_exception_handler()
                            return handler(_request, e)
                        else:
                            return _create_rate_limit_response(
                                str(e),
                                request=_request,
                                response_callback=response_callback,
                            )
                    current_count = 0

                # Check if limited, apply shadow mode
                is_allowed = current_count <= limit
                remaining = max(0, limit - current_count)
                decision = handle_shadow_decision(
                    allowed=is_allowed,
                    shadow=shadow,
                    request=_request,
                    key=limit_key,
                    limit=limit,
                    remaining=remaining,
                    algorithm=algorithm or "sliding_window",
                    backend=type(backend_instance).__name__,
                    cost=request_cost,
                )

                if not decision.allow:
                    if block:
                        response = _create_rate_limit_response(
                            request=_request,
                            response_callback=response_callback,
                        )
                        reset_time = int(time.time() + period)
                        add_rate_limit_headers(response, limit, 0, reset_time)
                        return response

                # Call view
                response = await func(*args, **kwargs)

                # Add headers
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

                # Allow/deny list policy check (v3) — evaluated before any
                # backend work so deny-listed IPs never touch the cache. In
                # shadow mode a deny still logs but passes through.
                policy = apply_policy_lists(
                    _request, allow_list=allow_list, deny_list=deny_list
                )
                if policy == POLICY_ALLOW:
                    return func(*args, **kwargs)
                if policy == POLICY_DENY:
                    if shadow:
                        handle_shadow_decision(
                            allowed=False,
                            shadow=True,
                            request=_request,
                            key="deny_list",
                            limit=0,
                            remaining=0,
                            algorithm="policy",
                            backend="decorator",
                        )
                    else:
                        response = _create_rate_limit_response(
                            request=_request,
                            response_callback=response_callback,
                        )
                        add_rate_limit_headers(response, 0, 0, int(time.time()))
                        return response

                # Get the backend and configure algorithm
                _backend = backend
                if _backend is None and settings is not None:
                    _backend = _settings.backend_class

                backend_instance = get_backend(_backend)
                if algorithm and hasattr(backend_instance, "config"):
                    backend_instance.config["algorithm"] = algorithm

                # Resolve key, rate, cost, adaptive via the v3 pipeline.
                try:
                    resolved = resolve_effective_rate(
                        key=key,
                        rate=_rate,
                        request=_request,
                        args=args,
                        kwargs=kwargs,
                        adaptive=adaptive,
                        cost=cost,
                    )
                except KeyGenerationError:
                    raise

                limit_key = resolved.key
                limit = resolved.limit
                period = resolved.period
                request_cost = resolved.cost

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
                        response_callback=response_callback,
                        shadow=shadow,
                        cost=request_cost,
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
                        response_callback=response_callback,
                        shadow=shadow,
                        cost=request_cost,
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
                    response_callback=response_callback,
                    shadow=shadow,
                    cost=request_cost,
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
    response_callback: Optional[Callable] = None,
    shadow: bool = False,
    cost: int = 1,
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
        ctx = check_rate_limit(ctx, backend_instance, cost=cost)
    except BackendError as e:
        # Handle backend errors based on configuration
        handler = get_exception_handler()
        return handler(_request, e)

    # Apply shadow mode: if shadow=True and the request would have been
    # blocked, flip the decision to allow but emit a structured log line.
    decision = handle_shadow_decision(
        allowed=ctx.allowed,
        shadow=shadow,
        request=_request,
        key=limit_key,
        limit=limit,
        remaining=ctx.remaining,
        algorithm=getattr(backend_instance, "_algorithm", "sliding_window"),
        backend=type(backend_instance).__name__,
        cost=cost,
    )
    ctx_allowed = decision.allow

    # Check if the decorator's limit is exceeded
    if not ctx_allowed:
        if block:
            # Block the request and return 429
            return _handle_rate_limit_exceeded(
                backend_instance,
                limit_key,
                limit,
                period,
                block,
                request=_request,
                response_callback=response_callback,
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
    response_callback: Optional[Callable] = None,
    shadow: bool = False,
    cost: int = 1,
) -> Any:
    """Handle token bucket algorithm logic."""
    try:
        algorithm_instance = TokenBucketAlgorithm(algorithm_config)
        # Token bucket natively supports cost via its ``tokens_requested`` arg.
        try:
            is_allowed, metadata = algorithm_instance.is_allowed(
                backend_instance, limit_key, limit, period, tokens_requested=cost
            )
        except TypeError:
            # Older algorithm signature without tokens_requested kwarg —
            # fall back to 1 token per request.
            is_allowed, metadata = algorithm_instance.is_allowed(
                backend_instance, limit_key, limit, period
            )

        # Apply shadow mode.
        decision = handle_shadow_decision(
            allowed=is_allowed,
            shadow=shadow,
            request=_request,
            key=limit_key,
            limit=limit,
            remaining=int(metadata.get("tokens_remaining", 0)) if metadata else 0,
            algorithm="token_bucket",
            backend=type(backend_instance).__name__,
            cost=cost,
        )
        is_allowed = decision.allow

        if not is_allowed:
            if block:
                return _create_rate_limit_response(
                    request=_request,
                    response_callback=response_callback,
                )
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
        # Fall back to standard algorithm, preserving shadow + cost
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
            response_callback=response_callback,
            shadow=shadow,
            cost=cost,
        )


def check_rate_limit(
    ctx: RateLimitContext,
    backend_instance: Any,
    cost: int = 1,
) -> RateLimitContext:
    """
    Check rate limit using context and backend.

    Args:
        ctx: The rate limit context
        backend_instance: The backend to use
        cost: Number of tokens / increments to consume for this request.
              New in v3.0.0 — defaults to 1 for backwards compatibility.

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
            # Cost > 1 with a backend that doesn't support cost natively:
            # repeat the increment so weighted limiting still works. This is
            # non-atomic per-token; backends that care should implement a
            # native incr(..., cost=N).
            for _ in range(cost - 1):
                current_count, remaining = backend_instance.increment(
                    ctx.key, ctx.period, ctx.limit
                )
            ctx.current_count = current_count
            ctx.remaining = remaining
        else:
            # Basic incr — try passing cost kwarg first (v3 backend contract)
            try:
                current_count = backend_instance.incr(ctx.key, ctx.period, cost)
            except TypeError:
                current_count = backend_instance.incr(ctx.key, ctx.period)
                for _ in range(cost - 1):
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
    response_callback: Optional[Callable] = None,
    shadow: bool = False,
    cost: int = 1,
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
        ctx = check_rate_limit(ctx, backend_instance, cost=cost)
    except BackendError as e:
        handler = get_exception_handler()
        return handler(_request, e)

    # Apply shadow mode and observability in one place.
    decision = handle_shadow_decision(
        allowed=ctx.allowed,
        shadow=shadow,
        request=_request,
        key=limit_key,
        limit=limit,
        remaining=ctx.remaining,
        algorithm=getattr(backend_instance, "_algorithm", "sliding_window"),
        backend=type(backend_instance).__name__,
        cost=cost,
    )
    ctx.allowed = decision.allow
    if decision.shadowed:
        ctx.metadata["shadow"] = True

    # Attach context to request
    if _request:
        _request.ratelimit = ctx

    if not ctx.allowed:
        if block:
            response = _create_rate_limit_response(
                request=_request,
                response_callback=response_callback,
            )
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
