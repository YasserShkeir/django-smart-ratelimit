"""
Utility functions for django-smart-ratelimit.

This module provides common utility functions for key generation,
rate parsing, header formatting, and other helper functionality.
"""

import re
import time
from typing import Any, Callable, Dict, Optional, Tuple, Union

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse


def get_ip_key(request: HttpRequest) -> str:
    """
    Extract IP address from request for use as rate limiting key.

    Args:
        request: Django HTTP request object

    Returns:
        IP address string formatted as 'ip:{address}'
    """
    # Try various headers to get real IP (considering proxies)
    ip_headers = [
        "HTTP_CF_CONNECTING_IP",  # Cloudflare
        "HTTP_X_FORWARDED_FOR",  # Standard proxy header
        "HTTP_X_REAL_IP",  # Nginx proxy
        "REMOTE_ADDR",  # Direct connection
    ]

    for header in ip_headers:
        ip = request.META.get(header)
        if ip:
            # Handle comma-separated IPs (X-Forwarded-For)
            if "," in ip:
                ip = ip.split(",")[0].strip()
            if ip and ip != "unknown":
                return f"ip:{ip}"

    return "ip:unknown"


def get_user_key(request: HttpRequest) -> str:
    """
    Extract user ID from request for use as rate limiting key.

    Args:
        request: Django HTTP request object

    Returns:
        User ID string formatted as 'user:{id}' or falls back to IP
    """
    if hasattr(request, "user") and request.user.is_authenticated:
        user_id = getattr(request.user, "id", None)
        return f"user:{user_id}" if user_id else get_ip_key(request)
    else:
        # Fall back to IP for anonymous users
        return get_ip_key(request)


def parse_rate(rate: str) -> Tuple[int, int]:
    """
    Parse rate limit string into (limit, period_seconds).

    Args:
        rate: Rate string like "10/m", "100/h", etc.

    Returns:
        Tuple of (limit, period_in_seconds)

    Raises:
        ImproperlyConfigured: If rate format is invalid
    """
    try:
        limit_str, period_str = rate.split("/")
        limit = int(limit_str)

        period_map = {
            "s": 1,  # second
            "m": 60,  # minute
            "h": 3600,  # hour
            "d": 86400,  # day
        }

        if period_str not in period_map:
            raise ValueError(f"Unknown period: {period_str}")

        period = period_map[period_str]
        return limit, period

    except (ValueError, IndexError) as e:
        raise ImproperlyConfigured(
            f"Invalid rate format: {rate}. Use format like '10/m'"
        ) from e


def validate_rate_config(
    rate: str, algorithm: Optional[str] = None, algorithm_config: Optional[dict] = None
) -> None:
    """
    Validate rate limiting configuration.

    Args:
        rate: Rate string to validate
        algorithm: Algorithm name to validate
        algorithm_config: Algorithm configuration to validate

    Raises:
        ImproperlyConfigured: If configuration is invalid
    """
    # Validate rate format
    parse_rate(rate)

    # Validate algorithm
    valid_algorithms = ["fixed_window", "sliding_window", "token_bucket"]
    if algorithm and algorithm not in valid_algorithms:
        raise ImproperlyConfigured(
            f"Invalid algorithm: {algorithm}. Must be one of {valid_algorithms}"
        )

    # Validate token bucket configuration
    if algorithm == "token_bucket" and algorithm_config:
        if "bucket_size" in algorithm_config:
            if (
                not isinstance(algorithm_config["bucket_size"], (int, float))
                or algorithm_config["bucket_size"] < 0
            ):
                raise ImproperlyConfigured("bucket_size must be a non-negative number")

        if "refill_rate" in algorithm_config:
            if (
                not isinstance(algorithm_config["refill_rate"], (int, float))
                or algorithm_config["refill_rate"] < 0
            ):
                raise ImproperlyConfigured("refill_rate must be a non-negative number")


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


def get_client_identifier(request: HttpRequest, identifier_type: str = "auto") -> str:
    """
    Get client identifier based on specified type.

    Args:
        request: Django HTTP request object
        identifier_type: Type of identifier ('ip', 'user', 'session', 'auto')

    Returns:
        Client identifier string
    """
    if identifier_type == "ip":
        return get_ip_key(request)
    elif identifier_type == "user":
        return get_user_key(request)
    elif identifier_type == "session":
        session_key = request.session.session_key
        if session_key:
            return f"session:{session_key}"
        else:
            return get_ip_key(request)  # Fallback to IP
    elif identifier_type == "auto":
        # Auto-select based on authentication status
        return get_user_key(request)
    else:
        raise ImproperlyConfigured(f"Invalid identifier_type: {identifier_type}")


def is_exempt_request(
    request: HttpRequest,
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
        client_ip = get_ip_key(request).replace("ip:", "")
        if client_ip in exempt_ips:
            return True

    return False


def generate_key(
    key: Union[str, Callable], request: HttpRequest, *args: Any, **kwargs: Any
) -> str:
    """
    Generate rate limit key from template or callable.

    Args:
        key: Key template string or callable function
        request: Django HTTP request object
        *args: Additional arguments passed from decorator
        **kwargs: Additional keyword arguments passed from decorator

    Returns:
        Generated rate limit key string

    Raises:
        ImproperlyConfigured: If key type is invalid
    """
    if callable(key):
        return key(request, *args, **kwargs)

    if isinstance(key, str):
        # Handle common key patterns
        if key == "ip":
            return get_ip_key(request)
        elif key == "user":
            return get_user_key(request)
        elif key.startswith("user:") and hasattr(request, "user"):
            # Handle user-based templates like "user:{user.id}"
            if request.user.is_authenticated:
                user_id = getattr(request.user, "id", None)
                return f"user:{user_id}" if user_id else get_ip_key(request)
            else:
                return get_ip_key(request)  # Fallback to IP
        elif key.startswith("ip:"):
            # Handle IP-based templates
            return get_ip_key(request)
        else:
            # Return key as-is for other patterns
            return key

    raise ImproperlyConfigured(f"Invalid key type: {type(key)}")


def add_rate_limit_headers(
    response: HttpResponse,
    limit: int,
    remaining: int,
    reset_time: Optional[int] = None,
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
                except (TypeError, ValueError):
                    # Fallback if reset_time is not a valid integer
                    pass
        elif period is not None:
            response.headers["X-RateLimit-Reset"] = str(int(time.time() + period))
            # Add Retry-After header only for 429 responses when rate limited
            if remaining <= 0 and getattr(response, "status_code", 200) == 429:
                response.headers["Retry-After"] = str(period)


def add_token_bucket_headers(
    response: HttpResponse, metadata: Dict[str, Any], limit: int, period: int
) -> None:
    """
    Add token bucket specific headers to HTTP response.

    Args:
        response: HTTP response object
        metadata: Token bucket metadata from algorithm
        limit: Rate limit value
        period: Rate limit period in seconds
    """
    if not hasattr(response, "headers"):
        return

    # Standard headers
    response.headers["X-RateLimit-Limit"] = str(limit)
    tokens_remaining = int(metadata.get("tokens_remaining", 0))
    response.headers["X-RateLimit-Remaining"] = str(tokens_remaining)

    # Calculate reset time based on time_to_refill
    time_to_refill = metadata.get("time_to_refill", 0)
    reset_time = (
        int(time.time() + time_to_refill)
        if time_to_refill > 0
        else int(time.time() + period)
    )
    response.headers["X-RateLimit-Reset"] = str(reset_time)

    # Add Retry-After header only for 429 responses when no tokens remaining
    if tokens_remaining <= 0 and getattr(response, "status_code", 200) == 429:
        retry_after = max(0, reset_time - int(time.time()))
        response.headers["Retry-After"] = str(retry_after)

    # Token bucket specific headers
    bucket_size = metadata.get("bucket_size", limit)
    response.headers["X-RateLimit-Bucket-Size"] = str(bucket_size)
    response.headers["X-RateLimit-Bucket-Remaining"] = str(tokens_remaining)

    # Optional: Add refill rate information
    refill_rate = metadata.get("refill_rate", 0)
    if refill_rate > 0:
        response.headers["X-RateLimit-Refill-Rate"] = f"{refill_rate:.2f}"


def get_jwt_key(request: HttpRequest, jwt_field: str = "sub") -> str:
    """
    Extract JWT-based key from request headers.

    Args:
        request: Django HTTP request object
        jwt_field: JWT field to use as key (default: 'sub')

    Returns:
        JWT-based key string or falls back to IP
    """
    try:
        import jwt

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove 'Bearer ' prefix
            decoded = jwt.decode(token, options={"verify_signature": False})

            if jwt_field in decoded:
                return f"jwt:{jwt_field}:{decoded[jwt_field]}"

    except (ImportError, jwt.InvalidTokenError):
        pass

    # Fallback to IP if JWT extraction fails
    return get_ip_key(request)


def get_api_key_key(request: HttpRequest, header_name: str = "X-API-Key") -> str:
    """
    Extract API key from request headers.

    Args:
        request: Django HTTP request object
        header_name: Header name containing API key

    Returns:
        API key-based rate limit key or falls back to IP
    """
    api_key = request.META.get(f'HTTP_{header_name.upper().replace("-", "_")}')
    if api_key:
        return f"api_key:{api_key}"

    # Fallback to IP if no API key
    return get_ip_key(request)


def get_tenant_key(request: HttpRequest, tenant_field: str = "tenant_id") -> str:
    """
    Extract tenant-based key for multi-tenant applications.

    Args:
        request: Django HTTP request object
        tenant_field: Field name to extract tenant ID from

    Returns:
        Tenant-based rate limit key
    """
    # Try to get tenant from various sources
    tenant_id = None

    # From URL parameters
    tenant_id = request.GET.get(tenant_field)

    # From request headers
    if not tenant_id:
        header_name = f'HTTP_{tenant_field.upper().replace("-", "_")}'
        tenant_id = request.META.get(header_name)

    # From user attributes (if authenticated)
    if not tenant_id and hasattr(request, "user") and request.user.is_authenticated:
        tenant_id = getattr(request.user, tenant_field, None)

    if tenant_id:
        return f"tenant:{tenant_id}"

    # Fallback to user or IP
    return get_user_key(request)


def get_device_fingerprint_key(request: HttpRequest) -> str:
    """
    Generate device fingerprint based on request headers.

    Args:
        request: Django HTTP request object

    Returns:
        Device fingerprint-based rate limit key
    """
    import hashlib

    # Collect identifying headers
    fingerprint_data = [
        request.META.get("HTTP_USER_AGENT", ""),
        request.META.get("HTTP_ACCEPT_LANGUAGE", ""),
        request.META.get("HTTP_ACCEPT_ENCODING", ""),
        request.META.get("HTTP_DNT", ""),  # Do Not Track
    ]

    # Create hash of combined data
    combined = "|".join(fingerprint_data)
    fingerprint = hashlib.md5(combined.encode(), usedforsecurity=False).hexdigest()[:16]

    return f"device:{fingerprint}"


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
    static_url = getattr(settings, "STATIC_URL", "/static/")
    if static_url and path.startswith(static_url):
        return True

    # Check against configured media URL
    media_url = getattr(settings, "MEDIA_URL", "/media/")
    if media_url and path.startswith(media_url):
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
