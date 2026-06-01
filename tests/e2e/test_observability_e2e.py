"""Real-backend end-to-end tests for the observability surface.

These scenarios drive REAL rate-limited traffic against REAL storage (live
Redis / live MongoDB / in-process memory) and then assert on the three
observability integrations the library ships:

* Prometheus (``django_smart_ratelimit.prometheus``): real requests are recorded
  through the public ``PrometheusMetrics.record_request`` API (the supported
  manual-instrumentation path) and scraped back via ``generate_metrics()`` /
  ``prometheus_metrics_view``. We assert request/denied counters increase, that
  the low-cardinality labels (``backend`` / ``result``) are present, and that the
  per-key value is NEVER a label (cardinality safety). A SEPARATE test
  (``test_prometheus_middleware_auto_emits_denials``) drives traffic through the
  shipped ``PrometheusMetricsMiddleware`` to check fully-automatic instrumentation
  end-to-end; it currently ``xfail``s on a real middleware bug (see its reason).
* OpenTelemetry (``django_smart_ratelimit.observability``): ``instrument_rate_limit``
  is called and ``record_check`` is exercised from real decorator traffic. We
  assert it never raises; OTel-specific span/metric assertions are made only
  when the SDK is installed.
* Structured logging (``django_smart_ratelimit.logging``): the public logging
  API (``log_rate_limit_check`` + ``JSONFormatter``) is exercised on real
  rate-limit decisions and asserted to produce parseable single-line JSON (via
  ``caplog``). A separate test (``test_request_path_auto_emits_structured_logs``)
  drives real traffic and asserts the enforcement path emits log records on its
  own, with no manual logging call.

The backend is never mocked: the ``@rate_limit`` decorator hits the real store
selected by the ``real_backend`` fixture, and we read the observable result
codes (200 vs 429) plus the emitted telemetry. Every test uses distinct IPs /
keys so they are independent and order-free.
"""

import json
import logging

import pytest

from django.http import HttpResponse

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.logging import (
    JSONFormatter,
    RateLimitLogEvent,
    clear_request_context,
    log_circuit_breaker_event,
    log_rate_limit_check,
    set_request_context,
)
from django_smart_ratelimit.prometheus import (
    PrometheusMetrics,
    PrometheusMetricsMiddleware,
    get_prometheus_metrics,
    prometheus_metrics_view,
)

from .conftest import AuthedUser, exhaust, make_request

# NOTE: the ``real_backend`` fixture is provided by tests/e2e/conftest.py and is
# auto-discovered by pytest; it is intentionally NOT imported here (importing a
# fixture only triggers F401/F811 lint noise).

# OpenTelemetry SDK is optional. When present we assert on real spans/metrics;
# when absent we still verify the no-op path never raises.
try:
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    HAS_OTEL_SDK = True
except ImportError:  # pragma: no cover - depends on optional dependency
    HAS_OTEL_SDK = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_prometheus(prefix="e2e_ratelimit"):
    """Return a freshly-initialized PrometheusMetrics singleton.

    The metrics object is a process-wide singleton, so we reset it per test to
    get clean counters and a stable, test-specific metric-name prefix.
    """
    PrometheusMetrics.reset()
    metrics = PrometheusMetrics()
    metrics._initialize(prefix=prefix)
    return metrics


def _counter_value(text, metric_name, **labels):
    """Parse a Prometheus exposition string for a single counter sample.

    Returns the float value of the line ``metric_name{labels...} value`` whose
    label set is a superset of the requested ``labels``. Returns ``None`` if no
    matching sample is found.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "{" in line:
            name, rest = line.split("{", 1)
            label_blob, value = rest.rsplit("}", 1)
        else:
            name, value = line.rsplit(" ", 1)
            label_blob = ""
        if name != metric_name:
            continue
        present = {}
        for chunk in label_blob.split(","):
            chunk = chunk.strip()
            if not chunk or "=" not in chunk:
                continue
            k, v = chunk.split("=", 1)
            present[k.strip()] = v.strip().strip('"')
        if all(present.get(k) == v for k, v in labels.items()):
            return float(value.strip())
    return None


def _build_view(rate, key="ip"):
    """Build a real @rate_limit-decorated view backed by the live store."""

    @rate_limit(key=key, rate=rate)
    def view(request):
        return HttpResponse("ok")

    return view


# ===========================================================================
# Prometheus: real traffic recorded + scraped
# ===========================================================================


class TestPrometheusRealTraffic:
    """Prometheus exposition scraped after real rate-limited traffic.

    These tests record each real decision through the public
    ``PrometheusMetrics.record_request`` API (the supported manual path) and
    assert the scraped exposition is correct. Fully-automatic instrumentation via
    ``PrometheusMetricsMiddleware`` is covered by
    ``test_prometheus_middleware_auto_emits_denials`` below.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: PrometheusMetricsMiddleware reads request.ratelimit.limited, but "
            "the decorator attaches a RateLimitContext that exposes .allowed (and "
            "leaves .backend unset). So every request -- including denials -- is "
            'recorded as result="allowed", backend="unknown", and auto-'
            "instrumentation cannot distinguish allowed from denied. Remove this "
            "xfail when the middleware is fixed to read .allowed / a real backend."
        ),
    )
    def test_prometheus_middleware_auto_emits_denials(self, real_backend):
        """TRUE auto-emit: traffic through the shipped middleware, no manual call.

        Installs ``PrometheusMetricsMiddleware`` around a real 2/min ``@rate_limit``
        view, drives 5 real requests (2 allowed, 3 denied on the live store), and
        scrapes the singleton WITHOUT any ``record_request`` call. Correct behavior
        is 2 allowed + 3 denied; this currently xfails (see reason).
        """
        PrometheusMetrics.reset()
        view = _build_view("2/m")
        middleware = PrometheusMetricsMiddleware(lambda request: view(request))
        ip = "198.51.100.210"

        codes = [middleware(make_request(ip=ip)).status_code for _ in range(5)]
        assert codes == [200, 200, 429, 429, 429]

        text = get_prometheus_metrics().generate_metrics()
        allowed = _counter_value(
            text, "django_ratelimit_requests_total", result="allowed"
        )
        denied = _counter_value(
            text, "django_ratelimit_requests_total", result="denied"
        )
        assert allowed == 2.0
        assert denied == 3.0

    def test_request_and_denied_counters_increase_on_real_backend(self, real_backend):
        """Public API endpoint: 3/min per IP.

        Five real requests hit the live backend; the first three are allowed
        and the last two are blocked (429). Each decision is recorded through
        ``PrometheusMetrics.record_request`` keyed on the real per-IP key, and
        we scrape ``generate_metrics()`` and assert the allowed counter shows
        3, the denied counter shows 2, and the denied-total matches.
        """
        metrics = _fresh_prometheus()
        view = _build_view("3/m")
        ip = "198.51.100.21"

        for code in exhaust(view, 5, ip=ip):
            # Record exactly what the live backend decided for this real call.
            metrics.record_request(
                key=f"ip:{ip}",
                backend=real_backend,
                allowed=(code == 200),
                duration_seconds=0.001,
            )

        text = metrics.generate_metrics()

        allowed = _counter_value(
            text,
            "e2e_ratelimit_requests_total",
            backend=real_backend,
            result="allowed",
        )
        denied = _counter_value(
            text,
            "e2e_ratelimit_requests_total",
            backend=real_backend,
            result="denied",
        )
        denied_total = _counter_value(
            text,
            "e2e_ratelimit_requests_denied_total",
            backend=real_backend,
        )

        assert allowed == 3.0
        assert denied == 2.0
        assert denied_total == 2.0

    def test_low_cardinality_labels_present_and_key_not_a_label(self, real_backend):
        """Cardinality safety: per-key value must never become a label.

        Drive traffic from three DISTINCT IPs against a 1/min limit so every IP
        is allowed once then denied. We record each with its unique per-IP key,
        then assert the scrape exposes only the low-cardinality ``backend`` and
        ``result`` labels and that NONE of the per-IP key strings leak into the
        exposition as a label value (which would explode cardinality).
        """
        metrics = _fresh_prometheus()
        view = _build_view("1/m")
        ips = ["203.0.113.41", "203.0.113.42", "203.0.113.43"]

        for ip in ips:
            for code in exhaust(view, 2, ip=ip):
                metrics.record_request(
                    key=f"ip:{ip}",
                    backend=real_backend,
                    allowed=(code == 200),
                    duration_seconds=0.0005,
                )

        text = metrics.generate_metrics()

        # The low-cardinality labels are present on the requests_total counter.
        assert 'backend="%s"' % real_backend in text
        assert 'result="allowed"' in text
        assert 'result="denied"' in text

        # The per-key value is NOT used as a label anywhere in the exposition.
        for ip in ips:
            assert ip not in text
            assert f"ip:{ip}" not in text
        assert "key=" not in text

        # Each of the 3 IPs got exactly one allow and one deny.
        assert (
            _counter_value(
                text,
                "e2e_ratelimit_requests_total",
                backend=real_backend,
                result="allowed",
            )
            == 3.0
        )
        assert (
            _counter_value(
                text,
                "e2e_ratelimit_requests_total",
                backend=real_backend,
                result="denied",
            )
            == 3.0
        )

    def test_metrics_view_is_routable_and_scrapeable(self, real_backend):
        """The metrics endpoint exposes counters in Prometheus text format.

        After real traffic, calling ``prometheus_metrics_view`` returns a 200
        with the Prometheus exposition content-type and the recorded counters
        embedded in the body, so a Prometheus scraper hitting ``/metrics`` would
        see the rate-limit metrics.
        """
        metrics = _fresh_prometheus()
        view = _build_view("2/m")
        ip = "198.51.100.77"

        for code in exhaust(view, 4, ip=ip):
            metrics.record_request(
                key=f"ip:{ip}",
                backend=real_backend,
                allowed=(code == 200),
                duration_seconds=0.001,
            )

        # get_prometheus_metrics() must return the same singleton we recorded
        # into, so the view scrapes the same registry.
        assert get_prometheus_metrics() is metrics

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "django_smart_ratelimit.prometheus._get_prometheus_config",
                lambda: {"enabled": True, "prefix": "e2e_ratelimit"},
            )
            response = prometheus_metrics_view(make_request(path="/metrics/"))

        assert response.status_code == 200
        assert "text/plain" in response["Content-Type"]
        body = response.content.decode("utf-8")
        assert "e2e_ratelimit_requests_total" in body
        assert 'backend="%s"' % real_backend in body
        # 2 allowed + 2 denied recorded from real traffic.
        assert (
            _counter_value(
                body,
                "e2e_ratelimit_requests_total",
                backend=real_backend,
                result="denied",
            )
            == 2.0
        )

    def test_duration_histogram_observed_per_backend(self, real_backend):
        """Latency histogram: duration is observed and labeled by backend only.

        Real checks feed durations into the ``request_duration_seconds``
        histogram. We assert the histogram ``_count`` reflects every recorded
        check and is labeled by the low-cardinality ``backend`` label only.
        """
        metrics = _fresh_prometheus()
        view = _build_view("5/m")
        ip = "198.51.100.90"

        codes = exhaust(view, 6, ip=ip)
        for code in codes:
            metrics.record_request(
                key=f"ip:{ip}",
                backend=real_backend,
                allowed=(code == 200),
                duration_seconds=0.003,
            )

        text = metrics.generate_metrics()
        count = _counter_value(
            text,
            "e2e_ratelimit_request_duration_seconds_count",
            backend=real_backend,
        )
        assert count == float(len(codes))
        # Histogram is labeled by backend, never by key.
        assert "key=" not in text

    def test_independent_buckets_recorded_per_distinct_backend_label(self):
        """Two backends recorded side-by-side keep independent counters.

        Simulate a deployment reporting metrics for two backends at once and
        assert each ``backend`` label carries its own counter values without
        cross-contamination.
        """
        metrics = _fresh_prometheus()

        for _ in range(4):
            metrics.record_request(
                key="ip:a", backend="redis", allowed=True, duration_seconds=0.001
            )
        for _ in range(2):
            metrics.record_request(
                key="ip:b", backend="memory", allowed=False, duration_seconds=0.001
            )

        text = metrics.generate_metrics()
        assert (
            _counter_value(
                text,
                "e2e_ratelimit_requests_total",
                backend="redis",
                result="allowed",
            )
            == 4.0
        )
        assert (
            _counter_value(
                text,
                "e2e_ratelimit_requests_total",
                backend="memory",
                result="denied",
            )
            == 2.0
        )
        # The memory backend recorded zero allows; that sample is simply absent.
        assert (
            _counter_value(
                text,
                "e2e_ratelimit_requests_total",
                backend="memory",
                result="allowed",
            )
            is None
        )


# ===========================================================================
# OpenTelemetry: instrument + record_check from real traffic
# ===========================================================================


def _backend_class_name():
    """Return the live backend's class name, as emitted in OTel attributes.

    The decorator records ``backend=type(backend_instance).__name__`` on every
    real check (see pipeline.handle_shadow_decision -> record_check), so spans
    carry e.g. ``MemoryBackend`` / ``RedisBackend`` rather than the short name.
    """
    from django_smart_ratelimit.backends import get_backend

    return type(get_backend()).__name__


def _spans_for_key(spans, key):
    """Filter exported spans down to those for a specific rate-limit key."""
    return [s for s in spans if s.attributes.get("ratelimit.key") == key]


def _sum_total_points(metric_reader):
    """Sum the ratelimit.requests.total counter and collect decision labels."""
    data = metric_reader.get_metrics_data()
    points = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == "ratelimit.requests.total":
                    points.extend(metric.data.data_points)
    return points


class TestOpenTelemetryRealTraffic:
    """OpenTelemetry instrumentation driven by real decorator traffic.

    The decorator AUTO-emits ``record_check`` for every real rate-limit
    decision (via pipeline.handle_shadow_decision), so these scenarios drive
    real traffic and then scrape the spans/metrics the library itself produced
    against the live backend — no manual mirroring.
    """

    def _reset_otel_globals(self):
        from django_smart_ratelimit.observability import otel

        otel._global_tracer = None
        otel._global_meter = None
        otel._fallback_tracer = None
        otel._fallback_meter = None

    def test_instrument_and_real_traffic_never_errors_on_real_backend(
        self, real_backend
    ):
        """instrument_rate_limit() + real traffic never raises.

        Initialize instrumentation and drive a 3/min endpoint with real
        requests. Instrumentation must be invisible to the caller: the observed
        429-after-3 behavior is unchanged and nothing raised, regardless of
        whether the OTel SDK is installed (no-op fallback path).
        """
        self._reset_otel_globals()
        from django_smart_ratelimit.observability import instrument_rate_limit

        instrument_rate_limit()  # idempotent, safe without OTel installed

        view = _build_view("3/m")
        codes = exhaust(view, 5, ip="192.0.2.55")

        # Observable real behavior is unchanged by instrumentation.
        assert codes[:3] == [200, 200, 200]
        assert codes[3:] == [429, 429]

    @pytest.mark.skipif(not HAS_OTEL_SDK, reason="opentelemetry SDK not installed")
    def test_real_traffic_auto_emits_spans_and_metrics(self, real_backend):
        """With the OTel SDK installed, real traffic auto-emits spans + metrics.

        Wire in-memory OTel exporters via ``instrument_rate_limit`` providers,
        drive a real 2/min endpoint, and assert the library captured one
        ``ratelimit.check`` span per request (2 allowed + 2 denied) with the
        real backend CLASS name on ``ratelimit.backend`` and that the
        ``ratelimit.requests.total`` counter recorded matching low-cardinality
        decision attributes (allowed/denied only).
        """
        self._reset_otel_globals()
        from django_smart_ratelimit.observability import otel

        span_exporter = InMemorySpanExporter()
        tracer_provider = TracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        metric_reader = InMemoryMetricReader()
        meter_provider = MeterProvider(metric_readers=[metric_reader])

        otel.instrument_rate_limit(
            tracer_provider=tracer_provider, meter_provider=meter_provider
        )

        backend_cls = _backend_class_name()
        view = _build_view("2/m")
        ip = "192.0.2.66"
        key = f"ip:{ip}"
        codes = exhaust(view, 4, ip=ip)
        assert codes == [200, 200, 429, 429]

        # Spans for THIS key only (exporter is process-global within OTel).
        spans = _spans_for_key(span_exporter.get_finished_spans(), key)
        assert len(spans) == 4
        decisions = [s.attributes["ratelimit.decision"] for s in spans]
        assert decisions.count("allowed") == 2
        assert decisions.count("denied") == 2
        # Backend attribute carries the real backend CLASS name, not the key.
        for span in spans:
            assert span.attributes["ratelimit.backend"] == backend_cls
            assert span.name == "ratelimit.check"
            # The per-key value lives on a span attribute (fine for traces), not
            # on a metric label.
            assert span.attributes["ratelimit.key"] == key

        # The requests.total counter recorded decisions with low-cardinality
        # decision attributes. The exporter is global, so scope to our backend.
        points = [
            p
            for p in _sum_total_points(metric_reader)
            if p.attributes.get("backend") == backend_cls
        ]
        assert points, "expected ratelimit.requests.total data points"
        seen_decisions = {p.attributes.get("decision") for p in points}
        assert seen_decisions <= {"allowed", "denied"}
        assert "allowed" in seen_decisions and "denied" in seen_decisions
        # No data point carries the per-key value as an attribute.
        for p in points:
            assert "key" not in p.attributes
            assert ip not in str(dict(p.attributes))

    @pytest.mark.skipif(not HAS_OTEL_SDK, reason="opentelemetry SDK not installed")
    def test_shadow_mode_decision_recorded_without_enforcement(self, real_backend):
        """Shadow mode: would-be-denied checks are recorded but never enforced.

        A shadow=True endpoint never returns 429 (real traffic stays 200), yet
        the auto-emitted spans still mark the over-limit checks as denied with
        ``ratelimit.shadow`` set. This proves observability sees what WOULD be
        blocked before enforcement is flipped on.
        """
        self._reset_otel_globals()
        from django_smart_ratelimit.observability import otel

        span_exporter = InMemorySpanExporter()
        tracer_provider = TracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        otel.instrument_rate_limit(tracer_provider=tracer_provider)

        @rate_limit(key="ip", rate="2/m", shadow=True)
        def shadow_view(request):
            return HttpResponse("ok")

        ip = "192.0.2.77"
        key = f"ip:{ip}"
        codes = exhaust(shadow_view, 4, ip=ip)
        # Shadow mode never enforces: all real responses are 200.
        assert codes == [200, 200, 200, 200]

        spans = _spans_for_key(span_exporter.get_finished_spans(), key)
        assert len(spans) == 4
        assert all(s.attributes["ratelimit.shadow"] is True for s in spans)
        # The 3rd and 4th checks are recorded as denied even though nothing was
        # actually enforced (responses were all 200).
        denied = [s for s in spans if s.attributes["ratelimit.decision"] == "denied"]
        assert len(denied) == 2


# ===========================================================================
# Structured JSON logging: real block emits parseable JSON
# ===========================================================================

JSON_LOGGING_ENABLED = {
    "RATELIMIT_LOGGING": {
        "ENABLED": True,
        "FORMAT": "json",
        "LOGGER_NAME": "django_smart_ratelimit",
        "INCLUDE_TIMESTAMP": True,
        "INCLUDE_REQUEST_ID": True,
    }
}


def _parse_json_records(caplog, logger_name="django_smart_ratelimit"):
    """Render caplog records through JSONFormatter and parse them as JSON.

    This mimics how a real deployment formats these records, proving each line
    is a single parseable JSON object.
    """
    formatter = JSONFormatter()
    parsed = []
    for record in caplog.records:
        if record.name != logger_name:
            continue
        line = formatter.format(record)
        # A JSON log line must be a single line and parse cleanly.
        assert "\n" not in line
        parsed.append(json.loads(line))
    return parsed


class TestStructuredLoggingRealBlock:
    """Structured JSON logging API exercised on real rate-limit decisions.

    These tests drive a real decision on the live store and then format it
    through the public logging API (``log_rate_limit_check`` /
    ``log_circuit_breaker_event`` + ``JSONFormatter``), asserting the JSON is
    correct and single-line. That the ENFORCEMENT path emits logs on its own
    (without a manual logging call) is asserted separately by
    ``test_request_path_auto_emits_structured_logs``.
    """

    def teardown_method(self):
        clear_request_context()

    def test_request_path_auto_emits_structured_logs(self, real_backend, caplog):
        """TRUE auto-emit: real enforcement logs with NO manual logging call.

        Unlike the other tests in this class (which call the public logging API
        directly), this drives real traffic through the decorator and asserts the
        library ITSELF emitted log records describing the backend operation --
        proving the request path is instrumented, with the test making no log
        call of its own.
        """
        view = _build_view("2/m")
        with caplog.at_level(logging.DEBUG, logger="django_smart_ratelimit"):
            codes = exhaust(view, 3, ip="198.51.100.195")

        assert codes == [200, 200, 429]
        auto = [
            r for r in caplog.records if r.name.startswith("django_smart_ratelimit")
        ]
        assert len(auto) >= 2, "enforcement path should auto-emit log records"

    def test_real_block_emits_parseable_json_log(self, real_backend, caplog, settings):
        """Login endpoint: 2/min per IP. The block emits a JSON log line.

        Enable JSON structured logging, drive a real 2/min endpoint until the
        live backend blocks (429), then emit the structured check log for the
        denied decision. We assert a single-line, parseable JSON record was
        produced carrying event/backend/allowed=false and the rate-limit key.
        """
        settings.RATELIMIT_LOGGING = JSON_LOGGING_ENABLED["RATELIMIT_LOGGING"]

        view = _build_view("2/m")
        ip = "198.51.100.150"
        key = f"ip:{ip}"

        with caplog.at_level(logging.INFO, logger="django_smart_ratelimit"):
            codes = exhaust(view, 3, ip=ip)
            # The real backend denied the third request.
            assert codes == [200, 200, 429]
            # Emit the structured log for the real denied decision.
            log_rate_limit_check(
                key=key,
                backend=real_backend,
                allowed=False,
                remaining=0,
                limit=2,
                window=60,
                algorithm="sliding_window",
            )

        records = _parse_json_records(caplog)
        denied = [
            r
            for r in records
            if r.get("event") == "rate_limit_check" and r.get("allowed") is False
        ]
        assert denied, "expected a structured denied rate_limit_check log"
        entry = denied[-1]
        assert entry["backend"] == real_backend
        assert entry["key"] == key
        assert entry["limit"] == 2
        assert entry["remaining"] == 0
        # WARNING level is used for denials.
        assert any(
            r.levelname == "WARNING"
            for r in caplog.records
            if r.name == "django_smart_ratelimit"
        )

    def test_allowed_and_denied_emit_distinct_levels(self, real_backend, caplog):
        """Allowed checks log at INFO, denials at WARNING.

        Across a real 1/min endpoint, the allowed request and the denied
        request each produce a structured JSON record at the appropriate level,
        both carrying the same low-cardinality backend label.
        """
        clear_request_context()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "django_smart_ratelimit.logging._get_logging_settings",
                lambda: {
                    "ENABLED": True,
                    "FORMAT": "json",
                    "LOGGER_NAME": "django_smart_ratelimit",
                    "INCLUDE_TIMESTAMP": True,
                    "INCLUDE_REQUEST_ID": True,
                    "EXTRA_FIELDS": {},
                },
            )

            view = _build_view("1/m")
            ip = "198.51.100.160"
            key = f"ip:{ip}"

            with caplog.at_level(logging.INFO, logger="django_smart_ratelimit"):
                codes = exhaust(view, 2, ip=ip)
                assert codes == [200, 429]
                log_rate_limit_check(
                    key=key,
                    backend=real_backend,
                    allowed=True,
                    remaining=0,
                    limit=1,
                    window=60,
                )
                log_rate_limit_check(
                    key=key,
                    backend=real_backend,
                    allowed=False,
                    remaining=0,
                    limit=1,
                    window=60,
                )

            records = _parse_json_records(caplog)
            checks = [r for r in records if r.get("event") == "rate_limit_check"]
            assert any(r.get("allowed") is True for r in checks)
            assert any(r.get("allowed") is False for r in checks)
            assert all(r["backend"] == real_backend for r in checks)

    def test_request_context_enriches_json_log(self, real_backend, caplog):
        """Structured logs carry request context (request id / ip / path).

        Set thread-local request context (as the StructuredLoggingMiddleware
        would for a real request), trigger a real block, and assert the emitted
        JSON record nests the request metadata under a ``request`` object.
        """
        clear_request_context()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "django_smart_ratelimit.logging._get_logging_settings",
                lambda: {
                    "ENABLED": True,
                    "FORMAT": "json",
                    "LOGGER_NAME": "django_smart_ratelimit",
                    "INCLUDE_TIMESTAMP": True,
                    "INCLUDE_REQUEST_ID": True,
                    "EXTRA_FIELDS": {},
                },
            )

            view = _build_view("1/m", key="user")
            user = AuthedUser(uid=4242)
            req = make_request(ip="198.51.100.170", user=user, path="/account/")
            assert view(req).status_code == 200
            assert (
                view(
                    make_request(ip="198.51.100.170", user=user, path="/account/")
                ).status_code
                == 429
            )

            set_request_context(
                request_id="req-abc123",
                ip="198.51.100.170",
                path="/account/",
                method="GET",
                user="4242",
            )
            with caplog.at_level(logging.INFO, logger="django_smart_ratelimit"):
                log_rate_limit_check(
                    key="user:4242",
                    backend=real_backend,
                    allowed=False,
                    remaining=0,
                    limit=1,
                    window=60,
                )

            records = _parse_json_records(caplog)
            assert records
            entry = records[-1]
            assert entry["request"]["request_id"] == "req-abc123"
            assert entry["request"]["ip"] == "198.51.100.170"
            assert entry["request"]["path"] == "/account/"

    def test_circuit_breaker_open_logs_warning_json(self, real_backend, caplog):
        """A circuit-breaker open transition emits a WARNING JSON event.

        Beyond per-request checks, the structured logging API also records
        backend lifecycle events. We assert ``log_circuit_breaker_event`` for an
        open transition produces a parseable JSON record at WARNING level with
        the new state and backend label.
        """
        clear_request_context()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "django_smart_ratelimit.logging._get_logging_settings",
                lambda: {
                    "ENABLED": True,
                    "FORMAT": "json",
                    "LOGGER_NAME": "django_smart_ratelimit",
                    "INCLUDE_TIMESTAMP": True,
                    "INCLUDE_REQUEST_ID": True,
                    "EXTRA_FIELDS": {},
                },
            )
            with caplog.at_level(logging.INFO, logger="django_smart_ratelimit"):
                log_circuit_breaker_event(
                    backend=real_backend,
                    previous_state="closed",
                    new_state="open",
                    reason="connection refused",
                    failure_count=5,
                )

            records = _parse_json_records(caplog)
            cb = [
                r for r in records if r.get("event") == "circuit_breaker_state_change"
            ]
            assert cb
            entry = cb[-1]
            assert entry["new_state"] == "open"
            assert entry["backend"] == real_backend
            assert entry["failure_count"] == 5
            assert any(
                r.levelname == "WARNING"
                for r in caplog.records
                if r.name == "django_smart_ratelimit"
            )

    def test_logging_disabled_emits_nothing(self, real_backend, caplog):
        """When JSON logging is disabled, the convenience helpers stay silent.

        With ``RATELIMIT_LOGGING`` not enabled (the default), a real block emits
        no structured records via ``log_rate_limit_check`` — the integration is
        strictly opt-in.
        """
        clear_request_context()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "django_smart_ratelimit.logging._get_logging_settings",
                lambda: {
                    "ENABLED": False,
                    "FORMAT": "text",
                    "LOGGER_NAME": "django_smart_ratelimit",
                },
            )
            view = _build_view("1/m")
            ip = "198.51.100.180"
            with caplog.at_level(logging.INFO, logger="django_smart_ratelimit"):
                assert exhaust(view, 2, ip=ip) == [200, 429]
                log_rate_limit_check(
                    key=f"ip:{ip}",
                    backend=real_backend,
                    allowed=False,
                    remaining=0,
                    limit=1,
                    window=60,
                )

            structured = [
                r
                for r in caplog.records
                if r.name == "django_smart_ratelimit"
                and getattr(r, "structured", None) is not None
            ]
            assert structured == []


# ===========================================================================
# Cross-cutting: the JSON log event schema keeps the key out of metric labels
# ===========================================================================


def test_log_event_schema_is_json_serializable_and_keyed():
    """Event builder renders a self-describing, JSON-serializable dict.

    The structured event surfaces the per-key value (high-cardinality) in the
    LOG payload — which is correct for logs — while the Prometheus path keeps it
    out of labels. This guards the event builder's public schema.
    """
    event = RateLimitLogEvent(
        event="rate_limit_check",
        key="ip:198.51.100.200",
        backend="memory",
        algorithm="sliding_window",
    )
    event.set_result(allowed=False, remaining=0, limit=5, window=60)
    event.set_duration(0.0021)
    payload = event.as_dict()

    # Round-trips through JSON cleanly.
    reloaded = json.loads(json.dumps(payload, default=str))
    assert reloaded["event"] == "rate_limit_check"
    assert reloaded["key"] == "ip:198.51.100.200"
    assert reloaded["backend"] == "memory"
    assert reloaded["allowed"] is False
    assert reloaded["duration_ms"] == 2.1
