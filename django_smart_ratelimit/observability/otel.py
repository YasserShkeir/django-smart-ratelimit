"""
OpenTelemetry instrumentation for rate limiting.

Provides span and metrics instrumentation for rate limit checks. Works with or
without opentelemetry libraries installed by providing no-op fallbacks.

Spans:
    - ratelimit.check: Created for each rate limit check with attributes:
        - ratelimit.key: The rate limit key
        - ratelimit.limit: Configured limit
        - ratelimit.remaining: Remaining count after request
        - ratelimit.algorithm: Algorithm name (sliding_window, token_bucket, etc.)
        - ratelimit.backend: Backend class name
        - ratelimit.decision: "allowed" or "denied"
        - ratelimit.shadow: True if shadow mode
        - ratelimit.cost: Tokens consumed (default 1)

Metrics:
    - ratelimit.requests.total (Counter): Total checks with attributes:
        decision (allowed/denied), backend, algorithm, shadow
    - ratelimit.tokens.consumed (Counter): Sum of tokens consumed with attributes:
        backend, algorithm
    - ratelimit.check.duration_ms (Histogram): Check duration in milliseconds
        with attributes: backend, algorithm
    - ratelimit.backend.errors (UpDownCounter): Backend errors with attribute:
        error_type

Example:
    from django_smart_ratelimit.observability import (
        instrument_rate_limit,
        record_check,
    )

    # Initialize at app startup
    instrument_rate_limit()

    # Record a rate limit decision
    record_check(
        key="user:123",
        limit=100,
        remaining=42,
        algorithm="sliding_window",
        backend="RedisBackend",
        allowed=True,
        cost=1,
        duration_ms=2.5,
    )
"""

import threading
from typing import Any, Dict, Optional

# Try to import OpenTelemetry
try:
    from opentelemetry import metrics, trace
    from opentelemetry.metrics import Meter
    from opentelemetry.trace import Status, StatusCode, Tracer

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False
    Tracer = Any
    Meter = Any


# Global tracer and meter (set by instrument_rate_limit)
_global_tracer: Optional["RateLimitTracer"] = None
_global_meter: Optional["RateLimitMeter"] = None
_lock = threading.Lock()


class NoOpTracer:
    """No-op tracer when OpenTelemetry is not installed."""

    def start_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        record_exception: bool = False,
        set_status_on_exception: bool = True,
    ) -> "NoOpSpanContext":
        """Return a no-op span context."""
        return NoOpSpanContext()


class NoOpSpanContext:
    """No-op span context manager."""

    def __enter__(self) -> "NoOpSpanContext":
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""

    def set_attribute(self, key: str, value: Any) -> None:
        """No-op set_attribute."""

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        """No-op add_event."""

    def set_status(self, status: Any) -> None:
        """No-op set_status."""


class NoOpMeter:
    """No-op meter when OpenTelemetry is not installed."""

    def create_counter(self, name: str, description: str = "") -> "NoOpCounter":
        """Create a no-op counter."""
        return NoOpCounter()

    def create_histogram(self, name: str, description: str = "") -> "NoOpHistogram":
        """Create a no-op histogram."""
        return NoOpHistogram()

    def create_up_down_counter(
        self, name: str, description: str = ""
    ) -> "NoOpUpDownCounter":
        """Create a no-op up-down counter."""
        return NoOpUpDownCounter()


class NoOpCounter:
    """No-op counter."""

    def add(self, value: float, attributes: Optional[Dict[str, Any]] = None) -> None:
        """No-op add."""


class NoOpHistogram:
    """No-op histogram."""

    def record(self, value: float, attributes: Optional[Dict[str, Any]] = None) -> None:
        """No-op record."""


class NoOpUpDownCounter:
    """No-op up-down counter."""

    def add(self, value: float, attributes: Optional[Dict[str, Any]] = None) -> None:
        """No-op add."""


class RateLimitTracer:
    """
    OpenTelemetry tracer for rate limiting operations.

    Wraps OTel's Tracer and provides rate-limit-specific span creation.
    Falls back to no-op implementations if OpenTelemetry is not installed.
    """

    def __init__(self, tracer: Optional[Tracer] = None) -> None:
        """
        Initialize RateLimitTracer.

        Args:
            tracer: Optional OTel Tracer. If None and OTel is available,
                   gets the default tracer from trace provider.
        """
        if HAS_OTEL and tracer is None:
            tracer = trace.get_tracer(__name__)

        self._tracer: Any = tracer or NoOpTracer()
        self._has_otel = HAS_OTEL

    def start_check_span(
        self,
        key: str,
        limit: int,
        remaining: int,
        algorithm: str,
        backend: str,
        allowed: bool,
        shadow: bool = False,
        cost: int = 1,
    ) -> Any:
        """
        Start a span for a rate limit check.

        Args:
            key: Rate limit key
            limit: Configured limit
            remaining: Remaining count after this check
            algorithm: Algorithm name
            backend: Backend class name
            allowed: Whether request was allowed
            shadow: Whether in shadow mode
            cost: Tokens consumed

        Returns:
            Span context manager (yields the span)
        """
        if self._has_otel:
            span = self._tracer.start_span(
                "ratelimit.check",
                kind=trace.SpanKind.INTERNAL,
            )
            span.set_attribute("ratelimit.key", key)
            span.set_attribute("ratelimit.limit", limit)
            span.set_attribute("ratelimit.remaining", remaining)
            span.set_attribute("ratelimit.algorithm", algorithm)
            span.set_attribute("ratelimit.backend", backend)
            span.set_attribute("ratelimit.decision", "allowed" if allowed else "denied")
            span.set_attribute("ratelimit.shadow", shadow)
            span.set_attribute("ratelimit.cost", cost)

            if not allowed:
                span.add_event("ratelimit.denied", {"ratelimit.key": key})
                span.set_status(Status(StatusCode.ERROR))

            return _SpanContextManager(span)
        else:
            return NoOpSpanContext()


class _SpanContextManager:
    """Context manager for OTel spans."""

    def __init__(self, span: Any) -> None:
        """Initialize with span."""
        self._span = span

    def __enter__(self) -> Any:
        """Enter context."""
        if hasattr(self._span, "__enter__"):
            return self._span.__enter__()
        return self._span

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context."""
        if hasattr(self._span, "__exit__"):
            self._span.__exit__(exc_type, exc_val, exc_tb)
        elif hasattr(self._span, "end"):
            self._span.end()


class RateLimitMeter:
    """
    OpenTelemetry meter for rate limiting metrics.

    Provides counters, histograms, and up-down counters for rate limit operations.
    Falls back to no-op implementations if OpenTelemetry is not installed.
    """

    def __init__(self, meter: Optional[Meter] = None) -> None:
        """
        Initialize RateLimitMeter.

        Args:
            meter: Optional OTel Meter. If None and OTel is available,
                  gets the default meter from metric provider.
        """
        if HAS_OTEL and meter is None:
            meter = metrics.get_meter(__name__)

        self._meter: Any = meter or NoOpMeter()
        self._has_otel = HAS_OTEL

        # Initialize metrics
        self._requests_total = self._meter.create_counter(
            "ratelimit.requests.total",
            "Total number of rate limit checks",
        )
        self._tokens_consumed = self._meter.create_counter(
            "ratelimit.tokens.consumed",
            "Total tokens consumed across all rate limit checks",
        )
        self._check_duration = self._meter.create_histogram(
            "ratelimit.check.duration_ms",
            "Duration of rate limit checks in milliseconds",
        )
        self._backend_errors = self._meter.create_up_down_counter(
            "ratelimit.backend.errors",
            "Number of backend errors",
        )

    def record_decision(
        self,
        allowed: bool,
        backend: str,
        algorithm: str,
        shadow: bool = False,
        cost: int = 1,
        duration_ms: float = 0.0,
    ) -> None:
        """
        Record a rate limit decision with metrics.

        Args:
            allowed: Whether request was allowed
            backend: Backend name
            algorithm: Algorithm name
            shadow: Whether in shadow mode
            cost: Tokens consumed
            duration_ms: Check duration in milliseconds
        """
        decision = "allowed" if allowed else "denied"
        attrs_decision = {
            "decision": decision,
            "backend": backend,
            "algorithm": algorithm,
            "shadow": shadow,
        }

        # Record request total
        self._requests_total.add(1, attributes=attrs_decision)

        # Record tokens consumed
        attrs_tokens = {
            "backend": backend,
            "algorithm": algorithm,
        }
        self._tokens_consumed.add(cost, attributes=attrs_tokens)

        # Record check duration
        attrs_duration = {
            "backend": backend,
            "algorithm": algorithm,
        }
        self._check_duration.record(duration_ms, attributes=attrs_duration)

    def record_backend_error(self, error_type: str) -> None:
        """
        Record a backend error.

        Args:
            error_type: Type of error (e.g., "connection", "timeout")
        """
        self._backend_errors.add(1, attributes={"error_type": error_type})


def record_check(
    *,
    key: str,
    limit: int,
    remaining: int,
    algorithm: str,
    backend: str,
    allowed: bool,
    shadow: bool = False,
    cost: int = 1,
    duration_ms: float = 0.0,
) -> None:
    """
    Record a rate limit check with OTel spans and metrics.

    This is the primary public API for recording rate limit decisions.
    Should be called after a rate limit check completes.

    Args:
        key: The rate limit key
        limit: Configured limit
        remaining: Remaining count after this check
        algorithm: Algorithm name (sliding_window, token_bucket, etc.)
        backend: Backend class name
        allowed: Whether request was allowed
        shadow: Whether in shadow mode (default: False)
        cost: Tokens consumed (default: 1)
        duration_ms: Check duration in milliseconds (default: 0.0)

    Example:
        from django_smart_ratelimit.observability import record_check

        allowed = rate_limit_check(...)
        record_check(
            key="user:123",
            limit=100,
            remaining=42,
            algorithm="sliding_window",
            backend="RedisBackend",
            allowed=allowed,
            cost=1,
            duration_ms=2.5,
        )
    """
    # Use global instances if available (read-only module-level access).
    tracer = _global_tracer or RateLimitTracer()
    meter = _global_meter or RateLimitMeter()

    # Record span
    with tracer.start_check_span(
        key=key,
        limit=limit,
        remaining=remaining,
        algorithm=algorithm,
        backend=backend,
        allowed=allowed,
        shadow=shadow,
        cost=cost,
    ):
        # Record metrics
        meter.record_decision(
            allowed=allowed,
            backend=backend,
            algorithm=algorithm,
            shadow=shadow,
            cost=cost,
            duration_ms=duration_ms,
        )


def record_rate_limit_decision(
    *,
    key: str,
    limit: int,
    remaining: int,
    algorithm: str,
    backend: str,
    allowed: bool,
    shadow: bool = False,
    cost: int = 1,
    duration_ms: float = 0.0,
) -> None:
    """
    Alias for record_check. Records a rate limit decision with spans and metrics.

    See record_check for parameter documentation.
    """
    record_check(
        key=key,
        limit=limit,
        remaining=remaining,
        algorithm=algorithm,
        backend=backend,
        allowed=allowed,
        shadow=shadow,
        cost=cost,
        duration_ms=duration_ms,
    )


def instrument_rate_limit(
    tracer_provider: Optional[Any] = None,
    meter_provider: Optional[Any] = None,
) -> None:
    """
    Initialize OpenTelemetry instrumentation for rate limiting.

    Should be called once at application startup to enable OTel spans and metrics.
    Safe to call multiple times (idempotent).

    Args:
        tracer_provider: Optional TracerProvider. If None, uses global tracer provider.
        meter_provider: Optional MeterProvider. If None, uses global meter provider.

    Example:
        In Django AppConfig.ready():

            from django_smart_ratelimit.observability import instrument_rate_limit

            class MyAppConfig(AppConfig):
                name = 'myapp'

                def ready(self):
                    instrument_rate_limit()

        Or with custom providers:

            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.metrics import MeterProvider

            tp = TracerProvider()
            mp = MeterProvider()

            instrument_rate_limit(tracer_provider=tp, meter_provider=mp)
    """
    global _global_tracer, _global_meter

    if not HAS_OTEL:
        # OpenTelemetry not installed, use no-ops
        if _global_tracer is None:
            _global_tracer = RateLimitTracer()
        if _global_meter is None:
            _global_meter = RateLimitMeter()
        return

    with _lock:
        if _global_tracer is None:
            if tracer_provider is None:
                tracer = trace.get_tracer(__name__)
            else:
                tracer = tracer_provider.get_tracer(__name__)
            _global_tracer = RateLimitTracer(tracer=tracer)

        if _global_meter is None:
            if meter_provider is None:
                meter = metrics.get_meter(__name__)
            else:
                meter = meter_provider.get_meter(__name__)
            _global_meter = RateLimitMeter(meter=meter)
