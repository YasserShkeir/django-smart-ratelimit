"""StatsD metrics exporter (roadmap Phase 5.1.3).

A dependency-free, fire-and-forget StatsD client and a ``StatsDMetrics`` facade
mirroring the :class:`~django_smart_ratelimit.prometheus.PrometheusMetrics` API
(``record_request`` plus health / circuit-breaker / active-key gauges). Metrics
are emitted as UDP packets in the StatsD line protocol with optional
DogStatsD-style tags; network and configuration errors are swallowed so metrics
never affect request handling.

Enable by pointing at a StatsD/DogStatsD agent::

    RATELIMIT_STATSD = {
        "ENABLED": True,
        "HOST": "127.0.0.1",
        "PORT": 8125,
        "PREFIX": "django_ratelimit",
    }
"""

import logging
import socket
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _get_statsd_config() -> Dict[str, Any]:
    """Read StatsD configuration from Django settings (``RATELIMIT_STATSD``)."""
    from django.conf import settings as django_settings

    config = getattr(django_settings, "RATELIMIT_STATSD", {})
    return {
        "enabled": config.get("ENABLED", False),
        "host": config.get("HOST", "127.0.0.1"),
        "port": int(config.get("PORT", 8125)),
        "prefix": config.get("PREFIX", "django_ratelimit"),
    }


class StatsDClient:
    """Minimal fire-and-forget UDP StatsD client (no external dependency).

    Emits counters (``c``), timers (``ms``), and gauges (``g``). DogStatsD-style
    ``|#k:v`` tags are appended when provided. Send failures are swallowed.
    """

    def __init__(
        self, host: str = "127.0.0.1", port: int = 8125, prefix: str = "ratelimit"
    ) -> None:
        """Open the UDP socket and remember the destination and metric prefix."""
        self._addr = (host, int(port))
        self._prefix = prefix.rstrip(".")
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def format_metric(
        self,
        metric: str,
        value: Any,
        unit: str,
        tags: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build a StatsD line (exposed for testing); no I/O."""
        name = f"{self._prefix}.{metric}" if self._prefix else metric
        line = f"{name}:{value}|{unit}"
        if tags:
            line += "|#" + ",".join(f"{k}:{v}" for k, v in tags.items())
        return line

    def _send(
        self, metric: str, value: Any, unit: str, tags: Optional[Dict[str, Any]]
    ) -> None:
        line = self.format_metric(metric, value, unit, tags)
        try:
            self._sock.sendto(line.encode("utf-8"), self._addr)
        except OSError as exc:  # pragma: no cover - network failure must not raise
            logger.debug("statsd send failed: %s", exc)

    def incr(
        self, metric: str, value: int = 1, tags: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a counter increment."""
        self._send(metric, int(value), "c", tags)

    def timing(
        self, metric: str, ms: float, tags: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a timer value in milliseconds."""
        self._send(metric, round(float(ms), 3), "ms", tags)

    def gauge(
        self, metric: str, value: float, tags: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a gauge value."""
        self._send(metric, round(float(value), 3), "g", tags)


class StatsDMetrics:
    """StatsD facade mirroring :class:`PrometheusMetrics` (singleton)."""

    _instance: Optional["StatsDMetrics"] = None
    _lock = threading.Lock()

    def __init__(self, client: Optional[StatsDClient] = None) -> None:
        """Build from ``RATELIMIT_STATSD`` settings, or inject a client (tests)."""
        config = _get_statsd_config()
        self._enabled = bool(config["enabled"]) or client is not None
        if client is not None:
            self._client: Optional[StatsDClient] = client
        elif self._enabled:
            self._client = StatsDClient(
                host=config["host"], port=config["port"], prefix=config["prefix"]
            )
        else:
            self._client = None

    @property
    def enabled(self) -> bool:
        """Whether metrics are being emitted."""
        return self._enabled and self._client is not None

    def record_request(
        self, key: str, backend: str, allowed: bool, duration_seconds: float
    ) -> None:
        """Record a rate-limit check.

        ``key`` is accepted for API parity with the Prometheus exporter but is
        deliberately not used as a tag (per-key tags cause unbounded
        cardinality).
        """
        if not self.enabled:
            return
        assert self._client is not None
        result = "allowed" if allowed else "denied"
        self._client.incr("requests", tags={"backend": backend, "result": result})
        if not allowed:
            self._client.incr("requests_denied", tags={"backend": backend})
        self._client.timing(
            "request_duration", duration_seconds * 1000.0, tags={"backend": backend}
        )

    def set_backend_health(self, backend: str, healthy: bool) -> None:
        """Record backend health as a 0/1 gauge."""
        if not self.enabled:
            return
        assert self._client is not None
        self._client.gauge("backend_healthy", 1 if healthy else 0, {"backend": backend})

    def set_circuit_breaker_state(self, backend: str, state: str) -> None:
        """Record circuit-breaker state (closed=0, half-open=1, open=2)."""
        if not self.enabled:
            return
        assert self._client is not None
        state_map = {"closed": 0, "half-open": 1, "open": 2}
        self._client.gauge(
            "circuit_breaker_state", state_map.get(state, 0), {"backend": backend}
        )

    def set_active_keys(self, backend: str, count: int) -> None:
        """Record the number of active rate-limit keys."""
        if not self.enabled:
            return
        assert self._client is not None
        self._client.gauge("active_keys", float(count), {"backend": backend})

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (useful for testing)."""
        with cls._lock:
            cls._instance = None


def get_statsd_metrics() -> StatsDMetrics:
    """Get or create the singleton :class:`StatsDMetrics`."""
    if StatsDMetrics._instance is None:
        with StatsDMetrics._lock:
            if StatsDMetrics._instance is None:
                StatsDMetrics._instance = StatsDMetrics()
    return StatsDMetrics._instance
