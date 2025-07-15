"""
Advanced Backend Utilities

This module provides additional utilities for backend operations, common patterns,
and performance optimizations that reduce duplication across backend implementations.
"""

import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, Tuple

from django.core.cache import cache

from .utils import format_token_bucket_metadata, log_backend_operation, normalize_key

logger = logging.getLogger(__name__)


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
                        f"Backend operation {operation_name} failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
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


class BackendHealthMonitor:
    """
    Health monitoring utilities for backends.

    Provides standardized health checks and monitoring across different backends.
    """

    def __init__(self, backend_name: str, cache_timeout: int = 60):
        """Initialize instance."""
        self.backend_name = backend_name
        self.cache_timeout = cache_timeout
        self._health_cache_key = f"backend_health:{backend_name}"

    def is_healthy(self, force_check: bool = False) -> bool:
        """
        Check if the backend is healthy, with caching.

        Args:
            force_check: Force a fresh health check, bypassing cache

        Returns:
            True if backend is healthy
        """
        if not force_check:
            cached_status = cache.get(self._health_cache_key)
            if cached_status is not None:
                return cached_status

        # Perform actual health check
        try:
            health_status = self._perform_health_check()
            cache.set(self._health_cache_key, health_status, self.cache_timeout)
            return health_status
        except Exception as e:
            logger.error(f"Health check failed for {self.backend_name}: {e}")
            cache.set(self._health_cache_key, False, self.cache_timeout // 2)
            return False

    def _perform_health_check(self) -> bool:
        """
        Override this method in specific backend implementations.

        Returns:
            True if backend is healthy
        """
        raise NotImplementedError("Subclasses must implement _perform_health_check")

    def mark_unhealthy(self, reason: str = "") -> None:
        """
        Mark the backend as unhealthy.

        Args:
            reason: Reason for marking as unhealthy
        """
        logger.warning(f"Marking {self.backend_name} as unhealthy: {reason}")
        cache.set(self._health_cache_key, False, self.cache_timeout)

    def clear_health_cache(self) -> None:
        """Clear the health status cache."""
        cache.delete(self._health_cache_key)


class BackendConnectionPool:
    """
    Connection pooling utilities for backends that support it.

    Provides standardized connection management patterns.
    """

    def __init__(self, backend_name: str, max_connections: int = 10):
        """Initialize instance."""
        self.backend_name = backend_name
        self.max_connections = max_connections
        self._connections: List[Any] = []
        self._active_connections = 0

    @contextmanager
    def get_connection(self) -> Any:
        """
        Context manager for getting and releasing connections.

        Yields:
            Connection object
        """
        connection = self._acquire_connection()
        try:
            yield connection
        finally:
            self._release_connection(connection)

    def _acquire_connection(self) -> Any:
        """Acquire a connection from the pool."""
        # Implementation would depend on specific backend
        # This is a placeholder for the pattern
        self._active_connections += 1
        return object()  # Placeholder connection

    def _release_connection(self, connection: Any) -> None:
        """Release a connection back to the pool."""
        self._active_connections -= 1

    def close_all_connections(self) -> None:
        """Close all connections in the pool."""
        self._connections.clear()
        self._active_connections = 0


class BackendMetricsCollector:
    """
    Metrics collection utilities for backends.

    Provides standardized metrics collection across different backends.
    """

    def __init__(self, backend_name: str):
        """Initialize instance."""
        self.backend_name = backend_name
        self._metrics_cache_key = f"backend_metrics:{backend_name}"

    def record_operation(
        self,
        operation: str,
        duration_ms: float,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record an operation for metrics.

        Args:
            operation: Name of the operation
            duration_ms: Duration in milliseconds
            success: Whether the operation succeeded
            metadata: Additional metadata
        """
        metrics = self._get_metrics()

        if operation not in metrics["operations"]:
            metrics["operations"][operation] = {
                "count": 0,
                "success_count": 0,
                "total_duration_ms": 0,
                "avg_duration_ms": 0,
                "last_operation": None,
            }

        op_metrics = metrics["operations"][operation]
        op_metrics["count"] += 1
        if success:
            op_metrics["success_count"] += 1
        op_metrics["total_duration_ms"] += duration_ms
        op_metrics["avg_duration_ms"] = (
            op_metrics["total_duration_ms"] / op_metrics["count"]
        )
        op_metrics["last_operation"] = time.time()

        self._save_metrics(metrics)

    def _get_metrics(self) -> Dict[str, Any]:
        """Get current metrics from cache."""
        metrics = cache.get(self._metrics_cache_key)
        if metrics is None:
            metrics = {
                "backend": self.backend_name,
                "operations": {},
                "started_at": time.time(),
            }
        return metrics

    def _save_metrics(self, metrics: Dict[str, Any]) -> None:
        """Save metrics to cache."""
        cache.set(self._metrics_cache_key, metrics, 3600)  # 1 hour

    def get_operation_stats(self, operation: str) -> Dict[str, Any]:
        """Get statistics for a specific operation."""
        metrics = self._get_metrics()
        return metrics["operations"].get(operation, {})

    def get_all_stats(self) -> Dict[str, Any]:
        """Get all metrics for this backend."""
        return self._get_metrics()


def create_backend_operation_context(backend_name: str, operation: str) -> Any:
    """
    Create a context manager for backend operations with standardized logging and metrics.

    Args:
        backend_name: Name of the backend
        operation: Name of the operation

    Returns:
        Context manager that handles timing, logging, and metrics
    """

    @contextmanager
    def operation_context() -> Any:
        start_time = time.time()
        success = False
        error = None

        try:
            yield
            success = True
        except Exception as e:
            error = e
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000

            # Log operation
            if success:
                log_backend_operation(
                    operation,
                    f"{backend_name} operation completed successfully",
                    duration_ms,
                )
            else:
                log_backend_operation(
                    operation,
                    f"{backend_name} operation failed: {error}",
                    duration_ms,
                    "error",
                )

            # Record metrics
            metrics_collector = BackendMetricsCollector(backend_name)
            metrics_collector.record_operation(operation, duration_ms, success)

    return operation_context


def standardize_backend_error_handling(backend_name: str) -> Callable:
    """
    Decorator for standardizing error handling across backends.

    Args:
        backend_name: Name of the backend for logging
    """

    def decorator(func: Callable) -> Callable:
        def wrapper(*_args: Any, **_kwargs: Any) -> Any:
            try:
                return func(*_args, **_kwargs)
            except Exception as e:
                # Log the error
                logger.error(f"{backend_name} operation {func.__name__} failed: {e}")

                # Mark backend as potentially unhealthy if it's a connection issue
                if "connection" in str(e).lower() or "timeout" in str(e).lower():
                    health_monitor = BackendHealthMonitor(backend_name)
                    health_monitor.mark_unhealthy(str(e))

                raise

        return wrapper

    return decorator
