"""
Performance Optimization Utilities

This module provides performance optimization utilities for rate limiting,
including caching strategies, batch operations, and performance monitoring.
"""

import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

from django.core.cache import cache
from django.http import HttpRequest

from .utils import generate_key


class RateLimitCache:
    """
    Intelligent caching system for rate limit operations.

    Provides multi-level caching with intelligent invalidation and
    performance optimization for rate limiting operations.
    """

    def __init__(self, cache_prefix: str = "rl_cache", default_timeout: int = 300):
        """Initialize instance."""
        self.cache_prefix = cache_prefix
        self.default_timeout = default_timeout

    def _make_cache_key(self, key: str, operation: str = "") -> str:
        """Create a cache key for rate limit data."""
        if operation:
            return f"{self.cache_prefix}:{operation}:{key}"
        return f"{self.cache_prefix}:{key}"

    def get_rate_limit_info(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get cached rate limit information.

        Args:
            key: Rate limit key

        Returns:
            Cached rate limit info or None
        """
        cache_key = self._make_cache_key(key, "info")
        return cache.get(cache_key)

    def set_rate_limit_info(
        self, key: str, info: Dict[str, Any], timeout: Optional[int] = None
    ) -> None:
        """
        Cache rate limit information.

        Args:
            key: Rate limit key
            info: Rate limit information to cache
            timeout: Cache timeout in seconds
        """
        cache_key = self._make_cache_key(key, "info")
        timeout = timeout or self.default_timeout
        cache.set(cache_key, info, timeout)

    def invalidate_rate_limit_info(self, key: str) -> None:
        """
        Invalidate cached rate limit information.

        Args:
            key: Rate limit key to invalidate
        """
        cache_key = self._make_cache_key(key, "info")
        cache.delete(cache_key)

    def get_backend_health(self, backend_name: str) -> Optional[bool]:
        """
        Get cached backend health status.

        Args:
            backend_name: Name of the backend

        Returns:
            Health status or None if not cached
        """
        cache_key = self._make_cache_key(backend_name, "health")
        return cache.get(cache_key)

    def set_backend_health(
        self, backend_name: str, is_healthy: bool, timeout: int = 60
    ) -> None:
        """
        Cache backend health status.

        Args:
            backend_name: Name of the backend
            is_healthy: Health status
            timeout: Cache timeout in seconds
        """
        cache_key = self._make_cache_key(backend_name, "health")
        cache.set(cache_key, is_healthy, timeout)

    def batch_invalidate(self, keys: List[str]) -> None:
        """
        Invalidate multiple cache keys in a batch.

        Args:
            keys: List of keys to invalidate
        """
        cache_keys = [self._make_cache_key(key, "info") for key in keys]
        cache.delete_many(cache_keys)


class PerformanceMonitor:
    """
    Performance monitoring for rate limiting operations.

    Tracks operation timing, throughput, and performance metrics.
    """

    def __init__(self, monitor_name: str = "rate_limit_monitor"):
        """Initialize instance."""
        self.monitor_name = monitor_name
        self._metrics: Dict[str, Dict[str, Any]] = {}

    @contextmanager
    def time_operation(self, operation_name: str) -> Iterator[None]:
        """
        Context manager for timing operations.

        Args:
            operation_name: Name of the operation being timed
        """
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            self._record_timing(operation_name, duration)

    def _record_timing(self, operation_name: str, duration: float) -> None:
        """
        Record timing information for an operation.

        Args:
            operation_name: Name of the operation
            duration: Duration in seconds
        """
        if operation_name not in self._metrics:
            self._metrics[operation_name] = {
                "count": 0,
                "total_time": 0.0,
                "min_time": float("inf"),
                "max_time": 0.0,
                "avg_time": 0.0,
            }

        metrics = self._metrics[operation_name]
        metrics["count"] += 1
        metrics["total_time"] += duration
        metrics["min_time"] = min(metrics["min_time"], duration)
        metrics["max_time"] = max(metrics["max_time"], duration)
        metrics["avg_time"] = metrics["total_time"] / metrics["count"]

    def get_metrics(self, operation_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get performance metrics.

        Args:
            operation_name: Specific operation to get metrics for, or None for all

        Returns:
            Performance metrics
        """
        if operation_name:
            return self._metrics.get(operation_name, {})
        return self._metrics.copy()

    def reset_metrics(self) -> None:
        """Reset all performance metrics."""
        self._metrics.clear()

    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get a summary of performance across all operations.

        Returns:
            Performance summary
        """
        if not self._metrics:
            return {}

        total_operations = sum(m["count"] for m in self._metrics.values())
        total_time = sum(m["total_time"] for m in self._metrics.values())
        avg_time_all = total_time / total_operations if total_operations > 0 else 0

        slowest_operation = (
            max(self._metrics.items(), key=lambda x: x[1]["avg_time"])
            if self._metrics
            else None
        )

        fastest_operation = (
            min(self._metrics.items(), key=lambda x: x[1]["avg_time"])
            if self._metrics
            else None
        )

        return {
            "total_operations": total_operations,
            "total_time": total_time,
            "average_time": avg_time_all,
            "slowest_operation": (
                {
                    "name": slowest_operation[0],
                    "avg_time": slowest_operation[1]["avg_time"],
                }
                if slowest_operation
                else None
            ),
            "fastest_operation": (
                {
                    "name": fastest_operation[0],
                    "avg_time": fastest_operation[1]["avg_time"],
                }
                if fastest_operation
                else None
            ),
            "operations": list(self._metrics.keys()),
        }


class BatchRateLimitProcessor:
    """
    Batch processing utilities for rate limiting operations.

    Allows for efficient processing of multiple rate limit checks
    and operations in batches.
    """

    def __init__(self, batch_size: int = 100):
        """Initialize instance."""
        self.batch_size = batch_size

    def batch_check_rate_limits(
        self,
        requests_and_configs: List[Tuple[HttpRequest, Dict[str, Any]]],
        backend: Any,
    ) -> List[Tuple[bool, Dict[str, Any]]]:
        """
        Check rate limits for multiple requests in batches.

        Args:
            requests_and_configs: List of (request, config) tuples
            backend: Rate limiting backend to use

        Returns:
            List of (is_allowed, metadata) tuples
        """
        results = []

        # Process in batches
        for i in range(0, len(requests_and_configs), self.batch_size):
            batch = requests_and_configs[i : i + self.batch_size]
            batch_results = self._process_batch(batch, backend)
            results.extend(batch_results)

        return results

    def _process_batch(
        self, batch: List[Tuple[HttpRequest, Dict[str, Any]]], backend: Any
    ) -> List[Tuple[bool, Dict[str, Any]]]:
        """
        Process a single batch of rate limit checks.

        Args:
            batch: Batch of (request, config) tuples
            backend: Rate limiting backend

        Returns:
            List of results for the batch
        """
        results = []

        # Group by rate limit key to optimize backend calls
        key_groups: Dict[str, List[Tuple[int, HttpRequest, Dict[str, Any]]]] = {}
        for idx, (request, config) in enumerate(batch):
            key = generate_key(config.get("key", "ip"), request)
            if key not in key_groups:
                key_groups[key] = []
            key_groups[key].append((idx, request, config))

        # Process each key group
        for key, group in key_groups.items():
            # For now, process each item individually
            # Future optimization: implement batch operations in backends
            for idx, request, config in group:
                try:
                    # Simulate rate limit check
                    # In real implementation, this would call backend methods
                    is_allowed = True  # Placeholder
                    metadata = {"key": key, "rate": config.get("rate")}
                    results.append((idx, is_allowed, metadata))
                except Exception as e:
                    results.append((idx, False, {"error": str(e)}))

        # Sort results by original index to maintain order
        results.sort(key=lambda x: x[0])
        return [(allowed, metadata) for _, allowed, metadata in results]


class RateLimitOptimizer:
    """
    Optimization utilities for rate limiting performance.

    Provides various optimization strategies to improve rate limiting performance.
    """

    def __init__(self) -> None:
        """Initialize instance."""
        self.cache = RateLimitCache()
        self.monitor = PerformanceMonitor()

    def optimize_key_generation(
        self, key_func: Callable, cache_timeout: int = 60
    ) -> Callable:
        """
        Create an optimized version of a key generation function with caching.

        Args:
            key_func: Original key generation function
            cache_timeout: Cache timeout in seconds

        Returns:
            Optimized key generation function
        """

        def optimized_key_func(
            request: HttpRequest, *_args: Any, **_kwargs: Any
        ) -> str:
            # Create a cache key based on request characteristics
            request_fingerprint = self._create_request_fingerprint(request)
            cache_key = f"key_gen:{key_func.__name__}:{request_fingerprint}"

            # Try to get from cache
            cached_key = cache.get(cache_key)
            if cached_key:
                return cached_key

            # Generate key and cache it
            with self.monitor.time_operation(f"key_gen_{key_func.__name__}"):
                generated_key = key_func(request, *_args, **_kwargs)
                cache.set(cache_key, generated_key, cache_timeout)
                return generated_key

        return optimized_key_func

    def _create_request_fingerprint(self, request: HttpRequest) -> str:
        """
        Create a fingerprint for a request to use in caching.

        Args:
            request: Django request object

        Returns:
            Request fingerprint string
        """
        # Create fingerprint based on relevant request attributes
        fingerprint_parts = [
            request.method,
            request.path,
            request.META.get("REMOTE_ADDR", ""),
            str(
                getattr(request.user, "id", None)
                if hasattr(request, "user") and request.user.is_authenticated
                else "anonymous"
            ),
        ]

        # Add relevant headers
        relevant_headers = ["HTTP_USER_AGENT", "HTTP_X_API_KEY", "HTTP_AUTHORIZATION"]
        for header in relevant_headers:
            value = request.META.get(header, "")
            if value:
                # Use hash for long values to keep fingerprint manageable
                if len(value) > 50:
                    import hashlib

                    value = hashlib.md5(
                        value.encode(), usedforsecurity=False
                    ).hexdigest()[:16]
                fingerprint_parts.append(f"{header}:{value}")

        return "|".join(fingerprint_parts)

    def create_adaptive_rate_limiter(
        self, base_config: Dict[str, Any], adaptation_factor: float = 0.1
    ) -> Callable:
        """
        Create an adaptive rate limiter that adjusts based on system load.

        Args:
            base_config: Base rate limiting configuration
            adaptation_factor: Factor for adapting rates (0.0 to 1.0)

        Returns:
            Adaptive rate limiting function
        """

        def adaptive_rate_limiter(request: HttpRequest) -> Dict[str, Any]:
            config = base_config.copy()

            # Get current system metrics
            metrics = self.monitor.get_performance_summary()

            if metrics and metrics["total_operations"] > 100:
                avg_time = metrics["average_time"]

                # If operations are taking too long, reduce rate limits
                if avg_time > 0.1:  # 100ms threshold
                    adaptation = 1.0 - (adaptation_factor * (avg_time / 0.1))
                    adaptation = max(0.1, adaptation)  # Don't reduce below 10%

                    # Adjust rate
                    original_rate = config.get("rate", "100/h")
                    rate_parts = original_rate.split("/")
                    if len(rate_parts) == 2:
                        count = int(rate_parts[0])
                        period = rate_parts[1]
                        adjusted_count = max(1, int(count * adaptation))
                        config["rate"] = f"{adjusted_count}/{period}"

            return config

        return adaptive_rate_limiter

    def create_circuit_breaker(
        self, failure_threshold: int = 5, recovery_timeout: int = 60
    ) -> Callable:
        """
        Create a circuit breaker for rate limiting operations.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Time to wait before trying to close circuit

        Returns:
            Circuit breaker decorator
        """
        state: Dict[str, Union[int, float, str]] = {
            "failures": 0,
            "last_failure_time": 0.0,
            "state": "closed",  # closed, open, half-open
        }

        def circuit_breaker(func: Callable) -> Callable:
            def wrapper(*_args: Any, **_kwargs: Any) -> Any:
                current_time = time.time()

                # Check if we should try to recover
                if (
                    state["state"] == "open"
                    and current_time - float(state["last_failure_time"])
                    > recovery_timeout
                ):
                    state["state"] = "half-open"

                # If circuit is open, fail fast
                if state["state"] == "open":
                    raise Exception("Circuit breaker is open")

                try:
                    result = func(*_args, **_kwargs)

                    # Success - reset failure count if we were half-open
                    if state["state"] == "half-open":
                        state["failures"] = 0
                        state["state"] = "closed"

                    return result

                except Exception:
                    state["failures"] = int(state["failures"]) + 1
                    state["last_failure_time"] = current_time

                    # Open circuit if threshold reached
                    if int(state["failures"]) >= failure_threshold:
                        state["state"] = "open"

                    raise

            return wrapper

        return circuit_breaker


# Global instances for easy access
rate_limit_cache = RateLimitCache()
performance_monitor = PerformanceMonitor()
batch_processor = BatchRateLimitProcessor()
optimizer = RateLimitOptimizer()
