"""
Backend utility functions for Django Smart Ratelimit.

This module provides common functionality used across different backend implementations,
including connection handling, data serialization, key management, and monitoring.
"""

import hashlib
import json
import logging
import time
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


# ============================================================================
# Connection and Health Management
# ============================================================================


def with_retry(
    max_retries: int = 3, delay: float = 0.1, exponential_backoff: bool = True
) -> Callable:
    """
    Decorator for retrying backend operations with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        exponential_backoff: Whether to use exponential backoff
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"Backend operation failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
                        )
                        time.sleep(current_delay)
                        if exponential_backoff:
                            current_delay *= 2
                    else:
                        logger.error(
                            f"Backend operation failed after {max_retries + 1} attempts: {e}"
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
        hash_suffix = hashlib.md5(full_key.encode(), usedforsecurity=False).hexdigest()[
            :16
        ]
        if prefix:
            readable_part = f"{prefix}:..."
        else:
            readable_part = "..."

        # Calculate available space for readable part
        available_length = max_length - len(hash_suffix) - 1  # -1 for separator
        if len(readable_part) > available_length:
            readable_part = readable_part[:available_length]

        full_key = f"{readable_part}:{hash_suffix}"

    return full_key


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
    cutoff_time = current_time - window_size
    return sum(1 for timestamp, _ in window_data if timestamp > cutoff_time)


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


def merge_rate_limit_data(
    data1: Dict[str, Any], data2: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Merge rate limiting data from multiple sources.

    Args:
        data1: First data dictionary
        data2: Second data dictionary

    Returns:
        Merged data dictionary
    """
    merged = data1.copy()

    for key, value in data2.items():
        if key in merged:
            # Handle merging based on data type
            if isinstance(value, (int, float)) and isinstance(
                merged[key], (int, float)
            ):
                merged[key] += value
            elif isinstance(value, list) and isinstance(merged[key], list):
                merged[key].extend(value)
            elif isinstance(value, dict) and isinstance(merged[key], dict):
                merged[key].update(value)
            else:
                # Default: use newer value
                merged[key] = value
        else:
            merged[key] = value

    return merged


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
# Backend Factory and Registration
# ============================================================================

_backend_registry = {}


def register_backend(name: str, backend_class: type) -> None:
    """
    Register a backend implementation.

    Args:
        name: Backend name
        backend_class: Backend class
    """
    _backend_registry[name] = backend_class


def get_registered_backends() -> Dict[str, type]:
    """
    Get all registered backend implementations.

    Returns:
        Dictionary of backend name to class mappings
    """
    return _backend_registry.copy()


def create_backend_instance(backend_name: str, **kwargs: Any) -> Any:
    """
    Create a backend instance by name.

    Args:
        backend_name: Name of the backend
        **kwargs: Backend configuration

    Returns:
        Backend instance

    Raises:
        ValueError: If backend is not registered
    """
    if backend_name not in _backend_registry:
        available = list(_backend_registry.keys())
        raise ValueError(
            f"Backend '{backend_name}' not registered. Available: {available}"
        )

    backend_class = _backend_registry[backend_name]
    return backend_class(**kwargs)


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
    level: str = "info",
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
        message = f"{backend_type} {operation} operation for key '{key}' succeeded{duration_info}"
    else:
        message = f"{backend_type} {operation} operation for key '{key}' failed{duration_info}"
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
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
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


def estimate_memory_usage(data: Any) -> int:
    """
    Estimate memory usage of data structures.

    Args:
        data: Data structure to analyze

    Returns:
        Estimated memory usage in bytes
    """
    import sys

    if isinstance(data, dict):
        size = sys.getsizeof(data)
        for key, value in data.items():
            size += estimate_memory_usage(key) + estimate_memory_usage(value)
        return size
    elif isinstance(data, (list, tuple, set)):
        size = sys.getsizeof(data)
        for item in data:
            size += estimate_memory_usage(item)
        return size
    else:
        return sys.getsizeof(data)


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
        time_to_refill = (tokens_requested - updated_tokens) / refill_rate
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
        metadata["utilization_percent"] = (
            (bucket_size - tokens_remaining) / bucket_size
        ) * 100

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
    estimated_bytes = estimate_memory_usage(data)

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


def retry_backend_operation(max_retries: int = 3, delay: float = 0.1) -> Callable:
    """
    Decorator for retrying backend operations.

    Args:
        max_retries: Maximum number of retry attempts
        delay: Delay between retries in seconds
    """
    return with_retry(max_retries=max_retries, delay=delay, exponential_backoff=True)


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
