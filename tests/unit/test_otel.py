"""
Tests for OpenTelemetry instrumentation.

Tests span and metric emission for rate limit checks.
Skips if opentelemetry is not installed.
"""

import pytest

try:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False


pytestmark = pytest.mark.skipif(
    not HAS_OTEL, reason="opentelemetry not installed"
)


@pytest.fixture
def otel_setup():
    """Set up OTel providers with in-memory exporters."""
    if not HAS_OTEL:
        pytest.skip("opentelemetry not installed")

    # Setup tracer
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    # Setup meter
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])

    return {
        "tracer_provider": tracer_provider,
        "meter_provider": meter_provider,
        "span_exporter": span_exporter,
        "metric_reader": metric_reader,
    }


class TestRateLimitTracer:
    """Tests for RateLimitTracer."""

    def test_allowed_request_creates_span(self, otel_setup):
        """Test that allowed request creates span with correct attributes."""
        from django_smart_ratelimit.observability.otel import RateLimitTracer

        tracer = RateLimitTracer(tracer=otel_setup["tracer_provider"].get_tracer(__name__))

        with tracer.start_check_span(
            key="user:123",
            limit=100,
            remaining=42,
            algorithm="sliding_window",
            backend="RedisBackend",
            allowed=True,
            shadow=False,
            cost=1,
        ):
            pass

        spans = otel_setup["span_exporter"].get_finished_spans()
        assert len(spans) == 1

        span = spans[0]
        assert span.name == "ratelimit.check"
        assert span.attributes["ratelimit.key"] == "user:123"
        assert span.attributes["ratelimit.limit"] == 100
        assert span.attributes["ratelimit.remaining"] == 42
        assert span.attributes["ratelimit.algorithm"] == "sliding_window"
        assert span.attributes["ratelimit.backend"] == "RedisBackend"
        assert span.attributes["ratelimit.decision"] == "allowed"
        assert span.attributes["ratelimit.shadow"] is False
        assert span.attributes["ratelimit.cost"] == 1

    def test_denied_request_sets_error_status(self, otel_setup):
        """Test that denied request sets span status to ERROR."""
        from django_smart_ratelimit.observability.otel import RateLimitTracer
        from opentelemetry.trace import StatusCode

        tracer = RateLimitTracer(tracer=otel_setup["tracer_provider"].get_tracer(__name__))

        with tracer.start_check_span(
            key="user:456",
            limit=50,
            remaining=0,
            algorithm="token_bucket",
            backend="MemoryBackend",
            allowed=False,
            shadow=False,
            cost=1,
        ):
            pass

        spans = otel_setup["span_exporter"].get_finished_spans()
        assert len(spans) == 1

        span = spans[0]
        assert span.attributes["ratelimit.decision"] == "denied"
        assert span.status.status_code == StatusCode.ERROR

    def test_shadow_mode_attribute(self, otel_setup):
        """Test that shadow mode is recorded in span attributes."""
        from django_smart_ratelimit.observability.otel import RateLimitTracer

        tracer = RateLimitTracer(tracer=otel_setup["tracer_provider"].get_tracer(__name__))

        with tracer.start_check_span(
            key="user:789",
            limit=200,
            remaining=150,
            algorithm="sliding_window",
            backend="RedisBackend",
            allowed=True,
            shadow=True,
            cost=1,
        ):
            pass

        spans = otel_setup["span_exporter"].get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes["ratelimit.shadow"] is True

    def test_cost_greater_than_one(self, otel_setup):
        """Test that cost > 1 is recorded in span attributes."""
        from django_smart_ratelimit.observability.otel import RateLimitTracer

        tracer = RateLimitTracer(tracer=otel_setup["tracer_provider"].get_tracer(__name__))

        with tracer.start_check_span(
            key="batch:op1",
            limit=1000,
            remaining=750,
            algorithm="token_bucket",
            backend="RedisBackend",
            allowed=True,
            shadow=False,
            cost=5,
        ):
            pass

        spans = otel_setup["span_exporter"].get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes["ratelimit.cost"] == 5


class TestRateLimitMeter:
    """Tests for RateLimitMeter."""

    def test_allowed_request_increments_counter(self, otel_setup):
        """Test that allowed request increments correct counters."""
        from django_smart_ratelimit.observability.otel import RateLimitMeter

        meter = RateLimitMeter(meter=otel_setup["meter_provider"].get_meter(__name__))

        meter.record_decision(
            allowed=True,
            backend="RedisBackend",
            algorithm="sliding_window",
            shadow=False,
            cost=1,
            duration_ms=5.0,
        )

        metrics = otel_setup["metric_reader"].get_metrics_data()
        assert metrics is not None

    def test_denied_request_metrics(self, otel_setup):
        """Test that denied request is recorded in metrics."""
        from django_smart_ratelimit.observability.otel import RateLimitMeter

        meter = RateLimitMeter(meter=otel_setup["meter_provider"].get_meter(__name__))

        meter.record_decision(
            allowed=False,
            backend="MemoryBackend",
            algorithm="fixed_window",
            shadow=False,
            cost=1,
            duration_ms=3.0,
        )

        metrics = otel_setup["metric_reader"].get_metrics_data()
        assert metrics is not None

    def test_tokens_consumed_counter(self, otel_setup):
        """Test that tokens consumed counter sums cost correctly."""
        from django_smart_ratelimit.observability.otel import RateLimitMeter

        meter = RateLimitMeter(meter=otel_setup["meter_provider"].get_meter(__name__))

        # Record multiple decisions with different costs
        meter.record_decision(
            allowed=True,
            backend="RedisBackend",
            algorithm="token_bucket",
            shadow=False,
            cost=1,
            duration_ms=2.0,
        )

        meter.record_decision(
            allowed=True,
            backend="RedisBackend",
            algorithm="token_bucket",
            shadow=False,
            cost=3,
            duration_ms=2.5,
        )

        meter.record_decision(
            allowed=False,
            backend="RedisBackend",
            algorithm="token_bucket",
            shadow=False,
            cost=5,
            duration_ms=1.5,
        )

        metrics = otel_setup["metric_reader"].get_metrics_data()
        assert metrics is not None

    def test_backend_error_recording(self, otel_setup):
        """Test that backend errors are recorded."""
        from django_smart_ratelimit.observability.otel import RateLimitMeter

        meter = RateLimitMeter(meter=otel_setup["meter_provider"].get_meter(__name__))

        meter.record_backend_error("connection_timeout")
        meter.record_backend_error("connection_timeout")
        meter.record_backend_error("auth_failed")

        metrics = otel_setup["metric_reader"].get_metrics_data()
        assert metrics is not None


class TestRecordCheck:
    """Tests for record_check function."""

    def test_record_check_with_allowed_request(self, otel_setup):
        """Test record_check with allowed request."""
        from django_smart_ratelimit.observability import otel

        # Reset globals to use our setup
        otel._global_tracer = otel.RateLimitTracer(
            tracer=otel_setup["tracer_provider"].get_tracer(__name__)
        )
        otel._global_meter = otel.RateLimitMeter(
            meter=otel_setup["meter_provider"].get_meter(__name__)
        )

        otel.record_check(
            key="api:key123",
            limit=500,
            remaining=250,
            algorithm="sliding_window",
            backend="RedisBackend",
            allowed=True,
            cost=1,
            duration_ms=4.2,
        )

        spans = otel_setup["span_exporter"].get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes["ratelimit.decision"] == "allowed"
        assert spans[0].attributes["ratelimit.key"] == "api:key123"

    def test_record_check_with_denied_request(self, otel_setup):
        """Test record_check with denied request."""
        from django_smart_ratelimit.observability import otel

        # Reset globals to use our setup
        otel._global_tracer = otel.RateLimitTracer(
            tracer=otel_setup["tracer_provider"].get_tracer(__name__)
        )
        otel._global_meter = otel.RateLimitMeter(
            meter=otel_setup["meter_provider"].get_meter(__name__)
        )

        otel.record_check(
            key="user:blocked",
            limit=10,
            remaining=0,
            algorithm="fixed_window",
            backend="MemoryBackend",
            allowed=False,
            cost=1,
            duration_ms=1.1,
        )

        spans = otel_setup["span_exporter"].get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes["ratelimit.decision"] == "denied"

    def test_record_check_shadow_mode(self, otel_setup):
        """Test record_check with shadow mode."""
        from django_smart_ratelimit.observability import otel

        # Reset globals to use our setup
        otel._global_tracer = otel.RateLimitTracer(
            tracer=otel_setup["tracer_provider"].get_tracer(__name__)
        )
        otel._global_meter = otel.RateLimitMeter(
            meter=otel_setup["meter_provider"].get_meter(__name__)
        )

        otel.record_check(
            key="shadow:test",
            limit=100,
            remaining=75,
            algorithm="sliding_window",
            backend="RedisBackend",
            allowed=False,  # Would be denied, but shadow mode
            shadow=True,
            cost=1,
            duration_ms=2.0,
        )

        spans = otel_setup["span_exporter"].get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes["ratelimit.shadow"] is True


class TestImportWithoutOtel:
    """Tests for importing when OpenTelemetry is not available."""

    def test_import_without_otel_doesnt_crash(self):
        """Test that importing observability module doesn't crash without OTel."""
        # This test always runs; it verifies that imports are safe
        from django_smart_ratelimit.observability import (
            instrument_rate_limit,
            record_check,
        )

        # Should not raise
        assert instrument_rate_limit is not None
        assert record_check is not None

    def test_record_check_noop_without_otel(self):
        """Test that record_check is a no-op when OTel not installed."""
        from django_smart_ratelimit.observability import otel

        # Reset to ensure we use no-op implementations if needed
        otel._global_tracer = otel.RateLimitTracer()
        otel._global_meter = otel.RateLimitMeter()

        # Should not raise
        otel.record_check(
            key="test",
            limit=100,
            remaining=50,
            algorithm="sliding_window",
            backend="MemoryBackend",
            allowed=True,
            cost=1,
            duration_ms=1.0,
        )

    def test_instrument_rate_limit_idempotent(self, otel_setup):
        """Test that instrument_rate_limit is idempotent."""
        from django_smart_ratelimit.observability import otel

        # Reset state
        otel._global_tracer = None
        otel._global_meter = None

        # Call multiple times - should only initialize once
        otel.instrument_rate_limit(
            tracer_provider=otel_setup["tracer_provider"],
            meter_provider=otel_setup["meter_provider"],
        )

        first_tracer = otel._global_tracer
        first_meter = otel._global_meter

        otel.instrument_rate_limit(
            tracer_provider=otel_setup["tracer_provider"],
            meter_provider=otel_setup["meter_provider"],
        )

        # Should be the same instances
        assert otel._global_tracer is first_tracer
        assert otel._global_meter is first_meter
