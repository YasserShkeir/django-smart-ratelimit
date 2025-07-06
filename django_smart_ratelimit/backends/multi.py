"""Multi-backend support for Django Smart Ratelimit."""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseBackend
from .factory import BackendFactory

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
        Check if backend is healthy.

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

        # Perform health check
        try:
            # Simple health check: try to get a non-existent key
            test_key = f"_health_check_{int(now)}"
            backend.get_count(test_key)
            self._health_status[backend_name] = True
            logger.debug(f"Backend {backend_name} is healthy")
        except Exception as e:
            self._health_status[backend_name] = False
            logger.warning(f"Backend {backend_name} health check failed: {e}")

        self._last_check[backend_name] = now
        return self._health_status[backend_name]


class MultiBackend(BaseBackend):
    """
    Multi-backend support with fallback mechanism.

    This backend allows using multiple backends with automatic fallback
    when the primary backend fails.
    """

    def __init__(self, **kwargs: Any) -> None:
        """
        Initialize multi-backend.

        Args:
            **kwargs: Configuration options including:
                - backends: List of backend configurations
                - fallback_strategy: How to handle fallbacks
                  ("first_healthy", "round_robin")
                - health_check_interval: How often to check backend health
                - health_check_timeout: Timeout for health checks
        """
        from django.conf import settings

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
        self._current_backend_index = 0

        # Get backends from kwargs or settings
        backends = kwargs.get("backends")
        if not backends:
            backends = getattr(settings, "RATELIMIT_BACKENDS", [])

        self._setup_backends(backends)

    def _setup_backends(self, backend_configs: List[Dict[str, Any]]) -> None:
        """
        Set up backend instances from configurations.

        Args:
            backend_configs: List of backend configuration dictionaries
        """
        for config in backend_configs:
            backend_path = config.get("backend")
            backend_name = config.get("name") or backend_path
            backend_config = config.get("config", {})

            if not backend_path:
                logger.warning("Backend configuration missing 'backend' key")
                continue

            # Ensure backend_name is a string
            if not backend_name:
                logger.warning(
                    "Backend configuration missing both 'name' and 'backend' keys"
                )
                continue

            try:
                backend = BackendFactory.create_backend(backend_path, **backend_config)
                self.backends.append((backend_name, backend))
                logger.info(f"Initialized backend: {backend_name}")
            except Exception as e:
                logger.error(f"Failed to initialize backend {backend_name}: {e}")

        if not self.backends:
            raise ValueError(
                "No backends configured or all backends failed to initialize"
            )

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
        Execute method with fallback to healthy backends.

        Args:
            method_name: Name of the method to execute
            *args: Positional arguments for the method
            **kwargs: Keyword arguments for the method

        Returns:
            Result from the method execution

        Raises:
            Exception: If all backends fail
        """
        last_exception = None
        attempted_backends = []

        for name, backend in self.backends:
            if not self.health_checker.is_healthy(name, backend):
                continue

            try:
                method = getattr(backend, method_name)
                result = method(*args, **kwargs)
                logger.debug(f"Successfully executed {method_name} on backend {name}")
                return result
            except Exception as e:
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
        logger.error(error_msg)
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

    def get_count_with_window(self, key: str, window_seconds: int) -> int:
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
