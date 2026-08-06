"""
Utility functions for django-smart-ratelimit.

This module provides common utility functions for key generation,
rate parsing, header formatting, and other helper functionality.

Note: This module is now a facade that imports from specialized modules.
"""

import logging
import math
import re
import time
from typing import Any, Callable, Dict, Optional, Union

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse

# Import from specialized modules
from .backends.utils import normalize_key, parse_rate, validate_rate_config
from .key_functions import (
    generate_key,
    get_api_key_key,
    get_client_identifier,
    get_device_fingerprint_key,
    get_ip_key,
    get_jwt_key,
    get_tenant_key,
    get_user_key,
)
from .messages import ERROR_RATE_LIMIT_EXCEEDED

logger = logging.getLogger(__name__)

__all__ = [
    "format_rate_headers",
    "is_exempt_request",
    "get_ip_key",
    "generate_key",
    "get_api_key_key",
    "get_client_identifier",
    "get_device_fingerprint_key",
    "get_jwt_key",
    "get_tenant_key",
    "get_user_key",
    "parse_rate",
    "validate_rate_config",
    "normalize_key",
    "HttpResponseTooManyRequests",
    "is_ratelimited",
]

# Compatibility for Django < 4.2
try:
    from django.http import HttpResponseTooManyRequests  # type: ignore
except ImportError:

    class HttpResponseTooManyRequests(HttpResponse):  # type: ignore
        """HTTP 429 Too Many Requests response class."""

        status_code = 429


def format_rate_headers(metadata: dict, limit: int, period: int) -> dict:
    """
    Format rate limiting metadata into HTTP headers.

    Args:
        metadata: Rate limiting metadata from backend
        limit: Rate limit value
        period: Rate limit period

    Returns:
        Dictionary of HTTP headers
    """
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, metadata.get("remaining", 0))),
    }

    # Add reset time if available
    if "reset_time" in metadata:
        headers["X-RateLimit-Reset"] = str(int(metadata["reset_time"]))

    # Add token bucket specific headers
    if "bucket_size" in metadata:
        headers["X-RateLimit-Bucket-Size"] = str(metadata["bucket_size"])
        headers["X-RateLimit-Bucket-Remaining"] = str(
            int(metadata.get("tokens_remaining", 0))
        )

    if "refill_rate" in metadata:
        headers["X-RateLimit-Refill-Rate"] = f"{metadata['refill_rate']:.2f}"

    return headers


def is_exempt_request(
    request: Any,
    exempt_paths: Optional[list] = None,
    exempt_ips: Optional[list] = None,
) -> bool:
    """
    Check if request should be exempt from rate limiting.

    Args:
        request: Django HTTP request object
        exempt_paths: List of path patterns to exempt
        exempt_ips: List of IP addresses/ranges to exempt

    Returns:
        True if request should be exempt
    """
    if exempt_paths:
        for pattern in exempt_paths:
            if re.match(pattern, request.path):
                return True

    if exempt_ips:
        from .auth_utils import _ip_in_network

        client_ip = get_ip_key(request).replace("ip:", "")
        for exempt_ip in exempt_ips:
            if "/" in exempt_ip:
                if _ip_in_network(client_ip, exempt_ip):
                    return True
            elif client_ip == exempt_ip:
                return True

    return False


def add_rate_limit_headers(
    response: HttpResponse,
    limit: int,
    remaining: int,
    reset_time: Optional[Union[int, float]] = None,
    period: Optional[int] = None,
) -> None:
    """
    Add standard rate limiting headers to HTTP response.

    Args:
        response: HTTP response object
        limit: Rate limit value
        remaining: Remaining requests
        reset_time: Reset timestamp (optional)
        period: Period in seconds (used if reset_time not provided)
    """
    if hasattr(response, "headers"):
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))

        if reset_time is not None:
            response.headers["X-RateLimit-Reset"] = str(reset_time)
            # Add Retry-After header only for 429 responses when rate limited
            if remaining <= 0 and getattr(response, "status_code", 200) == 429:
                # Handle case where reset_time might be a Mock object in tests
                try:
                    retry_after = max(0, int(reset_time) - int(time.time()))
                    response.headers["Retry-After"] = str(retry_after)
                except (TypeError, ValueError) as e:
                    # Fallback if reset_time is not a valid integer
                    logger.warning(f"Failed to calculate Retry-After header: {e}")
        elif period is not None:
            response.headers["X-RateLimit-Reset"] = str(int(time.time() + period))
            # Add Retry-After header only for 429 responses when rate limited
            if remaining <= 0 and getattr(response, "status_code", 200) == 429:
                response.headers["Retry-After"] = str(period)


def _coerce_finite_float(value: Any, default: float) -> float:
    """
    Best-effort conversion of backend metadata to a finite float.

    Backends are free to omit any optional metadata field, to report it as
    ``None``, or (for the "never refills" case) as ``inf``. ``dict.get`` only
    applies its default when the key is *absent*, so a key present with a
    ``None`` value would otherwise reach ``int()``/``float()`` and raise. This
    helper never raises: anything that is not a finite number becomes
    ``default``.

    Args:
        value: Raw metadata value.
        default: Value to use when ``value`` is missing or unusable.

    Returns:
        A finite float.
    """
    if value is None or isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _format_header_number(value: float) -> str:
    """
    Render a numeric header value without truncating a fractional part.

    ``10.5`` must stay ``"10.5"`` (``format_token_bucket_metadata`` types
    ``bucket_size`` as ``Optional[float]`` and the Redis fail-open path really
    does pass a float), while a whole number stays ``"10"`` rather than
    becoming ``"10.0"``.

    Args:
        value: Numeric header value.

    Returns:
        String representation for the header.
    """
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def add_token_bucket_headers(
    response: HttpResponse, metadata: Dict[str, Any], limit: int, period: int
) -> None:
    """
    Add token bucket specific headers to HTTP response.

    ``X-RateLimit-Reset`` is period-aligned and therefore stable across
    successive requests (issue #14); ``Retry-After`` tracks the bucket's real
    refill wait so a caller told to wait actually waits the right amount of
    time.

    Args:
        response: HTTP response object
        metadata: Token bucket metadata from algorithm
        limit: Rate limit value
        period: Rate limit period in seconds
    """
    if not hasattr(response, "headers"):
        return

    current_time = time.time()

    # Every value below is coerced defensively. A single malformed optional
    # field must degrade only itself -- it must never raise (the sync decorator
    # would then re-run the view body through its fallback path, and the async
    # decorator would surface a TypeError to the caller) and it must never cost
    # us the headers we *can* compute.
    period_seconds = _coerce_finite_float(period, 0.0)
    if period_seconds < 0:
        period_seconds = 0.0

    tokens_remaining = int(_coerce_finite_float(metadata.get("tokens_remaining"), 0.0))
    bucket_size = _coerce_finite_float(
        metadata.get("bucket_size"), _coerce_finite_float(limit, 0.0)
    )
    refill_rate = _coerce_finite_float(metadata.get("refill_rate"), 0.0)

    # Standard headers
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(tokens_remaining)

    # X-RateLimit-Reset stays anchored to the fixed period grid rather than to
    # the bucket's refill state. Clients need a reset time that does not move
    # on every request (issue #14), so it is deliberately *not* derived from
    # time_to_refill.
    if period_seconds > 0:
        bucket_start = int(current_time // period_seconds) * period_seconds
        reset_time = bucket_start + period_seconds
        # If very close to current time, advance to next period.
        if reset_time - current_time < 5:
            reset_time += period_seconds
    else:
        reset_time = current_time
    response.headers["X-RateLimit-Reset"] = str(int(reset_time))

    # Retry-After answers a different question than X-RateLimit-Reset: "how
    # long until this request would be served?". For a token bucket that is
    # the backend-computed refill wait, and it applies to every rejection --
    # including the multi-token-cost case where tokens remain (3 left) but not
    # enough for the request (costs 5).
    if getattr(response, "status_code", 200) == 429:
        # A refill_rate of 0 means the bucket never refills. Producers spell
        # that either `inf` (backends/utils) or `0` (algorithms/token_bucket,
        # redis lua), and neither is a usable wait -- fall back to `period` on
        # both rather than emitting a nonsensical `Retry-After: 1`.
        fallback = period_seconds if period_seconds > 0 else 1.0
        time_to_refill = _coerce_finite_float(metadata.get("time_to_refill"), fallback)
        if time_to_refill <= 0:
            time_to_refill = fallback
        # Round up: waiting a fraction of a second short would just 429 again.
        response.headers["Retry-After"] = str(max(1, int(math.ceil(time_to_refill))))

    # Token bucket specific headers
    response.headers["X-RateLimit-Bucket-Size"] = _format_header_number(bucket_size)
    response.headers["X-RateLimit-Bucket-Remaining"] = str(tokens_remaining)

    # Optional: Add refill rate information
    if refill_rate > 0:
        response.headers["X-RateLimit-Refill-Rate"] = f"{refill_rate:.2f}"


def load_function_from_string(function_path: str) -> Callable:
    """
    Load a function from a string path.

    Args:
        function_path: String path to function (e.g., 'mymodule.myfunction')

    Returns:
        Loaded function

    Raises:
        ImproperlyConfigured: If function cannot be loaded
    """
    try:
        module_path, function_name = function_path.rsplit(".", 1)
        module = __import__(module_path, fromlist=[function_name])
        return getattr(module, function_name)
    except (ImportError, AttributeError, ValueError) as e:
        raise ImproperlyConfigured(f"Cannot load function {function_path}: {e}") from e


def should_skip_static_media(request: HttpRequest) -> bool:
    """
    Check if request is for static or media files and should be skipped.

    This function uses the actual configured STATIC_URL and MEDIA_URL settings
    instead of hardcoded paths to prevent bypassing rate limits.

    Security Note: Always use this function instead of hardcoding '/static/'
    and '/media/' to prevent rate limit bypass when these settings are customized.

    Args:
        request: Django HTTP request object

    Returns:
        True if request should be skipped (is for static/media files)
    """
    from django.conf import settings

    path = request.path

    # Check against configured static URL
    # Note: STATIC_URL may be None in Django 4.0+ if not configured
    static_url = getattr(settings, "STATIC_URL", None)
    # Only skip if static_url is a meaningful path (not empty, not just "/")
    if static_url and static_url != "/" and path.startswith(static_url):
        return True

    # Check against configured media URL
    # Note: MEDIA_URL defaults to "" but may become "/" due to SCRIPT_NAME prefix
    media_url = getattr(settings, "MEDIA_URL", None)
    # Only skip if media_url is a meaningful path (not empty, not just "/")
    if media_url and media_url != "/" and path.startswith(media_url):
        return True

    return False


def should_skip_common_browser_requests(request: HttpRequest) -> bool:
    """
    Check if request is a common browser secondary request that should be skipped.

    This includes favicon, robots.txt, preflight requests, and static/media files.
    Uses configured static/media URLs for security.

    Args:
        request: Django HTTP request object

    Returns:
        True if request should be skipped
    """
    path = request.path
    method = request.method

    # Common browser files
    browser_files = [
        "/favicon.ico",
        "/robots.txt",
        "/apple-touch-icon.png",
        "/apple-touch-icon-precomposed.png",
        "/manifest.json",
        "/browserconfig.xml",
        "/sitemap.xml",
    ]

    if path in browser_files:
        return True

    # HTTP methods that shouldn't count toward rate limits
    if method in ["OPTIONS", "HEAD"]:
        return True

    # Static and media files (using configured URLs)
    if should_skip_static_media(request):
        return True

    return False


def should_skip_path(path: str, skip_patterns: list) -> bool:
    """
    Check if a path should be skipped based on patterns.

    Args:
        path: Request path to check
        skip_patterns: List of path patterns to skip

    Returns:
        True if path should be skipped
    """
    for pattern in skip_patterns:
        if path.startswith(pattern):
            return True
    return False


def get_rate_for_path(path: str, rate_limits: Dict[str, str], default_rate: str) -> str:
    """
    Get rate limit for a specific path based on configured patterns.

    Args:
        path: Request path
        rate_limits: Dictionary mapping path patterns to rates
        default_rate: Default rate to use if no pattern matches

    Returns:
        Rate string for the path
    """
    for path_pattern, rate in rate_limits.items():
        if path.startswith(path_pattern):
            return rate
    return default_rate


def debug_ratelimit_status(request: HttpRequest) -> Dict[str, Any]:
    """
    Get debug information about rate limiting status for a request.

    This function helps diagnose rate limiting issues by providing
    information about middleware processing, current limits, and
    backend state.

    Args:
        request: Django HTTP request object

    Returns:
        Dictionary containing debug information
    """
    from .backends import get_backend

    debug_info = {
        "middleware_processed": getattr(
            request, "_ratelimit_middleware_processed", False
        ),
        "middleware_limit": getattr(request, "_ratelimit_middleware_limit", None),
        "middleware_remaining": getattr(
            request, "_ratelimit_middleware_remaining", None
        ),
        "request_path": request.path,
        "request_method": request.method,
        "user_authenticated": (
            request.user.is_authenticated if hasattr(request, "user") else False
        ),
        "user_id": (
            getattr(request.user, "id", None)
            if hasattr(request, "user") and request.user.is_authenticated
            else None
        ),
        "remote_addr": request.META.get("REMOTE_ADDR"),
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[
            :100
        ],  # Truncate for readability
    }

    # Try to get backend count for common key patterns
    try:
        backend = get_backend()

        # Generate common key patterns to check
        keys_to_check = []

        # IP-based keys
        ip_key = get_ip_key(request)
        keys_to_check.append(("ip", ip_key))

        # User-based keys
        if debug_info["user_authenticated"]:
            user_key = f"user:{debug_info['user_id']}"
            keys_to_check.append(("user", user_key))

        # Middleware keys
        if ip_key:
            middleware_ip_key = ip_key.replace("ip:", "middleware:")
            keys_to_check.append(("middleware_ip", middleware_ip_key))

        if debug_info["user_authenticated"]:
            middleware_user_key = f"middleware:user:{debug_info['user_id']}"
            keys_to_check.append(("middleware_user", middleware_user_key))

        # Check counts for each key pattern
        backend_counts = {}
        for key_type, key in keys_to_check:
            try:
                if hasattr(backend, "get_count"):
                    count = backend.get_count(key)
                    backend_counts[key_type] = {"key": key, "count": count}
            except Exception as e:
                backend_counts[key_type] = {"key": key, "error": str(e)}

        debug_info["backend_counts"] = backend_counts
        debug_info["backend_type"] = type(backend).__name__

    except Exception as e:
        debug_info["backend_error"] = str(e)

    return debug_info


def format_debug_info(debug_info: Dict[str, Any]) -> str:
    """
    Format debug information into a readable string.

    Added for GitHub issue #6:
    https://github.com/YasserShkeir/django-smart-ratelimit/issues/6

    Args:
        debug_info: Dictionary from debug_ratelimit_status()

    Returns:
        Formatted debug information string
    """
    lines = []
    lines.append("=== Rate Limiting Debug Information ===")
    lines.append(f"Path: {debug_info['request_path']}")
    lines.append(f"Method: {debug_info['request_method']}")
    lines.append(
        f"User: {'Authenticated' if debug_info['user_authenticated'] else 'Anonymous'}"
    )

    if debug_info["user_authenticated"]:
        lines.append(f"User ID: {debug_info['user_id']}")

    lines.append(f"Remote IP: {debug_info['remote_addr']}")
    lines.append("")

    lines.append("Middleware Status:")
    lines.append(f"  Processed: {debug_info['middleware_processed']}")
    if debug_info["middleware_processed"]:
        lines.append(f"  Limit: {debug_info['middleware_limit']}")
        lines.append(f"  Remaining: {debug_info['middleware_remaining']}")
    lines.append("")

    if "backend_counts" in debug_info:
        lines.append(f"Backend: {debug_info.get('backend_type', 'Unknown')}")
        lines.append("Current Counts:")
        for key_type, info in debug_info["backend_counts"].items():
            if "error" in info:
                lines.append(f"  {key_type}: Error - {info['error']}")
            else:
                lines.append(f"  {key_type}: {info['count']} (key: {info['key']})")

    if "backend_error" in debug_info:
        lines.append(f"Backend Error: {debug_info['backend_error']}")

    lines.append("=" * 40)

    return "\n".join(lines)


def get_rate_limit_error_message(include_details: bool = False) -> str:
    """
    Get rate limit error message for HTTP responses.

    Args:
        include_details: If True, include more details (for debugging only)

    Returns:
        Error message string safe for client responses
    """
    from django.conf import settings

    base_message = ERROR_RATE_LIMIT_EXCEEDED
    if include_details and settings.DEBUG:
        return base_message + " Check X-RateLimit-* headers for details."
    return base_message


def is_ratelimited(
    request: Any,
    group: Optional[str] = None,
    key: Union[str, Callable] = "ip",
    rate: str = "5/m",
    increment: bool = True,
    backend: Optional[str] = None,
) -> bool:
    """
    Check if a request is rate limited programmatically.

    Args:
        request: Django HTTP request
        group: Optional group name for the limit
        key: Key function or string ('ip', 'user')
        rate: Rate limit string ('5/m')
        increment: Whether to increment the counter
        backend: Backend alias to use (optional)

    Returns:
        True if the request is rate limited (exceeds limit), False otherwise.
    """
    from .backends import get_backend

    # 1. Generate the key
    # If group is provided, it's usually part of specific business logic,
    # but generate_key handles basic keyparts. We prepend group if exists.
    generated_key = generate_key(key, request)
    if group:
        generated_key = f"{group}:{generated_key}"

    # 2. Get the backend
    limiter = get_backend(backend)

    # 3. Parse the rate
    limit, period = parse_rate(rate)

    # 4. Check status
    if increment:
        count = limiter.incr(generated_key, period)
    else:
        count = limiter.get_count(generated_key, period)

    return count > limit
