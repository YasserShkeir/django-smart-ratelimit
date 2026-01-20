"""
Adaptive Rate Limiting module for Django Smart Ratelimit.

This module provides load-based adaptive rate limiting that automatically adjusts
rate limits based on system load metrics (CPU, memory, request latency, etc.).

When the system is under heavy load, limits become more restrictive.
When load is low, limits are more permissive (up to the configured maximum).
"""

import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class LoadMetrics:
    """Container for system load metrics."""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    request_latency_ms: float = 0.0
    active_connections: int = 0
    error_rate: float = 0.0
    custom_metrics: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class LoadIndicator(ABC):
    """Abstract base class for load indicators."""

    @abstractmethod
    def get_load(self) -> float:
        """
        Get the current load level.

        Returns:
            Load level as a float between 0.0 (no load) and 1.0 (maximum load).
        """

    @property
    def name(self) -> str:
        """Return the name of this load indicator."""
        return self.__class__.__name__


class CPULoadIndicator(LoadIndicator):
    """Load indicator based on CPU usage."""

    def __init__(self, sample_interval: float = 0.1):
        """
        Initialize CPU load indicator.

        Args:
            sample_interval: How often to sample CPU (seconds).
        """
        self._sample_interval = sample_interval
        self._psutil_available = False
        try:
            import psutil

            self._psutil = psutil
            self._psutil_available = True
        except ImportError:
            logger.warning(
                "psutil not installed. CPULoadIndicator will use fallback. "
                "Install psutil for accurate CPU monitoring: pip install psutil"
            )

    def get_load(self) -> float:
        """Get current CPU load as a value between 0.0 and 1.0."""
        if self._psutil_available:
            try:
                cpu_percent = self._psutil.cpu_percent(interval=self._sample_interval)
                return min(1.0, cpu_percent / 100.0)
            except Exception as e:
                logger.warning(f"Failed to get CPU load via psutil: {e}")

        # Fallback: use os.getloadavg() on Unix systems
        try:
            load_avg = os.getloadavg()[0]  # 1-minute load average
            cpu_count = os.cpu_count() or 1
            # Normalize: load average of cpu_count means 100% utilization
            return min(1.0, load_avg / cpu_count)
        except (OSError, AttributeError):
            # Windows doesn't support getloadavg
            return 0.0


class MemoryLoadIndicator(LoadIndicator):
    """Load indicator based on memory usage."""

    def __init__(self) -> None:
        """Initialize memory load indicator."""
        self._psutil_available = False
        try:
            import psutil

            self._psutil = psutil
            self._psutil_available = True
        except ImportError:
            logger.warning(
                "psutil not installed. MemoryLoadIndicator will return 0. "
                "Install psutil for memory monitoring: pip install psutil"
            )

    def get_load(self) -> float:
        """Get current memory usage as a value between 0.0 and 1.0."""
        if self._psutil_available:
            try:
                mem = self._psutil.virtual_memory()
                return min(1.0, mem.percent / 100.0)
            except Exception as e:
                logger.warning(f"Failed to get memory load via psutil: {e}")
        return 0.0


class LatencyLoadIndicator(LoadIndicator):
    """Load indicator based on recent request latency."""

    def __init__(
        self,
        target_latency_ms: float = 100.0,
        max_latency_ms: float = 1000.0,
        window_size: int = 100,
    ):
        """
        Initialize latency load indicator.

        Args:
            target_latency_ms: Target latency in milliseconds (load=0 at or below).
            max_latency_ms: Maximum latency (load=1 at or above).
            window_size: Number of recent requests to consider.
        """
        self._target_latency = target_latency_ms
        self._max_latency = max_latency_ms
        self._window_size = window_size
        self._latencies: List[float] = []
        self._lock = threading.Lock()

    def record_latency(self, latency_ms: float) -> None:
        """
        Record a request latency.

        Args:
            latency_ms: Request latency in milliseconds.
        """
        with self._lock:
            self._latencies.append(latency_ms)
            if len(self._latencies) > self._window_size:
                self._latencies.pop(0)

    def get_load(self) -> float:
        """Get load based on average latency."""
        with self._lock:
            if not self._latencies:
                return 0.0
            avg_latency = sum(self._latencies) / len(self._latencies)

        if avg_latency <= self._target_latency:
            return 0.0
        if avg_latency >= self._max_latency:
            return 1.0

        # Linear interpolation between target and max
        return (avg_latency - self._target_latency) / (
            self._max_latency - self._target_latency
        )


class ConnectionCountIndicator(LoadIndicator):
    """Load indicator based on active connection count."""

    def __init__(self, max_connections: int = 1000):
        """
        Initialize connection count indicator.

        Args:
            max_connections: Maximum expected connections (load=1).
        """
        self._max_connections = max_connections
        self._current_connections = 0
        self._lock = threading.Lock()

    def increment(self) -> None:
        """Increment the connection count."""
        with self._lock:
            self._current_connections += 1

    def decrement(self) -> None:
        """Decrement the connection count."""
        with self._lock:
            self._current_connections = max(0, self._current_connections - 1)

    def get_load(self) -> float:
        """Get load based on connection count."""
        with self._lock:
            return min(1.0, self._current_connections / self._max_connections)


class CustomLoadIndicator(LoadIndicator):
    """Load indicator that uses a custom function."""

    def __init__(self, load_function: Callable[[], float], name: str = "custom"):
        """
        Initialize custom load indicator.

        Args:
            load_function: Function that returns load as float between 0.0 and 1.0.
            name: Name for this indicator.
        """
        self._load_function = load_function
        self._name = name

    def get_load(self) -> float:
        """Get load from custom function."""
        try:
            load = self._load_function()
            return max(0.0, min(1.0, float(load)))
        except Exception as e:
            logger.warning(f"Custom load indicator '{self._name}' failed: {e}")
            return 0.0

    @property
    def name(self) -> str:
        """Return the custom name."""
        return self._name


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter that adjusts limits based on system load.

    The limiter monitors one or more load indicators and adjusts the effective
    rate limit between a minimum and maximum value based on the combined load.

    Higher load → Lower effective limit (more restrictive)
    Lower load → Higher effective limit (more permissive)
    """

    def __init__(
        self,
        base_limit: int,
        min_limit: Optional[int] = None,
        max_limit: Optional[int] = None,
        indicators: Optional[List[LoadIndicator]] = None,
        weights: Optional[Dict[str, float]] = None,
        load_threshold_low: float = 0.3,
        load_threshold_high: float = 0.7,
        smoothing_factor: float = 0.3,
        update_interval: float = 1.0,
    ):
        """
        Initialize adaptive rate limiter.

        Args:
            base_limit: Base rate limit (used when load is at threshold_low).
            min_limit: Minimum rate limit (used under extreme load). Defaults to 10% of base.
            max_limit: Maximum rate limit (used when load is very low). Defaults to base_limit.
            indicators: List of LoadIndicator instances to monitor.
            weights: Dict mapping indicator names to weights (default: equal weights).
            load_threshold_low: Load below this is considered "low" (more permissive).
            load_threshold_high: Load above this is considered "high" (more restrictive).
            smoothing_factor: Factor for exponential smoothing of load (0-1).
                              Higher = more responsive, lower = more stable.
            update_interval: How often to recalculate the effective limit (seconds).
        """
        self.base_limit = base_limit
        self.min_limit = (
            min_limit if min_limit is not None else max(1, base_limit // 10)
        )
        self.max_limit = max_limit if max_limit is not None else base_limit
        self.load_threshold_low = load_threshold_low
        self.load_threshold_high = load_threshold_high
        self.smoothing_factor = smoothing_factor
        self.update_interval = update_interval

        # Initialize with default indicators if None provided (explicit empty list means no indicators)
        self._indicators: List[LoadIndicator]
        if indicators is None:
            # Default: use CPU indicator
            self._indicators = [CPULoadIndicator()]
        else:
            self._indicators = list(indicators)

        # Weights for combining indicators
        self._weights = weights or {}

        # State
        self._current_load = 0.0
        self._effective_limit = base_limit
        self._last_update = 0.0
        self._lock = threading.Lock()

        # Metrics tracking
        self._load_history: List[Tuple[float, float]] = []  # (timestamp, load)
        self._history_max_size = 1000

    def add_indicator(
        self, indicator: LoadIndicator, weight: float = 1.0
    ) -> "AdaptiveRateLimiter":
        """
        Add a load indicator.

        Args:
            indicator: LoadIndicator instance to add.
            weight: Weight for this indicator when combining loads.

        Returns:
            Self for chaining.
        """
        self._indicators.append(indicator)
        self._weights[indicator.name] = weight
        return self

    def remove_indicator(self, name: str) -> bool:
        """
        Remove an indicator by name.

        Args:
            name: Name of the indicator to remove.

        Returns:
            True if found and removed, False otherwise.
        """
        for i, indicator in enumerate(self._indicators):
            if indicator.name == name:
                self._indicators.pop(i)
                self._weights.pop(name, None)
                return True
        return False

    def _calculate_combined_load(self) -> float:
        """Calculate combined load from all indicators."""
        if not self._indicators:
            return 0.0

        total_weight = 0.0
        weighted_load = 0.0

        for indicator in self._indicators:
            try:
                load = indicator.get_load()
                weight = self._weights.get(indicator.name, 1.0)
                weighted_load += load * weight
                total_weight += weight
            except Exception as e:
                logger.warning(f"Failed to get load from {indicator.name}: {e}")

        if total_weight == 0:
            return 0.0

        return weighted_load / total_weight

    def _calculate_effective_limit(self, load: float) -> int:
        """
        Calculate the effective limit based on current load.

        Uses a linear interpolation between min_limit and max_limit
        based on where the load falls within the threshold range.
        """
        if load <= self.load_threshold_low:
            # Low load: use max_limit (most permissive)
            return self.max_limit
        elif load >= self.load_threshold_high:
            # High load: use min_limit (most restrictive)
            return self.min_limit
        else:
            # Interpolate between max and min based on load
            load_range = self.load_threshold_high - self.load_threshold_low
            load_position = (load - self.load_threshold_low) / load_range
            limit_range = self.max_limit - self.min_limit
            return int(self.max_limit - (load_position * limit_range))

    def _update_if_needed(self) -> None:
        """Update effective limit if enough time has passed."""
        current_time = time.time()

        with self._lock:
            if current_time - self._last_update < self.update_interval:
                return

            # Calculate new load
            raw_load = self._calculate_combined_load()

            # Apply exponential smoothing
            self._current_load = (
                self.smoothing_factor * raw_load
                + (1 - self.smoothing_factor) * self._current_load
            )

            # Calculate effective limit
            self._effective_limit = self._calculate_effective_limit(self._current_load)
            self._last_update = current_time

            # Track history
            self._load_history.append((current_time, self._current_load))
            if len(self._load_history) > self._history_max_size:
                self._load_history.pop(0)

    def get_effective_limit(self) -> int:
        """
        Get the current effective rate limit.

        Returns:
            The current effective limit adjusted for system load.
        """
        self._update_if_needed()
        with self._lock:
            return self._effective_limit

    def get_current_load(self) -> float:
        """
        Get the current smoothed load value.

        Returns:
            Current load as float between 0.0 and 1.0.
        """
        self._update_if_needed()
        with self._lock:
            return self._current_load

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current adaptive rate limiting metrics.

        Returns:
            Dictionary with current metrics.
        """
        self._update_if_needed()
        with self._lock:
            return {
                "base_limit": self.base_limit,
                "min_limit": self.min_limit,
                "max_limit": self.max_limit,
                "effective_limit": self._effective_limit,
                "current_load": self._current_load,
                "load_threshold_low": self.load_threshold_low,
                "load_threshold_high": self.load_threshold_high,
                "indicators": [ind.name for ind in self._indicators],
                "last_update": self._last_update,
            }

    def get_load_history(
        self, since: Optional[float] = None
    ) -> List[Tuple[float, float]]:
        """
        Get load history.

        Args:
            since: Only return entries after this timestamp.

        Returns:
            List of (timestamp, load) tuples.
        """
        with self._lock:
            if since is None:
                return list(self._load_history)
            return [(ts, load) for ts, load in self._load_history if ts > since]


# Global registry of adaptive rate limiters
_adaptive_limiters: Dict[str, AdaptiveRateLimiter] = {}
_registry_lock = threading.Lock()


def get_adaptive_limiter(name: str) -> Optional[AdaptiveRateLimiter]:
    """
    Get a registered adaptive rate limiter by name.

    Args:
        name: Name of the limiter.

    Returns:
        AdaptiveRateLimiter instance or None if not found.
    """
    with _registry_lock:
        return _adaptive_limiters.get(name)


def register_adaptive_limiter(name: str, limiter: AdaptiveRateLimiter) -> None:
    """
    Register an adaptive rate limiter.

    Args:
        name: Name to register under.
        limiter: AdaptiveRateLimiter instance.
    """
    with _registry_lock:
        _adaptive_limiters[name] = limiter


def unregister_adaptive_limiter(name: str) -> bool:
    """
    Unregister an adaptive rate limiter.

    Args:
        name: Name of the limiter to unregister.

    Returns:
        True if found and removed, False otherwise.
    """
    with _registry_lock:
        return _adaptive_limiters.pop(name, None) is not None


def create_adaptive_limiter(
    name: str,
    base_limit: int,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
    use_cpu: bool = True,
    use_memory: bool = False,
    custom_indicators: Optional[List[LoadIndicator]] = None,
    **kwargs: Any,
) -> AdaptiveRateLimiter:
    """
    Create and register an adaptive rate limiter with common configuration.

    Args:
        name: Name to register the limiter under.
        base_limit: Base rate limit.
        min_limit: Minimum limit under high load.
        max_limit: Maximum limit under low load.
        use_cpu: Whether to include CPU load indicator.
        use_memory: Whether to include memory load indicator.
        custom_indicators: Additional custom indicators.
        **kwargs: Additional kwargs passed to AdaptiveRateLimiter.

    Returns:
        The created AdaptiveRateLimiter instance.
    """
    indicators: List[LoadIndicator] = []

    if use_cpu:
        indicators.append(CPULoadIndicator())
    if use_memory:
        indicators.append(MemoryLoadIndicator())
    if custom_indicators:
        indicators.extend(custom_indicators)

    limiter = AdaptiveRateLimiter(
        base_limit=base_limit,
        min_limit=min_limit,
        max_limit=max_limit,
        indicators=indicators,
        **kwargs,
    )

    register_adaptive_limiter(name, limiter)
    return limiter
