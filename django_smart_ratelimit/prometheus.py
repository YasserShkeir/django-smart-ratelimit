"""
Prometheus metrics integration for Django Smart Ratelimit.

This module provides Prometheus-compatible metrics collection and exposure
for rate limiting operations. It works with or without the prometheus_client
library installed.

Usage:
    1. Add the middleware to collect metrics automatically:
        MIDDLEWARE = [
            ...
            'django_smart_ratelimit.prometheus.PrometheusMetricsMiddleware',
        ]

    2. Add the metrics endpoint to your URLs:
        from django_smart_ratelimit.prometheus import prometheus_metrics_view

        urlpatterns = [
            path('metrics/', prometheus_metrics_view),
        ]

    3. Configure in settings.py:
        RATELIMIT_PROMETHEUS = {
            'ENABLED': True,
            'PREFIX': 'django_ratelimit',  # Metric name prefix
        }
"""

import threading
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from django.http import HttpRequest, HttpResponse

from .config import get_settings

# Try to import prometheus_client for native integration
try:
    import prometheus_client
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    HAS_PROMETHEUS_CLIENT = True
except ImportError:
    HAS_PROMETHEUS_CLIENT = False


class SimpleCounter:
    """Simple counter for Prometheus text format output (no prometheus_client)."""

    def __init__(self, name: str, help_text: str, labels: Optional[List[str]] = None):
        self.name = name
        self.help_text = help_text
        self._label_names = labels or []
        self._values: Dict[Tuple[str, ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def labels(self, **kwargs: str) -> "_LabeledSimpleMetric":
        """Return a child counter with the given label values."""
        key = tuple(kwargs.get(label, "") for label in self._label_names)
        return _LabeledSimpleMetric(self, key)

    def inc(self, amount: float = 1.0) -> None:
        """Increment the counter (no labels)."""
        with self._lock:
            self._values[()] += amount

    def _inc_labeled(self, key: Tuple[str, ...], amount: float = 1.0) -> None:
        with self._lock:
            self._values[key] += amount

    def collect(self) -> str:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} counter"]
        with self._lock:
            for key, value in sorted(self._values.items()):
                if key and self._label_names:
                    label_str = ",".join(
                        f'{name}="{val}"' for name, val in zip(self._label_names, key)
                    )
                    lines.append(f"{self.name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{self.name} {value}")
        return "\n".join(lines)


class SimpleGauge:
    """Simple gauge for Prometheus text format output."""

    def __init__(self, name: str, help_text: str, labels: Optional[List[str]] = None):
        self.name = name
        self.help_text = help_text
        self._label_names = labels or []
        self._values: Dict[Tuple[str, ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def labels(self, **kwargs: str) -> "_LabeledSimpleMetric":
        key = tuple(kwargs.get(label, "") for label in self._label_names)
        return _LabeledSimpleMetric(self, key)

    def set(self, value: float) -> None:
        with self._lock:
            self._values[()] = value

    def _set_labeled(self, key: Tuple[str, ...], value: float) -> None:
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._values[()] += amount

    def _inc_labeled(self, key: Tuple[str, ...], amount: float = 1.0) -> None:
        with self._lock:
            self._values[key] += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._values[()] -= amount

    def _dec_labeled(self, key: Tuple[str, ...], amount: float = 1.0) -> None:
        with self._lock:
            self._values[key] -= amount

    def collect(self) -> str:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} gauge"]
        with self._lock:
            for key, value in sorted(self._values.items()):
                if key and self._label_names:
                    label_str = ",".join(
                        f'{name}="{val}"' for name, val in zip(self._label_names, key)
                    )
                    lines.append(f"{self.name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{self.name} {value}")
        return "\n".join(lines)


class SimpleHistogram:
    """Simple histogram for Prometheus text format output."""

    DEFAULT_BUCKETS = (
        0.001,
        0.005,
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        2.5,
        5.0,
        7.5,
        10.0,
        float("inf"),
    )

    def __init__(
        self,
        name: str,
        help_text: str,
        labels: Optional[List[str]] = None,
        buckets: Optional[Tuple[float, ...]] = None,
    ):
        self.name = name
        self.help_text = help_text
        self._label_names = labels or []
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._observations: Dict[Tuple[str, ...], List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def labels(self, **kwargs: str) -> "_LabeledSimpleMetric":
        key = tuple(kwargs.get(label, "") for label in self._label_names)
        return _LabeledSimpleMetric(self, key)

    def observe(self, value: float) -> None:
        with self._lock:
            self._observations[()].append(value)

    def _observe_labeled(self, key: Tuple[str, ...], value: float) -> None:
        with self._lock:
            self._observations[key].append(value)

    def collect(self) -> str:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            for key, observations in sorted(self._observations.items()):
                label_prefix = ""
                if key and self._label_names:
                    label_prefix = ",".join(
                        f'{name}="{val}"' for name, val in zip(self._label_names, key)
                    )

                total = sum(observations)
                count = len(observations)

                for bucket_bound in self.buckets:
                    bucket_count = sum(1 for o in observations if o <= bucket_bound)
                    le_str = (
                        "+Inf" if bucket_bound == float("inf") else str(bucket_bound)
                    )
                    if label_prefix:
                        lines.append(
                            f'{self.name}_bucket{{{label_prefix},le="{le_str}"}} {bucket_count}'
                        )
                    else:
                        lines.append(
                            f'{self.name}_bucket{{le="{le_str}"}} {bucket_count}'
                        )

                if label_prefix:
                    lines.append(f"{self.name}_sum{{{label_prefix}}} {total}")
                    lines.append(f"{self.name}_count{{{label_prefix}}} {count}")
                else:
                    lines.append(f"{self.name}_sum {total}")
                    lines.append(f"{self.name}_count {count}")

        return "\n".join(lines)


class _LabeledSimpleMetric:
    """Helper for labeled metric operations on simple metrics."""

    def __init__(self, parent: Any, key: Tuple[str, ...]):
        self._parent = parent
        self._key = key

    def inc(self, amount: float = 1.0) -> None:
        self._parent._inc_labeled(self._key, amount)

    def dec(self, amount: float = 1.0) -> None:
        self._parent._dec_labeled(self._key, amount)

    def set(self, value: float) -> None:
        self._parent._set_labeled(self._key, value)

    def observe(self, value: float) -> None:
        self._parent._observe_labeled(self._key, value)


def _get_prometheus_config() -> Dict[str, Any]:
    """Get Prometheus configuration from Django settings."""
    from django.conf import settings as django_settings

    config = getattr(django_settings, "RATELIMIT_PROMETHEUS", {})
    return {
        "enabled": config.get("ENABLED", True),
        "prefix": config.get("PREFIX", "django_ratelimit"),
    }


class PrometheusMetrics:
    """
    Prometheus metrics for rate limiting.

    Creates and manages Prometheus metrics. Uses the prometheus_client
    library if available, otherwise falls back to simple built-in
    implementations that output standard Prometheus text format.
    """

    _instance: Optional["PrometheusMetrics"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "PrometheusMetrics":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def _initialize(self, prefix: str = "django_ratelimit") -> None:
        """Initialize metrics with the given prefix."""
        if self._initialized:
            return

        self._prefix = prefix

        if HAS_PROMETHEUS_CLIENT:
            self._registry = CollectorRegistry()
            self._init_prometheus_client_metrics()
        else:
            self._init_simple_metrics()

        self._initialized = True

    def _init_prometheus_client_metrics(self) -> None:
        """Initialize metrics using prometheus_client library."""
        p = self._prefix

        self.requests_total = Counter(
            f"{p}_requests_total",
            "Total number of rate limit checks",
            ["key", "backend", "result"],
            registry=self._registry,
        )

        self.requests_denied_total = Counter(
            f"{p}_requests_denied_total",
            "Total number of denied requests",
            ["key", "backend"],
            registry=self._registry,
        )

        self.request_duration_seconds = Histogram(
            f"{p}_request_duration_seconds",
            "Rate limit check duration in seconds",
            ["backend"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
            registry=self._registry,
        )

        self.active_keys = Gauge(
            f"{p}_active_keys",
            "Number of active rate limit keys",
            ["backend"],
            registry=self._registry,
        )

        self.backend_healthy = Gauge(
            f"{p}_backend_healthy",
            "Whether the backend is healthy (1) or not (0)",
            ["backend"],
            registry=self._registry,
        )

        self.circuit_breaker_state = Gauge(
            f"{p}_circuit_breaker_state",
            "Circuit breaker state: 0=closed, 1=half-open, 2=open",
            ["backend"],
            registry=self._registry,
        )

    def _init_simple_metrics(self) -> None:
        """Initialize simple built-in metrics (no prometheus_client)."""
        p = self._prefix

        self.requests_total = SimpleCounter(
            f"{p}_requests_total",
            "Total number of rate limit checks",
            labels=["key", "backend", "result"],
        )

        self.requests_denied_total = SimpleCounter(
            f"{p}_requests_denied_total",
            "Total number of denied requests",
            labels=["key", "backend"],
        )

        self.request_duration_seconds = SimpleHistogram(
            f"{p}_request_duration_seconds",
            "Rate limit check duration in seconds",
            labels=["backend"],
            buckets=(
                0.001,
                0.005,
                0.01,
                0.025,
                0.05,
                0.1,
                0.25,
                0.5,
                1.0,
                float("inf"),
            ),
        )

        self.active_keys = SimpleGauge(
            f"{p}_active_keys",
            "Number of active rate limit keys",
            labels=["backend"],
        )

        self.backend_healthy = SimpleGauge(
            f"{p}_backend_healthy",
            "Whether the backend is healthy (1) or not (0)",
            labels=["backend"],
        )

        self.circuit_breaker_state = SimpleGauge(
            f"{p}_circuit_breaker_state",
            "Circuit breaker state: 0=closed, 1=half-open, 2=open",
            labels=["backend"],
        )

    def record_request(
        self,
        key: str,
        backend: str,
        allowed: bool,
        duration_seconds: float,
    ) -> None:
        """
        Record a rate limit check.

        Args:
            key: The rate limit key.
            backend: The backend name.
            allowed: Whether the request was allowed.
            duration_seconds: Time taken for the check in seconds.
        """
        if not self._initialized:
            return

        result = "allowed" if allowed else "denied"
        self.requests_total.labels(key=key, backend=backend, result=result).inc()

        if not allowed:
            self.requests_denied_total.labels(key=key, backend=backend).inc()

        self.request_duration_seconds.labels(backend=backend).observe(duration_seconds)

    def set_backend_health(self, backend: str, healthy: bool) -> None:
        """Record backend health status."""
        if not self._initialized:
            return
        self.backend_healthy.labels(backend=backend).set(1.0 if healthy else 0.0)

    def set_circuit_breaker_state(self, backend: str, state: str) -> None:
        """Record circuit breaker state."""
        if not self._initialized:
            return
        state_map = {"closed": 0, "half-open": 1, "open": 2}
        self.circuit_breaker_state.labels(backend=backend).set(state_map.get(state, 0))

    def set_active_keys(self, backend: str, count: int) -> None:
        """Record the number of active rate limit keys."""
        if not self._initialized:
            return
        self.active_keys.labels(backend=backend).set(float(count))

    def generate_metrics(self) -> str:
        """
        Generate metrics output in Prometheus text exposition format.

        Returns:
            Prometheus-formatted metrics string.
        """
        if not self._initialized:
            return ""

        if HAS_PROMETHEUS_CLIENT:
            return generate_latest(self._registry).decode("utf-8")

        # Collect from simple metrics
        parts = []
        for metric in [
            self.requests_total,
            self.requests_denied_total,
            self.request_duration_seconds,
            self.active_keys,
            self.backend_healthy,
            self.circuit_breaker_state,
        ]:
            collected = metric.collect()
            if collected:
                parts.append(collected)

        return "\n\n".join(parts) + "\n"

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        with cls._lock:
            cls._instance = None


def get_prometheus_metrics() -> PrometheusMetrics:
    """
    Get or create the singleton PrometheusMetrics instance.

    Returns:
        The PrometheusMetrics singleton.
    """
    instance = PrometheusMetrics()
    if not instance._initialized:
        config = _get_prometheus_config()
        instance._initialize(prefix=config["prefix"])
    return instance


def prometheus_metrics_view(request: HttpRequest) -> HttpResponse:
    """
    Django view that exposes Prometheus metrics.

    Returns metrics in Prometheus text exposition format.
    Can be added to urlpatterns:

        from django_smart_ratelimit.prometheus import prometheus_metrics_view

        urlpatterns = [
            path('metrics/', prometheus_metrics_view),
        ]
    """
    config = _get_prometheus_config()
    if not config["enabled"]:
        return HttpResponse(
            "Prometheus metrics are disabled", status=404, content_type="text/plain"
        )

    metrics = get_prometheus_metrics()
    output = metrics.generate_metrics()

    content_type = "text/plain; version=0.0.4; charset=utf-8"
    return HttpResponse(output, content_type=content_type)


class PrometheusMetricsMiddleware:
    """
    Django middleware that collects Prometheus metrics for rate limiting.

    Automatically instruments rate limit checks made by the RateLimitMiddleware
    or @rate_limit decorator.

    Add to MIDDLEWARE in settings.py:
        MIDDLEWARE = [
            ...
            'django_smart_ratelimit.prometheus.PrometheusMetricsMiddleware',
        ]
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self.metrics = get_prometheus_metrics()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start_time = time.monotonic()

        response = self.get_response(request)

        duration = time.monotonic() - start_time

        # Check if rate limiting was applied (set by decorator/middleware)
        ratelimit_info = getattr(request, "ratelimit", None)
        if ratelimit_info:
            key = getattr(ratelimit_info, "key", "unknown")
            backend = getattr(ratelimit_info, "backend", "unknown")
            allowed = not getattr(ratelimit_info, "limited", False)
            self.metrics.record_request(
                key=key,
                backend=backend,
                allowed=allowed,
                duration_seconds=duration,
            )

        # Track 429 responses as denied even without ratelimit info
        if response.status_code == 429 and not ratelimit_info:
            self.metrics.record_request(
                key="unknown",
                backend="unknown",
                allowed=False,
                duration_seconds=duration,
            )

        return response
