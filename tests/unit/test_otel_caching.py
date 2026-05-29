"""
Tests for OTel fallback meter/tracer caching in record_check.

These tests run regardless of whether opentelemetry is installed: the bug being
guarded against (recreating the meter and its instruments on every call when
instrument_rate_limit() was never invoked) also manifests with the no-op
fallback implementations.
"""

from unittest.mock import patch

import pytest

from django_smart_ratelimit.observability import otel


@pytest.fixture
def reset_otel_state():
    """Reset module-level OTel state and restore it after the test."""
    saved = (
        otel._global_tracer,
        otel._global_meter,
        otel._fallback_tracer,
        otel._fallback_meter,
    )
    # Simulate instrument_rate_limit() never having been called.
    otel._global_tracer = None
    otel._global_meter = None
    otel._fallback_tracer = None
    otel._fallback_meter = None
    try:
        yield
    finally:
        (
            otel._global_tracer,
            otel._global_meter,
            otel._fallback_tracer,
            otel._fallback_meter,
        ) = saved


_CHECK_KWARGS = dict(
    key="test",
    limit=100,
    remaining=50,
    algorithm="sliding_window",
    backend="MemoryBackend",
    allowed=True,
    cost=1,
    duration_ms=1.0,
)


def test_record_check_constructs_meter_once(reset_otel_state):
    """record_check must construct the fallback meter only once."""
    with patch.object(otel, "RateLimitMeter", wraps=otel.RateLimitMeter) as meter_cls:
        otel.record_check(**_CHECK_KWARGS)
        otel.record_check(**_CHECK_KWARGS)
        otel.record_check(**_CHECK_KWARGS)

        # The meter (and its 4 instruments) must be constructed only once.
        assert meter_cls.call_count == 1


def test_record_check_reuses_same_meter_instance(reset_otel_state):
    """Repeated record_check calls must reuse the same cached meter instance."""
    otel.record_check(**_CHECK_KWARGS)
    first_meter = otel._fallback_meter
    assert first_meter is not None

    otel.record_check(**_CHECK_KWARGS)
    otel.record_check(**_CHECK_KWARGS)

    assert otel._fallback_meter is first_meter


def test_record_check_prefers_global_meter(reset_otel_state):
    """record_check must prefer the global meter set by instrument_rate_limit."""
    global_meter = otel.RateLimitMeter()
    otel._global_meter = global_meter
    otel._global_tracer = otel.RateLimitTracer()

    tracer, meter = otel._get_tracer_and_meter()

    assert meter is global_meter
    # Fallbacks should not be created when globals are present.
    assert otel._fallback_meter is None
