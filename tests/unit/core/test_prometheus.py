"""Tests for Prometheus metrics integration."""

from unittest.mock import MagicMock

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from django_smart_ratelimit.prometheus import (
    PrometheusMetrics,
    PrometheusMetricsMiddleware,
    SimpleCounter,
    SimpleGauge,
    SimpleHistogram,
    _LabeledSimpleMetric,
    get_prometheus_metrics,
    prometheus_metrics_view,
)


class TestSimpleCounter(TestCase):
    """Test SimpleCounter for Prometheus text format."""

    def test_counter_inc(self):
        counter = SimpleCounter("test_total", "A test counter")
        counter.inc()
        counter.inc(2.0)
        output = counter.collect()
        assert "# HELP test_total A test counter" in output
        assert "# TYPE test_total counter" in output
        assert "test_total 3.0" in output

    def test_counter_with_labels(self):
        counter = SimpleCounter(
            "test_total", "A test counter", labels=["method", "status"]
        )
        counter.labels(method="GET", status="200").inc()
        counter.labels(method="POST", status="429").inc(3.0)
        output = counter.collect()
        assert 'test_total{method="GET",status="200"} 1.0' in output
        assert 'test_total{method="POST",status="429"} 3.0' in output


class TestSimpleGauge(TestCase):
    """Test SimpleGauge for Prometheus text format."""

    def test_gauge_set(self):
        gauge = SimpleGauge("test_gauge", "A test gauge")
        gauge.set(42.0)
        output = gauge.collect()
        assert "# TYPE test_gauge gauge" in output
        assert "test_gauge 42.0" in output

    def test_gauge_inc_dec(self):
        gauge = SimpleGauge("test_gauge", "A test gauge")
        gauge.inc()
        gauge.inc(4.0)
        gauge.dec(2.0)
        output = gauge.collect()
        assert "test_gauge 3.0" in output

    def test_gauge_with_labels(self):
        gauge = SimpleGauge("test_gauge", "A test gauge", labels=["backend"])
        gauge.labels(backend="redis").set(1.0)
        gauge.labels(backend="memory").set(0.0)
        output = gauge.collect()
        assert 'test_gauge{backend="redis"} 1.0' in output
        assert 'test_gauge{backend="memory"} 0.0' in output


class TestSimpleHistogram(TestCase):
    """Test SimpleHistogram for Prometheus text format."""

    def test_histogram_observe(self):
        hist = SimpleHistogram(
            "test_duration",
            "A test histogram",
            buckets=(0.01, 0.05, 0.1, float("inf")),
        )
        hist.observe(0.005)
        hist.observe(0.03)
        hist.observe(0.08)
        output = hist.collect()
        assert "# TYPE test_duration histogram" in output
        assert 'test_duration_bucket{le="0.01"} 1' in output
        assert 'test_duration_bucket{le="0.05"} 2' in output
        assert 'test_duration_bucket{le="0.1"} 3' in output
        assert 'test_duration_bucket{le="+Inf"} 3' in output
        assert "test_duration_count 3" in output

    def test_histogram_with_labels(self):
        hist = SimpleHistogram(
            "test_duration",
            "A test histogram",
            labels=["backend"],
            buckets=(0.1, float("inf")),
        )
        hist.labels(backend="redis").observe(0.05)
        hist.labels(backend="redis").observe(0.5)
        output = hist.collect()
        assert 'test_duration_bucket{backend="redis",le="0.1"} 1' in output
        assert 'test_duration_bucket{backend="redis",le="+Inf"} 2' in output


class TestPrometheusMetrics(TestCase):
    """Test PrometheusMetrics singleton."""

    def setUp(self):
        PrometheusMetrics.reset()

    def tearDown(self):
        PrometheusMetrics.reset()

    def test_singleton(self):
        m1 = PrometheusMetrics()
        m2 = PrometheusMetrics()
        assert m1 is m2

    def test_initialize(self):
        metrics = PrometheusMetrics()
        metrics._initialize(prefix="test_rl")
        assert metrics._initialized
        assert metrics._prefix == "test_rl"

    def test_record_request_allowed(self):
        metrics = PrometheusMetrics()
        metrics._initialize(prefix="test_rl")
        metrics.record_request(
            key="user:123",
            backend="memory",
            allowed=True,
            duration_seconds=0.005,
        )
        output = metrics.generate_metrics()
        assert "test_rl_requests_total" in output
        assert "allowed" in output

    def test_record_request_denied(self):
        metrics = PrometheusMetrics()
        metrics._initialize(prefix="test_rl")
        metrics.record_request(
            key="user:456",
            backend="redis",
            allowed=False,
            duration_seconds=0.01,
        )
        output = metrics.generate_metrics()
        assert "test_rl_requests_denied_total" in output
        assert "denied" in output

    def test_set_backend_health(self):
        metrics = PrometheusMetrics()
        metrics._initialize(prefix="test_rl")
        metrics.set_backend_health("redis", True)
        metrics.set_backend_health("memory", False)
        output = metrics.generate_metrics()
        assert "test_rl_backend_healthy" in output

    def test_set_circuit_breaker_state(self):
        metrics = PrometheusMetrics()
        metrics._initialize(prefix="test_rl")
        metrics.set_circuit_breaker_state("redis", "closed")
        metrics.set_circuit_breaker_state("memory", "open")
        output = metrics.generate_metrics()
        assert "test_rl_circuit_breaker_state" in output

    def test_set_active_keys(self):
        metrics = PrometheusMetrics()
        metrics._initialize(prefix="test_rl")
        metrics.set_active_keys("memory", 42)
        output = metrics.generate_metrics()
        assert "test_rl_active_keys" in output

    def test_generate_metrics_not_initialized(self):
        metrics = PrometheusMetrics()
        output = metrics.generate_metrics()
        assert output == ""

    def test_record_request_not_initialized(self):
        metrics = PrometheusMetrics()
        # Should not raise
        metrics.record_request(
            key="test", backend="memory", allowed=True, duration_seconds=0.001
        )

    def test_reset(self):
        m1 = PrometheusMetrics()
        m1._initialize(prefix="test_rl")
        PrometheusMetrics.reset()
        m2 = PrometheusMetrics()
        assert m1 is not m2
        assert not m2._initialized


class TestGetPrometheusMetrics(TestCase):
    """Test get_prometheus_metrics helper."""

    def setUp(self):
        PrometheusMetrics.reset()

    def tearDown(self):
        PrometheusMetrics.reset()

    @override_settings(RATELIMIT_PROMETHEUS={"ENABLED": True, "PREFIX": "myapp_rl"})
    def test_custom_prefix(self):
        metrics = get_prometheus_metrics()
        assert metrics._initialized
        assert metrics._prefix == "myapp_rl"

    @override_settings()
    def test_default_prefix(self):
        metrics = get_prometheus_metrics()
        assert metrics._prefix == "django_ratelimit"


class TestPrometheusMetricsView(TestCase):
    """Test the Prometheus metrics view."""

    def setUp(self):
        PrometheusMetrics.reset()
        self.factory = RequestFactory()

    def tearDown(self):
        PrometheusMetrics.reset()

    @override_settings(RATELIMIT_PROMETHEUS={"ENABLED": True})
    def test_metrics_view_returns_200(self):
        request = self.factory.get("/metrics/")
        response = prometheus_metrics_view(request)
        assert response.status_code == 200
        assert "text/plain" in response["Content-Type"]

    @override_settings(RATELIMIT_PROMETHEUS={"ENABLED": False})
    def test_metrics_view_disabled(self):
        request = self.factory.get("/metrics/")
        response = prometheus_metrics_view(request)
        assert response.status_code == 404

    @override_settings(RATELIMIT_PROMETHEUS={"ENABLED": True, "PREFIX": "test_rl"})
    def test_metrics_view_content(self):
        metrics = get_prometheus_metrics()
        metrics.record_request(
            key="test", backend="memory", allowed=True, duration_seconds=0.001
        )
        request = self.factory.get("/metrics/")
        response = prometheus_metrics_view(request)
        content = response.content.decode("utf-8")
        assert "test_rl_requests_total" in content


class TestPrometheusMetricsMiddleware(TestCase):
    """Test the PrometheusMetricsMiddleware."""

    def setUp(self):
        PrometheusMetrics.reset()
        self.factory = RequestFactory()

    def tearDown(self):
        PrometheusMetrics.reset()

    @override_settings(RATELIMIT_PROMETHEUS={"ENABLED": True, "PREFIX": "test_mw"})
    def test_middleware_records_ratelimit_info(self):
        ratelimit_info = MagicMock()
        ratelimit_info.key = "user:1"
        ratelimit_info.backend = "memory"
        ratelimit_info.limited = False

        def get_response(request):
            request.ratelimit = ratelimit_info
            return HttpResponse("OK")

        middleware = PrometheusMetricsMiddleware(get_response)
        request = self.factory.get("/api/test/")
        response = middleware(request)

        assert response.status_code == 200
        output = middleware.metrics.generate_metrics()
        assert "test_mw_requests_total" in output

    @override_settings(RATELIMIT_PROMETHEUS={"ENABLED": True, "PREFIX": "test_mw"})
    def test_middleware_tracks_429(self):
        def get_response(request):
            return HttpResponse("Rate Limited", status=429)

        middleware = PrometheusMetricsMiddleware(get_response)
        request = self.factory.get("/api/test/")
        response = middleware(request)

        assert response.status_code == 429
        output = middleware.metrics.generate_metrics()
        assert "denied" in output or "requests_denied_total" in output

    @override_settings(RATELIMIT_PROMETHEUS={"ENABLED": True, "PREFIX": "test_mw"})
    def test_middleware_no_ratelimit_info(self):
        def get_response(request):
            return HttpResponse("OK")

        middleware = PrometheusMetricsMiddleware(get_response)
        request = self.factory.get("/static/test.css")
        response = middleware(request)

        assert response.status_code == 200

    @override_settings(RATELIMIT_PROMETHEUS={"ENABLED": True, "PREFIX": "test_mw"})
    def test_middleware_records_denied(self):
        ratelimit_info = MagicMock()
        ratelimit_info.key = "ip:192.168.1.1"
        ratelimit_info.backend = "redis"
        ratelimit_info.limited = True

        def get_response(request):
            request.ratelimit = ratelimit_info
            return HttpResponse("Too Many Requests", status=429)

        middleware = PrometheusMetricsMiddleware(get_response)
        request = self.factory.get("/api/test/")
        middleware(request)

        output = middleware.metrics.generate_metrics()
        assert "test_mw_requests_denied_total" in output


class TestLabeledSimpleMetric(TestCase):
    """Test _LabeledSimpleMetric helper."""

    def test_labeled_inc(self):
        counter = SimpleCounter("test", "test", labels=["a"])
        labeled = _LabeledSimpleMetric(counter, ("val",))
        labeled.inc()
        labeled.inc(2.0)
        assert counter._values[("val",)] == 3.0

    def test_labeled_set(self):
        gauge = SimpleGauge("test", "test", labels=["a"])
        labeled = _LabeledSimpleMetric(gauge, ("val",))
        labeled.set(42.0)
        assert gauge._values[("val",)] == 42.0

    def test_labeled_observe(self):
        hist = SimpleHistogram("test", "test", labels=["a"])
        labeled = _LabeledSimpleMetric(hist, ("val",))
        labeled.observe(0.5)
        assert len(hist._observations[("val",)]) == 1


class TestThreadSafety(TestCase):
    """Test thread safety of metrics collection."""

    def setUp(self):
        PrometheusMetrics.reset()

    def tearDown(self):
        PrometheusMetrics.reset()

    def test_concurrent_counter_increments(self):
        import threading

        counter = SimpleCounter("test_concurrent", "Concurrent test")
        threads = []
        for _ in range(10):
            t = threading.Thread(target=lambda: [counter.inc() for _ in range(100)])
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert counter._values[()] == 1000.0

    def test_concurrent_histogram_observations(self):
        import threading

        hist = SimpleHistogram(
            "test_hist", "Concurrent hist", buckets=(0.5, 1.0, float("inf"))
        )
        threads = []
        for _ in range(10):
            t = threading.Thread(target=lambda: [hist.observe(0.1) for _ in range(100)])
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(hist._observations[()]) == 1000


class TestEdgeCases(TestCase):
    """Test edge cases."""

    def setUp(self):
        PrometheusMetrics.reset()

    def tearDown(self):
        PrometheusMetrics.reset()

    def test_empty_metrics_output(self):
        counter = SimpleCounter("empty_counter", "Empty counter")
        output = counter.collect()
        assert "# HELP empty_counter" in output
        assert "# TYPE empty_counter counter" in output

    def test_special_characters_in_labels(self):
        counter = SimpleCounter("test", "test", labels=["path"])
        counter.labels(path="/api/v1/users").inc()
        output = counter.collect()
        assert 'path="/api/v1/users"' in output

    def test_multiple_record_requests(self):
        metrics = PrometheusMetrics()
        metrics._initialize(prefix="edge")
        for i in range(100):
            metrics.record_request(
                key=f"user:{i % 10}",
                backend="memory",
                allowed=i % 3 != 0,
                duration_seconds=0.001 * i,
            )
        output = metrics.generate_metrics()
        assert "edge_requests_total" in output
        assert "edge_request_duration_seconds" in output
