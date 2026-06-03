# Observability

`django-smart-ratelimit` can export what it is doing to your monitoring stack
through two independent integrations:

- **OpenTelemetry** — spans and metrics for every rate-limit check.
- **Prometheus** — a `/metrics` endpoint plus middleware that records check
  outcomes.

Both are optional and degrade to no-ops when their libraries are not installed,
so you can leave the instrumentation calls in your code unconditionally.

## OpenTelemetry

### Installation

```bash
pip install "django-smart-ratelimit[opentelemetry]"
```

If OpenTelemetry is not installed, the API below still imports and runs — it
just emits nothing.

### Enabling Instrumentation

Call `instrument_rate_limit()` once at startup, typically from an
`AppConfig.ready()`:

```python
# apps.py
from django.apps import AppConfig

from django_smart_ratelimit.observability import instrument_rate_limit


class MyAppConfig(AppConfig):
    name = "myapp"

    def ready(self):
        instrument_rate_limit()
```

`instrument_rate_limit()` is idempotent and safe to call more than once. By
default it uses the global tracer and meter providers; you can pass your own:

```python
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider

from django_smart_ratelimit.observability import instrument_rate_limit

instrument_rate_limit(
    tracer_provider=TracerProvider(),
    meter_provider=MeterProvider(),
)
```

### What Gets Emitted

Once instrumented, every rate-limit decision (including shadow-mode decisions)
is recorded by `record_check()`, which the decorator, middleware, and pipeline
call internally. You normally do not call it yourself, but it is part of the
public API for custom integrations:

```python
from django_smart_ratelimit.observability import record_check

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
```

`record_rate_limit_decision()` is an alias with the same signature.

#### Spans

A `ratelimit.check` span is created for each check with these attributes:

| Attribute              | Meaning                                          |
| ---------------------- | ------------------------------------------------ |
| `ratelimit.key`        | The rate-limit key                               |
| `ratelimit.limit`      | Configured limit                                 |
| `ratelimit.remaining`  | Remaining count after the request                |
| `ratelimit.algorithm`  | Algorithm name (`sliding_window`, …)             |
| `ratelimit.backend`    | Backend class name                               |
| `ratelimit.decision`   | `"allowed"` or `"denied"`                        |
| `ratelimit.shadow`     | `True` when the check ran in shadow mode         |
| `ratelimit.cost`       | Tokens consumed (default `1`)                    |

Denied checks also add a `ratelimit.denied` event and set the span status to
`ERROR`.

#### Metrics

| Instrument                      | Type           | Attributes                                  |
| ------------------------------- | -------------- | ------------------------------------------- |
| `ratelimit.requests.total`      | Counter        | `decision`, `backend`, `algorithm`, `shadow`|
| `ratelimit.tokens.consumed`     | Counter        | `backend`, `algorithm`                       |
| `ratelimit.check.duration_ms`   | Histogram      | `backend`, `algorithm`                       |
| `ratelimit.backend.errors`      | UpDownCounter  | `error_type`                                 |

The `shadow` attribute on `ratelimit.requests.total` lets you compare what a new
limit *would* block (`shadow="True"`) against what is actually enforced — the
foundation of a safe rollout. See the
[`shadow_rollout` example](https://github.com/YasserShkeir/django-smart-ratelimit/tree/main/examples/shadow_rollout).

## Prometheus

### Installation

```bash
pip install "django-smart-ratelimit[prometheus]"
```

If `prometheus_client` is not installed, the integration falls back to a small
built-in implementation that still produces valid Prometheus text-format output.

### Setup

Add the middleware and expose the metrics endpoint:

```python
# settings.py
MIDDLEWARE = [
    # ...
    "django_smart_ratelimit.prometheus.PrometheusMetricsMiddleware",
]
```

```python
# urls.py
from django.urls import path

from django_smart_ratelimit.prometheus import prometheus_metrics_view

urlpatterns = [
    path("metrics/", prometheus_metrics_view),
]
```

The middleware times each request and, when a rate-limit decision was attached
to the request (by the decorator or middleware), records its outcome. Responses
with status `429` are counted as denied even without attached rate-limit info.

### Configuration: RATELIMIT_PROMETHEUS

```python
# settings.py
RATELIMIT_PROMETHEUS = {
    "ENABLED": True,                  # default True
    "PREFIX": "django_ratelimit",     # metric name prefix, default "django_ratelimit"
}
```

When `ENABLED` is `False`, `prometheus_metrics_view` returns `404` so you can
turn the endpoint off without removing the URL.

### Exposed Metrics

With the default `django_ratelimit` prefix the endpoint exposes:

| Metric                                    | Type      | Labels              |
| ----------------------------------------- | --------- | ------------------- |
| `django_ratelimit_requests_total`         | Counter   | `backend`, `result` |
| `django_ratelimit_requests_denied_total`  | Counter   | `backend`           |
| `django_ratelimit_request_duration_seconds` | Histogram | `backend`         |
| `django_ratelimit_active_keys`            | Gauge     | `backend`           |
| `django_ratelimit_backend_healthy`        | Gauge     | `backend`           |
| `django_ratelimit_circuit_breaker_state`  | Gauge     | `backend`           |

`circuit_breaker_state` is `0` (closed), `1` (half-open), or `2` (open).

> **Note on cardinality**: the rate-limit *key* is intentionally **not** used as
> a metric label. Per-IP or per-user keys would explode Prometheus label
> cardinality, so metrics are aggregated by `backend` and `result` only.

### Programmatic Access

`get_prometheus_metrics()` returns the lazily-initialized singleton if you want
to record gauges (backend health, active keys, circuit-breaker state) from your
own code:

```python
from django_smart_ratelimit.prometheus import get_prometheus_metrics

metrics = get_prometheus_metrics()
metrics.set_backend_health("redis", healthy=True)
metrics.set_active_keys("redis", count=1_234)
```

## StatsD

For push-based monitoring (StatsD / DogStatsD / Datadog agent), a dependency-free
UDP exporter mirrors the Prometheus API. It is fire-and-forget: network failures
are swallowed and never affect request handling.

### Configuration: RATELIMIT_STATSD

```python
# settings.py
RATELIMIT_STATSD = {
    "ENABLED": True,
    "HOST": "127.0.0.1",
    "PORT": 8125,
    "PREFIX": "django_ratelimit",  # metric name prefix
}
```

With `ENABLED` off (the default), the exporter is a no-op.

### Emitted metrics

`record_request()` emits a `requests` counter (tagged `backend` and
`result=allowed|denied`), a `requests_denied` counter on denials, and a
`request_duration` timer (milliseconds). Gauges are available for backend
health, circuit-breaker state, and active key counts. DogStatsD-style
`|#tag:value` tags are included.

### Programmatic access

```python
from django_smart_ratelimit.statsd import get_statsd_metrics

metrics = get_statsd_metrics()
metrics.record_request("ip:1.2.3.4", backend="redis", allowed=False,
                       duration_seconds=0.004)
metrics.set_backend_health("redis", healthy=True)
```

> **Grafana:** scrape the Prometheus `/metrics` endpoint with a Prometheus data
> source, or send StatsD metrics to a Datadog/Graphite source. The metric names
> above (`*_requests`, `*_requests_denied`, `*_request_duration`) are what you
> graph.

## See Also

- [Decorator](decorator.md) — `shadow=True` for safe rollouts.
- [Backends](backends.md) — backend names that appear in the metric labels.
- [Deployment](deployment.md) — running the metrics endpoint in production.
