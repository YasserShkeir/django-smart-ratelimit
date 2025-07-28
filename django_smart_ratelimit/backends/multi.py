"""Multi-backend support for Django Smart Ratelimit."""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseBackend
from .factory import BackendFactory
from .utils import (
    estimate_backend_memory_usage,
    log_backend_operation,
    retry_backend_operation,
    validate_backend_config,
)

logger = logging.getLogger(__name__)


class BackendHealthChecker:
    """Health checker for backends."""

    def __init__(self, check_interval: int = 30, timeout: int = 5):
        """
        Initialize health checker.

        Args:
            check_interval: How often to check backend health (seconds)
            timeout: Timeout for health checks (seconds)
        """
        self.check_interval = check_interval
        self.timeout = timeout
        self._last_check: Dict[str, float] = {}
        self._health_status: Dict[str, bool] = {}

    def is_healthy(self, backend_name: str, backend: BaseBackend) -> bool:
        """
        Check if backend is healthy using utilities.

        Args:
            backend_name: Name of the backend
            backend: Backend instance

        Returns:
            True if backend is healthy, False otherwise
        """
        now = time.time()
        last_check = self._last_check.get(backend_name, 0)

        # Check if we need to perform a health check
        if now - last_check < self.check_interval:
            return self._health_status.get(backend_name, True)

        # Perform health check using utility retry mechanism
        @retry_backend_operation(max_retries=2, delay=0.5)
        def _check_backend_health() -> bool:
            # Try to perform a lightweight operation
            test_key = f"_health_check_{int(now)}"
            backend.get_count(test_key)
            return True

        try:
            _check_backend_health()
            self._health_status[backend_name] = True

            log_backend_operation(
                "multi_backend_health_check",
                f"Backend {backend_name} is healthy",
                level="debug",
            )
        except Exception as e:
            self._health_status[backend_name] = False

            log_backend_operation(
                "multi_backend_health_check_error",
                f"Backend {backend_name} health check failed: {e}",
                level="warning",
            )

        self._last_check[backend_name] = now
        return self._health_status[backend_name]


class MultiBackend(BaseBackend):
    """
    Multi-backend support with fallback mechanism.

    This backend allows using multiple backends with automatic fallback
    when the primary backend fails.
    """

    def __init__(
        self,
        enable_circuit_breaker: bool = True,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize multi-backend with configuration validation.

        Args:
            enable_circuit_breaker: Whether to enable circuit breaker protection
            circuit_breaker_config: Custom circuit breaker configuration
            **kwargs: Configuration options including:
                - backends: List of backend configurations
                - fallback_strategy: How to handle fallbacks
                  ("first_healthy", "round_robin")
                - health_check_interval: How often to check backend health
                - health_check_timeout: Timeout for health checks
        """
        # Initialize parent class with circuit breaker
        super().__init__(enable_circuit_breaker, circuit_breaker_config)

        from django.conf import settings

        # Validate configuration using utility
        validate_backend_config(kwargs, backend_type="multi")

        self.backends: List[Tuple[str, BaseBackend]] = []
        self.fallback_strategy = kwargs.get(
            "fallback_strategy",
            getattr(
                settings,
                "RATELIMIT_MULTI_BACKEND_STRATEGY",
                "first_healthy",
            ),
        )
        self.health_checker = BackendHealthChecker(
            check_interval=kwargs.get(
                "health_check_interval",
                getattr(settings, "RATELIMIT_HEALTH_CHECK_INTERVAL", 30),
            ),
            timeout=kwargs.get(
                "health_check_timeout",
                getattr(settings, "RATELIMIT_HEALTH_CHECK_TIMEOUT", 5),
            ),
        )

        # Initialize backends from configuration
        backend_configs = kwargs.get(
            "backends",
            getattr(settings, "RATELIMIT_MULTI_BACKENDS", []),
        )

        if not backend_configs:
            raise ValueError(
                "Multi-backend requires at least one backend configuration"
            )

        for backend_config in backend_configs:
            try:
                # Support both 'type' and 'backend' for backward compatibility
                backend_type = backend_config.get("type") or backend_config.get(
                    "backend"
                )
                backend_name = backend_config.get("name", backend_type or "unnamed")
                backend_options = backend_config.get(
                    "options", {}
                ) or backend_config.get("config", {})

                if not backend_type:
                    raise ValueError(
                        f"Backend {backend_name} missing 'type' configuration"
                    )

                backend_instance = BackendFactory.create_backend(
                    backend_type, **backend_options
                )
                self.backends.append((backend_name, backend_instance))

                log_backend_operation(
                    "multi_backend_init",
                    f"Initialized backend {backend_name} ({backend_type})",
                    level="info",
                )

            except Exception as e:
                log_backend_operation(
                    "multi_backend_init_error",
                    f"Failed to initialize backend {backend_config}: {e}",
                    level="error",
                )
                # Continue with other backends rather than failing completely
                continue

        if not self.backends:
            raise ValueError("No backends were successfully initialized")

        log_backend_operation(
            "multi_backend_init_complete",
            f"Multi-backend initialized with {len(self.backends)} backends, "
            f"strategy: {self.fallback_strategy}",
            level="info",
        )

        self._current_backend_index = 0

    def _get_healthy_backend(self) -> Optional[Tuple[str, BaseBackend]]:
        """
        Get the first healthy backend based on fallback strategy.

        Returns:
            Tuple of (backend_name, backend) if healthy backend found, None otherwise
        """
        if self.fallback_strategy == "first_healthy":
            for name, backend in self.backends:
                if self.health_checker.is_healthy(name, backend):
                    return name, backend
        elif self.fallback_strategy == "round_robin":
            # Try backends in round-robin order
            for i in range(len(self.backends)):
                idx = (self._current_backend_index + i) % len(self.backends)
                name, backend = self.backends[idx]
                if self.health_checker.is_healthy(name, backend):
                    self._current_backend_index = (idx + 1) % len(self.backends)
                    return name, backend

        return None

    def _execute_with_fallback(
        self, method_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        """
        Execute method with fallback to healthy backends using utilities.

        Args:
            method_name: Name of the method to execute
            *args: Positional arguments for the method
            **kwargs: Keyword arguments for the method

        Returns:
            Result from the method execution

        Raises:
            Exception: If all backends fail
        """
        start_time = time.time()
        last_exception = None
        attempted_backends = []

        for name, backend in self.backends:
            if not self.health_checker.is_healthy(name, backend):
                continue

            try:
                method = getattr(backend, method_name)
                result = method(*args, **kwargs)

                log_backend_operation(
                    "multi_backend_execute_success",
                    f"Successfully executed {method_name} on backend {name}",
                    duration=time.time() - start_time,
                    level="debug",
                )

                return result
            except Exception as e:
                log_backend_operation(
                    "multi_backend_execute_error",
                    f"Backend {name} failed for {method_name}: {e}",
                    level="warning",
                )
                # Also log to the multi-backend's logger for test compatibility
                logger.warning(f"Backend {name} failed for {method_name}: {e}")
                attempted_backends.append(name)
                last_exception = e
                # Mark backend as unhealthy
                self.health_checker._health_status[name] = False
                continue

        # All backends failed
        error_msg = (
            f"All backends failed for {method_name}. Attempted: {attempted_backends}"
        )

        log_backend_operation(
            "multi_backend_execute_all_failed",
            error_msg,
            duration=time.time() - start_time,
            level="error",
        )

        if last_exception:
            raise last_exception
        else:
            raise RuntimeError(error_msg)

    def incr(self, key: str, period: int) -> int:
        """
        Increment rate limit counter with fallback.

        Args:
            key: Rate limit key
            period: Time period in seconds

        Returns:
            Current count after increment
        """
        return self._execute_with_fallback("incr", key, period)

    def get_count(self, key: str) -> int:
        """
        Get current count with fallback.

        Args:
            key: Rate limit key

        Returns:
            Current count
        """
        return self._execute_with_fallback("get_count", key)

    def get_reset_time(self, key: str) -> Optional[int]:
        """
        Get reset time with fallback.

        Args:
            key: Rate limit key

        Returns:
            Unix timestamp when key expires, or None if key doesn't exist
        """
        return self._execute_with_fallback("get_reset_time", key)

    def reset(self, key: str) -> None:
        """
        Reset rate limit counter with fallback.

        Args:
            key: Rate limit key
        """
        return self._execute_with_fallback("reset", key)

    def increment(self, key: str, window_seconds: int, limit: int) -> Tuple[int, int]:
        """
        Increment rate limit counter with fallback (legacy method).

        Args:
            key: Rate limit key
            window_seconds: Window size in seconds
            limit: Rate limit

        Returns:
            Tuple of (current_count, remaining_count)
        """
        return self._execute_with_fallback("increment", key, window_seconds, limit)

    def get_count_with_window(self, key: str, _window_seconds: int) -> int:
        """
        Get current count with window (legacy method).

        Args:
            key: Rate limit key
            window_seconds: Window size in seconds

        Returns:
            Current count
        """
        # For backward compatibility, just call get_count with the key
        # The window_seconds parameter is ignored as it's not part of the base interface
        return self._execute_with_fallback("get_count", key)

    def cleanup_expired(self) -> int:
        """
        Clean up expired entries with fallback.

        Returns:
            Number of cleaned up entries
        """
        return self._execute_with_fallback("cleanup_expired")

    def get_backend_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Get status of all backends.

        Returns:
            Dictionary with backend status information
        """
        status = {}
        for name, backend in self.backends:
            is_healthy = self.health_checker.is_healthy(name, backend)
            status[name] = {
                "healthy": is_healthy,
                "backend_class": backend.__class__.__name__,
                "last_check": self.health_checker._last_check.get(name, 0),
            }
        return status

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics from all backends.

        Returns:
            Dictionary with backend statistics
        """
        stats = {
            "total_backends": len(self.backends),
            "healthy_backends": sum(
                1
                for name, backend in self.backends
                if self.health_checker.is_healthy(name, backend)
            ),
            "fallback_strategy": self.fallback_strategy,
            "backends": self.get_backend_status(),
        }
        return stats

    def health_check(self) -> Dict[str, Any]:
        """
        Check the health of all backends using backend utilities.

        Returns:
            Dictionary with health status information for all backends
        """
        start_time = time.time()
        backend_statuses = {}
        healthy_count = 0
        total_count = len(self.backends)

        for name, backend in self.backends:
            try:
                # Check if backend has its own health_check method
                if hasattr(backend, "health_check"):
                    backend_health = backend.health_check()
                else:
                    # Use our health checker
                    is_healthy = self.health_checker.is_healthy(name, backend)
                    backend_health = {
                        "status": "healthy" if is_healthy else "unhealthy",
                        "backend_class": backend.__class__.__name__,
                        "last_check": self.health_checker._last_check.get(name, 0),
                    }

                backend_statuses[name] = backend_health

                if backend_health.get("status") == "healthy":
                    healthy_count += 1

            except Exception as e:
                backend_statuses[name] = {
                    "status": "unhealthy",
                    "error": str(e),
                    "backend_class": backend.__class__.__name__,
                }

        # Overall health status
        overall_status = "healthy" if healthy_count > 0 else "unhealthy"

        # Estimate memory usage using utility
        memory_data = {
            "backend_count": total_count,
            "healthy_count": healthy_count,
            "backend_statuses": backend_statuses,
        }

        memory_usage = estimate_backend_memory_usage(memory_data, backend_type="multi")

        health_data = {
            "status": overall_status,
            "response_time": time.time() - start_time,
            "backend_type": "multi",
            "total_backends": total_count,
            "healthy_backends": healthy_count,
            "fallback_strategy": self.fallback_strategy,
            "backends": backend_statuses,
            "estimated_memory_usage": memory_usage,
        }

        log_backend_operation(
            "multi_backend_health_check",
            f"Health check complete: {healthy_count}/{total_count} backends healthy",
            duration=health_data["response_time"],
        )

        return health_data
