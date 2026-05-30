"""
Backend utility functions for Django Smart Ratelimit.

This module provides common functionality used across different backend implementations,
including connection handling, data serialization, key management, and monitoring.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union

from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


# ============================================================================
# Connection and Health Management
# ============================================================================


def with_retry(
    max_retries: int = 3,
    delay: float = 0.1,
    max_delay: float = 2.0,
    exponential_backoff: bool = True,
    exponential_base: float = 2.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    on_retry: Optional[Callable[[BaseException, int], None]] = None,
) -> Callable:
    """
    Retry backend operations with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries
        exponential_backoff: Whether to use exponential backoff
        exponential_base: Base for exponential backoff calculation
        exceptions: Tuple of exception types to catch and retry
        on_retry: Optional callback called on each retry (exception, attempt)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[BaseException] = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        if on_retry:
                            on_retry(e, attempt + 1)
                        else:
                            logger.warning(
                                f"Backend operation failed (attempt {attempt + 1}/"
                                f"{max_retries + 1}): {e}"
                            )

                        time.sleep(current_delay)

                        if exponential_backoff:
                            current_delay = min(
                                current_delay * exponential_base, max_delay
                            )
                    else:
                        logger.error(
                            f"Backend operation failed after {max_retries + 1} "
                            f"attempts: {e}"
                        )

            if last_exception is not None:
                raise last_exception
            else:
                raise RuntimeError("Unexpected error: no exception was caught")

        return wrapper

    return decorator


def test_backend_connection(backend_instance: Any) -> Tuple[bool, Optional[str]]:
    """
    Test if a backend connection is healthy.

    Args:
        backend_instance: Backend instance to test

    Returns:
        Tuple of (is_healthy, error_message)
    """
    try:
        # Try a simple operation
        test_key = f"__health_check_{int(time.time())}"
        if hasattr(backend_instance, "set") and hasattr(backend_instance, "get"):
            backend_instance.set(test_key, "test", 1)
            result = backend_instance.get(test_key)
            if hasattr(backend_instance, "delete"):
                backend_instance.delete(test_key)

            if result == "test":
                return True, None
            else:
                return False, "Health check data mismatch"
        else:
            # For rate limiting backends, test incr operation
            result = backend_instance.incr(test_key, 60)
            if hasattr(backend_instance, "reset"):
                backend_instance.reset(test_key)
            return True, None

    except Exception as e:
        return False, str(e)


def get_backend_metrics(backend_instance: Any) -> Dict[str, Any]:
    """
    Get performance and health metrics from a backend.

    Args:
        backend_instance: Backend instance to analyze

    Returns:
        Dictionary with metrics
    """
    metrics = {
        "backend_type": backend_instance.__class__.__name__,
        "timestamp": time.time(),
        "is_healthy": False,
        "response_time_ms": None,
        "error": None,
    }

    start_time = time.time()
    is_healthy, error = test_backend_connection(backend_instance)
    end_time = time.time()

    metrics.update(
        {
            "is_healthy": is_healthy,
            "response_time_ms": (end_time - start_time) * 1000,
            "error": error,
        }
    )

    # Add backend-specific metrics
    if hasattr(backend_instance, "get_stats"):
        try:
            backend_stats = backend_instance.get_stats()
            metrics["backend_stats"] = backend_stats
        except Exception as e:
            metrics["stats_error"] = str(e)

    return metrics


# ============================================================================
# Data Serialization and Key Management
# ============================================================================


def serialize_data(data: Any) -> str:
    """
    Serialize data for storage in backends.

    Args:
        data: Data to serialize

    Returns:
        Serialized string
    """
    if isinstance(data, (str, int, float)):
        return str(data)
    elif isinstance(data, (dict, list, tuple)):
        return json.dumps(data, default=str)
    else:
        return str(data)


def deserialize_data(data: str, expected_type: Optional[type] = None) -> Any:
    """
    Deserialize data from backend storage.

    Args:
        data: Serialized data string
        expected_type: Expected type for validation

    Returns:
        Deserialized data
    """
    if not data:
        return None

    try:
        # Try JSON deserialization first
        result = json.loads(data)
        if expected_type and not isinstance(result, expected_type):
            # Type mismatch, try direct conversion
            if expected_type in (int, float):
                return expected_type(data)
            elif expected_type == str:
                return str(data)
        return result
    except (json.JSONDecodeError, ValueError):
        # Fallback to string or type conversion
        if expected_type:
            try:
                return expected_type(data)
            except (ValueError, TypeError):
                pass
        return data


def normalize_key(key: str, prefix: str = "", max_length: int = 250) -> str:
    """
    Normalize and validate keys for backend storage.

    Args:
        key: Original key
        prefix: Key prefix to add
        max_length: Maximum key length

    Returns:
        Normalized key
    """
    # Add prefix
    if prefix:
        # Remove trailing colon from prefix if present to avoid double colons
        prefix = prefix.rstrip(":")
        full_key = f"{prefix}:{key}"
    else:
        full_key = key

    # Handle long keys by hashing
    if len(full_key) > max_length:
        # Keep readable prefix and hash the rest
        hash_suffix = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
        # Truncate prefix to fit hash
        prefix_len = max_length - len(hash_suffix) - 1
        full_key = f"{full_key[:prefix_len]}:{hash_suffix}"

    # Ensure key is safe for backends (no spaces, control chars)
    # This is a basic sanitization, backends might have stricter rules
    return full_key.replace(" ", "_")


def parse_rate(rate: str) -> Tuple[int, int]:
    """
    Parse rate limit string into (limit, period_seconds).

    Supports both simple and custom time-window formats:

    * Simple:  ``"10/s"``, ``"10/m"``, ``"100/h"``, ``"1000/d"``
    * Custom:  ``"10/30s"`` (10 requests per 30 seconds),
               ``"100/5m"`` (100 requests per 5 minutes),
               ``"500/2h"`` (500 requests per 2 hours),
               ``"10000/7d"`` (10 000 requests per 7 days)

    Args:
        rate: Rate string in one of the formats described above.

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
            # v3: long-form aliases for DRF/API-Gateway compatibility
            "sec": 1,
            "second": 1,
            "min": 60,
            "minute": 60,
            "hr": 3600,
            "hour": 3600,
            "day": 86400,
        }

        # Simple format: "10/m", "10/minute"
        if period_str in period_map:
            period = period_map[period_str]
            return limit, period

        # Custom format: "10/30s", "100/5m", etc.
        import re

        match = re.match(r"^(\d+)([smhd])$", period_str)
        if match:
            multiplier = int(match.group(1))
            if multiplier <= 0:
                raise ValueError(
                    f"Period multiplier must be positive, got: {multiplier}"
                )
            unit = match.group(2)
            period = multiplier * period_map[unit]
            return limit, period

        raise ValueError(f"Unknown period: {period_str}")

    except (ValueError, IndexError) as e:
        raise ImproperlyConfigured(
            f"Invalid rate format: {rate}. "
            f"Use format like '10/m' or '10/30s' (custom windows)"
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
    valid_algorithms = [
        "fixed_window",
        "sliding_window",
        "token_bucket",
        "leaky_bucket",
    ]
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


def get_current_timestamp() -> float:
    """Get current Unix timestamp with consistent precision."""
    return time.time()


def get_current_datetime() -> datetime:
    """
    Get current UTC datetime.

    Centralized to allow easier mocking and consistency.
    """
    return datetime.now(dt_timezone.utc)


def calculate_expiry(period: int, current_time: Optional[float] = None) -> float:
    """
    Calculate expiry timestamp for a rate limit window.

    Args:
        period: Window period in seconds
        current_time: Current timestamp (defaults to now)

    Returns:
        Expiry timestamp
    """
    if current_time is None:
        current_time = get_current_timestamp()
    return current_time + period


def get_sliding_window_start(
    period: int, current_time: Optional[float] = None
) -> float:
    """
    Calculate the start of the sliding window (looking back 'period' seconds).

    Args:
        period: Window period in seconds
        current_time: Current timestamp (defaults to now)

    Returns:
        Window start timestamp
    """
    if current_time is None:
        current_time = get_current_timestamp()
    return current_time - period


def generate_expiry_timestamp(ttl_seconds: int) -> int:
    """
    Generate expiry timestamp from TTL.

    Args:
        ttl_seconds: Time to live in seconds

    Returns:
        Unix timestamp when the key should expire
    """
    return int(time.time()) + ttl_seconds


def is_expired(timestamp: Union[int, float]) -> bool:
    """
    Check if a timestamp has expired.

    Args:
        timestamp: Unix timestamp to check

    Returns:
        True if expired, False otherwise
    """
    return time.time() > timestamp


# ============================================================================
# Rate Limiting Algorithm Helpers
# ============================================================================


# ============================================================================
# Algorithm Utilities
# ============================================================================


def get_window_times(
    window_seconds: int, align_to_clock: Optional[bool] = None
) -> Tuple[datetime, datetime]:
    """
    Get the start and end times for a fixed window.

    This utility function calculates the current fixed window boundaries
    based on the window size. Used by backends that implement fixed window
    rate limiting algorithms.

    Args:
        window_seconds: The window size in seconds
        align_to_clock: If True, align window to clock boundaries (e.g., :00, :01).
                        If False, window starts at current time.
                        If None, uses RATELIMIT_ALIGN_WINDOW_TO_CLOCK setting.

    Returns:
        Tuple of (window_start, window_end) as datetime objects

    Example (align_to_clock=True):
        If window is 3600 seconds (1 hour) and now is 14:30:00,
        the window start will be 14:00:00 and end will be 15:00:00

    Example (align_to_clock=False):
        If window is 3600 seconds (1 hour) and now is 14:30:00,
        the window start will be 14:30:00 and end will be 15:30:00
    """
    # Import here to avoid Django dependency issues during import
    try:
        from django.utils import timezone

        now = timezone.now()
    except ImportError:
        # Fallback for non-Django environments
        now = datetime.now(dt_timezone.utc)

    # Determine alignment mode from settings if not explicitly provided
    if align_to_clock is None:
        try:
            from django_smart_ratelimit.config import get_settings

            align_to_clock = get_settings().align_window_to_clock
        except Exception:
            align_to_clock = True  # Default to clock-aligned for backward compat

    if align_to_clock:
        # Calculate the start of the current clock-aligned window
        seconds_since_epoch = int(now.timestamp())
        window_start_seconds = (seconds_since_epoch // window_seconds) * window_seconds
        window_start = datetime.fromtimestamp(window_start_seconds, tz=dt_timezone.utc)
    else:
        # Window starts at current time (first-request aligned)
        window_start = now

    window_end = window_start + timedelta(seconds=window_seconds)

    return window_start, window_end


def get_time_bucket_key_suffix(
    window_seconds: int, align_to_clock: Optional[bool] = None
) -> str:
    """
    Get a time bucket suffix for cache keys.

    When align_to_clock=True, returns a suffix based on the current time bucket
    (e.g., ':1705161600'). This causes keys to automatically rotate at clock boundaries.

    When align_to_clock=False, returns empty string (keys are static, TTL handles expiry).

    Args:
        window_seconds: The window size in seconds
        align_to_clock: If True, return time bucket suffix. If False, return empty string.
                        If None, uses RATELIMIT_ALIGN_WINDOW_TO_CLOCK setting.

    Returns:
        Time bucket suffix string (e.g., ':1705161600') or empty string
    """
    # Determine alignment mode from settings if not explicitly provided
    if align_to_clock is None:
        try:
            from django_smart_ratelimit.config import get_settings

            align_to_clock = get_settings().align_window_to_clock
        except Exception:
            align_to_clock = True  # Default to clock-aligned for backward compat

    if not align_to_clock:
        return ""

    # Calculate the current time bucket
    current_time = time.time()
    bucket = int(current_time // window_seconds) * window_seconds
    return f":{bucket}"


def filter_sliding_window_requests(
    requests: List[Tuple[float, str]], window_size: int, current_time: float
) -> List[Tuple[float, str]]:
    """
    Filter requests that are within the sliding window.

    Sliding window algorithm:
    1. Get all request timestamps
    2. Calculate cutoff time (current_time - window_size)
    3. Keep only timestamps > cutoff
    4. Count remaining is current usage

    This provides smoother rate limiting than fixed windows because there's
    no "boundary burst" problem where users can double their rate at the
    window reset edge.

    Uses millisecond precision to avoid floating point issues.

    Args:
        requests: List of (timestamp, unique_id) tuples
        window_size: Window size in seconds
        current_time: Current timestamp

    Returns:
        List of requests within the window
    """
    # Use milliseconds for precision to avoid floating point comparison issues
    current_ms = int(current_time * 1000)
    window_ms = int(window_size * 1000)
    cutoff_ms = current_ms - window_ms

    return [(ts, uid) for ts, uid in requests if int(ts * 1000) > cutoff_ms]


def calculate_sliding_window_count(
    window_data: List[Tuple[float, str]], window_size: int, current_time: float
) -> int:
    """
    Calculate count for sliding window algorithm.

    Args:
        window_data: List of (timestamp, unique_id) tuples
        window_size: Window size in seconds
        current_time: Current timestamp

    Returns:
        Total count in the sliding window
    """
    return len(filter_sliding_window_requests(window_data, window_size, current_time))


def clean_expired_entries(data: Dict[str, Any], current_time: float) -> Dict[str, Any]:
    """
    Remove expired entries from data structures.

    Args:
        data: Data dictionary with timestamp-based entries
        current_time: Current timestamp

    Returns:
        Cleaned data dictionary
    """
    cleaned: Dict[str, Any] = {}

    for key, value in data.items():
        if isinstance(value, dict) and "expires_at" in value:
            if not is_expired(value["expires_at"]):
                cleaned[key] = value
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            # Handle format: (expiry_time, data)
            expiry_time = value[0]
            if not is_expired(expiry_time):
                cleaned[key] = value
        else:
            # Keep non-expirable data
            cleaned[key] = value

    return cleaned


# ============================================================================
# Lua Script Helpers (for Redis-like backends)
# ============================================================================


def create_lua_script_hash(script: str) -> str:
    """
    Create a hash for a Lua script for caching.

    Args:
        script: Lua script content

    Returns:
        SHA1 hash of the script
    """
    return hashlib.sha1(script.encode(), usedforsecurity=False).hexdigest()


def validate_lua_script_args(
    args: List[Any], expected_count: int, script_name: str = "script"
) -> None:
    """
    Validate Lua script arguments.

    Args:
        args: List of arguments
        expected_count: Expected number of arguments
        script_name: Name of the script for error messages

    Raises:
        ValueError: If argument count doesn't match
    """
    if len(args) != expected_count:
        raise ValueError(
            f"{script_name} expects {expected_count} arguments, got {len(args)}"
        )


def format_lua_args(args: List[Any]) -> List[str]:
    """
    Format arguments for Lua script execution.

    Args:
        args: List of arguments to format

    Returns:
        List of string-formatted arguments
    """
    formatted = []
    for arg in args:
        if isinstance(arg, (int, float)):
            formatted.append(str(arg))
        elif isinstance(arg, str):
            formatted.append(arg)
        elif isinstance(arg, (dict, list)):
            formatted.append(json.dumps(arg))
        else:
            formatted.append(str(arg))

    return formatted


# ============================================================================
# Configuration Validation
# ============================================================================


def validate_backend_config(
    config: Dict[str, Any], backend_type: str
) -> Dict[str, Any]:
    """
    Validate backend configuration.

    Args:
        config: Configuration dictionary
        backend_type: Type of backend

    Returns:
        Validated and normalized configuration

    Raises:
        ValueError: If configuration is invalid
    """
    validated_config = config.copy()

    # Common validations
    if "timeout" in validated_config:
        timeout = validated_config["timeout"]
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("Timeout must be a positive number")

    if "max_connections" in validated_config:
        max_conn = validated_config["max_connections"]
        if not isinstance(max_conn, int) or max_conn <= 0:
            raise ValueError("max_connections must be a positive integer")

    # Backend-specific validations
    if backend_type == "redis":
        required_fields = ["host"]
        for field in required_fields:
            if field not in validated_config and field not in ["host"]:
                # host can be defaulted
                continue

        # Set defaults
        validated_config.setdefault("host", "localhost")
        validated_config.setdefault("port", 6379)
        validated_config.setdefault("db", 0)

    elif backend_type == "database":
        # Database backend uses Django's database settings
        validated_config.setdefault("table_name", "django_smart_ratelimit")

    elif backend_type == "memory":
        # Memory backend configuration - don't set defaults here
        # Let the backend handle Django settings
        pass

    return validated_config


# ============================================================================
# Monitoring and Logging
# ============================================================================


def log_backend_operation(
    operation: str,
    message: str,
    duration: Optional[float] = None,
    level: str = "debug",
    **kwargs: Any,
) -> None:
    """
    Log backend operation with structured data.

    Args:
        operation: Operation name
        message: Log message
        duration: Operation duration in seconds
        level: Log level
        **kwargs: Additional data to log
    """
    log_data = {"operation": operation, "message": message, **kwargs}

    if duration is not None:
        log_data["duration_ms"] = round(duration * 1000, 2)

    log_func = getattr(logger, level.lower(), logger.info)
    log_func(f"Backend operation: {log_data}")


def log_operation_result(
    operation: str,
    backend_type: str,
    key: str,
    duration_ms: Optional[float],
    success: bool,
    error: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """
    Log the result of a backend operation with consistent formatting.

    Args:
        operation: Operation name (e.g., 'incr', 'reset', 'get_count')
        backend_type: Backend type (e.g., 'memory', 'redis', 'database')
        key: The key being operated on
        duration_ms: Operation duration in milliseconds
        success: Whether the operation succeeded
        error: Error message if operation failed
        **kwargs: Additional logging data
    """
    level = "info" if success else "error"
    duration_info = f" in {duration_ms:.2f}ms" if duration_ms is not None else ""

    if success:
        message = (
            f"{backend_type} {operation} operation for key '{key}' "
            f"succeeded{duration_info}"
        )
    else:
        message = (
            f"{backend_type} {operation} operation for key '{key}' "
            f"failed{duration_info}"
        )
        if error:
            message += f": {error}"

    log_data = {
        "operation": operation,
        "backend_type": backend_type,
        "key": key,
        "success": success,
        **kwargs,
    }

    if duration_ms is not None:
        log_data["duration_ms"] = duration_ms

    if error:
        log_data["error"] = error

    log_func = getattr(logger, level, logger.info)
    log_func(message, extra=log_data)


class OperationTimer:
    """Context manager for timing operations."""

    def __init__(self) -> None:
        """Initialize instance."""
        self.start_time: Optional[float] = None
        self.elapsed_ms: Optional[float] = None

    def __enter__(self) -> "OperationTimer":
        """Start timer."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop timer."""
        if self.start_time is not None:
            end_time = time.time()
            self.elapsed_ms = (end_time - self.start_time) * 1000


def create_operation_timer() -> OperationTimer:
    """
    Create a context manager for timing operations.

    Returns:
        Context manager that yields elapsed time in milliseconds
    """
    return OperationTimer()


# ============================================================================
# Memory Management Helpers
# ============================================================================


def cleanup_memory_data(
    data: Dict[str, Any], max_size: int, cleanup_strategy: str = "lru"
) -> Dict[str, Any]:
    """
    Clean up memory data based on size limits.

    Args:
        data: Data dictionary to clean
        max_size: Maximum number of entries
        cleanup_strategy: Strategy for cleanup ('lru', 'fifo', 'random')

    Returns:
        Cleaned data dictionary
    """
    if len(data) <= max_size:
        return data

    if cleanup_strategy == "lru":
        # Sort by last access time if available
        sorted_items = sorted(
            data.items(),
            key=lambda x: x[1].get("last_access", 0) if isinstance(x[1], dict) else 0,
        )
    elif cleanup_strategy == "fifo":
        # Sort by creation time if available
        sorted_items = sorted(
            data.items(),
            key=lambda x: x[1].get("created_at", 0) if isinstance(x[1], dict) else 0,
        )
    else:  # random
        import random

        sorted_items = list(data.items())
        random.shuffle(sorted_items)

    # Keep only the newest entries
    entries_to_remove = len(data) - max_size
    items_to_keep = sorted_items[entries_to_remove:]

    return dict(items_to_keep)


# ============================================================================
# Token Bucket Algorithm Helpers
# ============================================================================


def calculate_token_bucket_state(
    current_tokens: float,
    last_refill: float,
    current_time: float,
    bucket_size: float,
    refill_rate: float,
    tokens_requested: int = 0,
) -> Dict[str, Any]:
    """
    Calculate token bucket state after time passage.

    Args:
        current_tokens: Current number of tokens
        last_refill: Last refill timestamp
        current_time: Current timestamp
        bucket_size: Maximum bucket capacity
        refill_rate: Tokens added per second
        tokens_requested: Tokens being requested (for consumption check)

    Returns:
        Dictionary with token bucket state
    """
    time_elapsed = current_time - last_refill
    tokens_to_add = time_elapsed * refill_rate
    updated_tokens = min(bucket_size, current_tokens + tokens_to_add)

    is_allowed = updated_tokens >= tokens_requested if tokens_requested > 0 else True
    tokens_remaining = (
        updated_tokens - tokens_requested if is_allowed else updated_tokens
    )

    if tokens_requested > updated_tokens and tokens_requested > 0:
        # A refill_rate of 0 means the bucket never refills, so the requested
        # tokens will never become available. Avoid dividing by zero and report
        # that refill never happens.
        time_to_refill = (
            (tokens_requested - updated_tokens) / refill_rate
            if refill_rate > 0
            else float("inf")
        )
    else:
        time_to_refill = (
            (bucket_size - tokens_remaining) / refill_rate if refill_rate > 0 else 0
        )

    return {
        "is_allowed": is_allowed,
        "current_tokens": updated_tokens,
        "tokens_remaining": tokens_remaining,
        "time_to_refill": time_to_refill,
    }


def format_token_bucket_metadata(
    tokens_remaining: float,
    bucket_size: Optional[float] = None,
    refill_rate: Optional[float] = None,
    time_to_refill: Optional[float] = None,
    tokens_requested: Optional[int] = None,
    last_refill: Optional[float] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Format token bucket metadata for API responses.

    Args:
        tokens_remaining: Current tokens remaining
        bucket_size: Maximum bucket capacity
        refill_rate: Tokens added per second
        time_to_refill: Time until bucket is full or specific tokens available
        tokens_requested: Number of tokens that were requested
        last_refill: Last refill timestamp
        **kwargs: Additional metadata

    Returns:
        Formatted metadata dictionary
    """
    metadata = {"tokens_remaining": tokens_remaining, **kwargs}

    if bucket_size is not None:
        metadata["bucket_size"] = bucket_size
        # Guard against division by zero
        if bucket_size > 0:
            metadata["utilization_percent"] = (
                (bucket_size - tokens_remaining) / bucket_size
            ) * 100
        else:
            metadata["utilization_percent"] = 0

    if refill_rate is not None:
        metadata["refill_rate"] = refill_rate

    if time_to_refill is not None:
        metadata["time_to_refill"] = time_to_refill

    if tokens_requested is not None:
        metadata["tokens_requested"] = tokens_requested

    if last_refill is not None:
        metadata["last_refill"] = last_refill

    return metadata


def estimate_backend_memory_usage(
    data: Dict[str, Any], backend_type: str = "generic"
) -> Dict[str, Any]:
    """
    Estimate memory usage for backend data.

    Args:
        data: Data to analyze
        backend_type: Type of backend

    Returns:
        Memory usage estimates
    """
    try:
        # Simple estimation based on string representation
        estimated_bytes = len(json.dumps(data, default=str))
    except Exception:
        estimated_bytes = 0

    # Backend-specific multipliers for overhead
    multipliers = {
        "redis": 1.5,  # Redis overhead
        "database": 2.0,  # Database + ORM overhead
        "memory": 1.1,  # Minimal overhead
        "multi": 1.2,  # Multi-backend coordination overhead
        "generic": 1.0,
    }

    multiplier = multipliers.get(backend_type, 1.0)
    total_bytes = int(estimated_bytes * multiplier)

    return {
        "estimated_bytes": total_bytes,
        "estimated_kb": round(total_bytes / 1024, 2),
        "estimated_mb": round(total_bytes / (1024 * 1024), 2),
        "backend_type": backend_type,
        "raw_bytes": estimated_bytes,
        "overhead_multiplier": multiplier,
    }


# ============================================================================
# Retry and Operation Helpers
# ============================================================================


def format_lua_script(script: str) -> str:
    """
    Format and optimize a Lua script.

    Args:
        script: Raw Lua script

    Returns:
        Formatted Lua script
    """
    # Remove extra whitespace and comments for optimization
    lines = []
    for line in script.split("\n"):
        line = line.strip()
        if line and not line.startswith("--"):
            lines.append(line)
    return "\n".join(lines)


# ============================================================================
# Advanced Utilities (Merged from advanced_utils.py)
# ============================================================================


class BackendOperationMixin:
    """
    Mixin class providing common backend operation patterns.

    This reduces code duplication across backend implementations by providing
    standardized patterns for common operations.
    """

    def _execute_with_retry(
        self,
        operation_name: str,
        operation_func: Callable,
        max_retries: int = 3,
        retry_delay: float = 0.1,
        *_args: Any,
        **_kwargs: Any,
    ) -> Any:
        """
        Execute an operation with retry logic and logging.

        Args:
            operation_name: Name of the operation for logging
            operation_func: Function to execute
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
            *_args, **_kwargs: Arguments to pass to operation_func

        Returns:
            Result of the operation

        Raises:
            Last exception encountered after all retries
        """
        last_exception: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                start_time = time.time()
                result = operation_func(*_args, **_kwargs)

                # Log successful operation
                duration_ms = (time.time() - start_time) * 1000
                log_backend_operation(
                    operation_name,
                    f"Operation successful on attempt {attempt + 1}",
                    duration_ms,
                )

                return result

            except Exception as e:
                last_exception = e

                if attempt < max_retries:
                    logger.warning(
                        f"Backend operation {operation_name} failed (attempt "
                        f"{attempt + 1}/{max_retries + 1}): {e}"
                    )
                    time.sleep(retry_delay * (2**attempt))  # Exponential backoff
                else:
                    # Log final failure
                    duration_ms = (time.time() - start_time) * 1000
                    log_backend_operation(
                        operation_name,
                        f"Operation failed after {max_retries + 1} attempts: {e}",
                        duration_ms,
                        "error",
                    )

        if last_exception:
            raise last_exception
        else:
            raise RuntimeError(f"Operation {operation_name} failed without exception")

    def _normalize_backend_key(self, key: str, operation_type: str = "") -> str:
        """
        Normalize a key for backend operations with operation-specific prefixes.

        Args:
            key: The key to normalize
            operation_type: Type of operation (e.g., "token_bucket", "sliding", "fixed")

        Returns:
            Normalized key
        """
        prefix = getattr(self, "key_prefix", "")
        if operation_type:
            key = f"{key}:{operation_type}"
        return normalize_key(key, prefix)

    def _format_operation_metadata(
        self, operation_type: str, success: bool, **metadata: Any
    ) -> Dict[str, Any]:
        """
        Format metadata for backend operations in a standardized way.

        Args:
            operation_type: Type of operation
            success: Whether the operation succeeded
            **metadata: Additional metadata fields

        Returns:
            Formatted metadata dictionary
        """
        base_metadata = {
            "operation_type": operation_type,
            "success": success,
            "timestamp": time.time(),
            "backend": self.__class__.__name__,
        }
        base_metadata.update(metadata)
        return base_metadata


class TokenBucketHelper:
    """
    Helper class for token bucket operations across different backends.

    Provides standardized token bucket logic that can be used by any backend.
    """

    @staticmethod
    def calculate_tokens_and_metadata(
        bucket_size: int,
        refill_rate: float,
        initial_tokens: int,
        tokens_requested: int,
        current_tokens: float,
        last_refill: float,
        current_time: float,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Calculate token bucket state and metadata in a standardized way.

        Args:
            bucket_size: Maximum bucket capacity
            refill_rate: Tokens per second refill rate
            initial_tokens: Initial tokens when bucket is created
            tokens_requested: Tokens requested for this operation
            current_tokens: Current number of tokens
            last_refill: Last refill timestamp
            current_time: Current timestamp

        Returns:
            Tuple of (is_allowed, metadata)
        """
        # Calculate time-based token refill
        time_passed = max(0, current_time - last_refill)
        tokens_to_add = time_passed * refill_rate

        # Update current tokens, capped at bucket size
        updated_tokens = min(bucket_size, current_tokens + tokens_to_add)

        # Check if request can be served
        is_allowed = updated_tokens >= tokens_requested

        if is_allowed:
            remaining_tokens = updated_tokens - tokens_requested
        else:
            remaining_tokens = updated_tokens

        # Calculate time until enough tokens are available
        if not is_allowed and refill_rate > 0:
            tokens_needed = tokens_requested - updated_tokens
            time_to_refill = tokens_needed / refill_rate
        else:
            time_to_refill = 0

        # Format metadata
        metadata = format_token_bucket_metadata(
            tokens_remaining=remaining_tokens,
            tokens_requested=tokens_requested,
            bucket_size=bucket_size,
            refill_rate=refill_rate,
            time_to_refill=time_to_refill,
        )

        return is_allowed, metadata
