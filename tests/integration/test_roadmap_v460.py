"""v4.6.0 roadmap-completion features.

Covers the analytics offender detail view + threshold alerting (4.3.2 / 4.3.4),
the StatsD exporter (5.1.3), the time-of-day adaptive indicator (5.3.1), and the
native atomic Redis leaky bucket (5.2.3).
"""

import pytest

from django.contrib.auth.models import User
from django.core import mail
from django.test import RequestFactory, override_settings

from django_smart_ratelimit.adaptive import TimeOfDayIndicator
from django_smart_ratelimit.analytics import (
    find_alertable_offenders,
    get_offender_detail,
    send_offender_alerts,
)
from django_smart_ratelimit.statsd import StatsDClient, StatsDMetrics
from django_smart_ratelimit.views import offender_detail_view


def _staff_req(path="/x", **params):
    request = RequestFactory().get(path, params)
    # A real User instance is always is_authenticated == True (read-only property).
    request.user = User(username="staff", is_staff=True)
    return request


# ---------------------------------------------------------------------------
# 5.3.1 time-of-day adaptive indicator
# ---------------------------------------------------------------------------


def test_time_of_day_indicator_peak_and_off_peak():
    from django.utils import timezone

    hour = timezone.localtime(timezone.now()).hour
    peak = TimeOfDayIndicator(peak_hours=[hour], peak_load=0.9, off_peak_load=0.1)
    assert peak.get_load() == 0.9
    off = TimeOfDayIndicator(
        peak_hours=[(hour + 1) % 24], peak_load=0.9, off_peak_load=0.1
    )
    assert off.get_load() == 0.1


def test_time_of_day_indicator_clamps_loads():
    ind = TimeOfDayIndicator(peak_hours=[], peak_load=5.0, off_peak_load=-2.0)
    assert ind.get_load() == 0.0  # off-peak (-2 clamped to 0)


# ---------------------------------------------------------------------------
# 5.1.3 StatsD exporter
# ---------------------------------------------------------------------------


class _FakeStatsD:
    def __init__(self):
        self.calls = []

    def incr(self, metric, value=1, tags=None):
        self.calls.append(("c", metric, value, tags))

    def timing(self, metric, ms, tags=None):
        self.calls.append(("ms", metric, ms, tags))

    def gauge(self, metric, value, tags=None):
        self.calls.append(("g", metric, value, tags))


def test_statsd_line_format():
    client = StatsDClient(prefix="django_ratelimit")
    line = client.format_metric("requests", 3, "c", {"backend": "redis"})
    assert line == "django_ratelimit.requests:3|c|#backend:redis"
    assert client.format_metric("x", 1, "c") == "django_ratelimit.x:1|c"


def test_statsd_record_request_emits_counter_and_timing():
    fake = _FakeStatsD()
    metrics = StatsDMetrics(client=fake)
    assert metrics.enabled is True

    metrics.record_request("ip:1.2.3.4", "redis", allowed=True, duration_seconds=0.01)
    metrics.record_request("ip:1.2.3.4", "redis", allowed=False, duration_seconds=0.02)

    units = [c[0] for c in fake.calls]
    assert units.count("c") == 3  # allowed:1 + denied(counter+denied_total):2
    assert units.count("ms") == 2
    # A denied request emits both the result=denied counter and requests_denied.
    names = [c[1] for c in fake.calls if c[0] == "c"]
    assert "requests_denied" in names


def test_statsd_disabled_without_config_is_noop():
    StatsDMetrics.reset()
    with override_settings(RATELIMIT_STATSD={"ENABLED": False}):
        metrics = StatsDMetrics()
        assert metrics.enabled is False
        # No client -> calls are no-ops and never raise.
        metrics.record_request("k", "memory", allowed=True, duration_seconds=0.0)
        metrics.set_active_keys("memory", 5)
    StatsDMetrics.reset()


# ---------------------------------------------------------------------------
# 4.3.2 / 4.3.4 analytics: offender detail + alerting
# ---------------------------------------------------------------------------


def _make_events(key, blocked, allowed=0, path="/api"):
    from django_smart_ratelimit.models import RateLimitEvent

    for _ in range(blocked):
        RateLimitEvent.objects.create(
            key=key, path=path, method="GET", allowed=False, count=11, limit=10
        )
    for _ in range(allowed):
        RateLimitEvent.objects.create(
            key=key, path=path, method="GET", allowed=True, count=1, limit=10
        )


@pytest.mark.django_db
def test_get_offender_detail():
    _make_events("ip:9.9.9.9", blocked=5, allowed=3, path="/login")
    detail = get_offender_detail("ip:9.9.9.9", days=7)
    assert detail["blocked"] == 5
    assert detail["allowed"] == 3
    assert detail["total"] == 8
    assert round(detail["block_rate"], 3) == round(5 / 8, 3)
    assert detail["by_path"][0]["path"] == "/login"
    assert detail["first_seen"] is not None
    assert len(detail["recent_events"]) == 8


@pytest.mark.django_db
def test_find_alertable_offenders_threshold():
    _make_events("ip:1.1.1.1", blocked=10)
    _make_events("ip:2.2.2.2", blocked=3)
    alertable = find_alertable_offenders(threshold=5, days=1)
    keys = {row["key"] for row in alertable}
    assert "ip:1.1.1.1" in keys
    assert "ip:2.2.2.2" not in keys


@pytest.mark.django_db
def test_send_offender_alerts_disabled_without_threshold():
    _make_events("ip:3.3.3.3", blocked=10)
    result = send_offender_alerts(threshold=None, days=1)
    assert result["enabled"] is False


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="alerts@example.com",
    RATELIMIT_ALERT_EMAILS=["ops@example.com"],
)
def test_send_offender_alerts_email():
    _make_events("ip:4.4.4.4", blocked=20)
    result = send_offender_alerts(threshold=5, days=1)
    assert result["enabled"] is True
    assert result["channels"]["email"]["sent"] is True
    assert len(mail.outbox) == 1
    assert "ip:4.4.4.4" in mail.outbox[0].body


@pytest.mark.django_db
def test_send_offender_alerts_webhook(monkeypatch):
    _make_events("ip:5.5.5.5", blocked=8)
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["url"] = req.full_url
        sent["body"] = req.data

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = send_offender_alerts(
        threshold=5, days=1, webhook_url="https://hooks.example.com/x"
    )
    assert result["channels"]["webhook"]["sent"] is True
    assert sent["url"] == "https://hooks.example.com/x"
    assert b"ip:5.5.5.5" in sent["body"]


@pytest.mark.django_db
def test_offender_detail_view_staff_only():
    _make_events("ip:6.6.6.6", blocked=4)
    # Authenticated but NOT staff -> 403
    non_staff = RequestFactory().get("/", {"key": "ip:6.6.6.6"})
    non_staff.user = User(username="plainuser")  # is_staff defaults to False
    assert offender_detail_view(non_staff).status_code == 403
    # Staff -> 200 JSON with the detail
    resp = offender_detail_view(_staff_req(key="ip:6.6.6.6"))
    assert resp.status_code == 200
    import json

    data = json.loads(resp.content)
    assert data["key"] == "ip:6.6.6.6"
    assert data["blocked"] == 4
    # Missing key -> 400
    assert offender_detail_view(_staff_req()).status_code == 400


# ---------------------------------------------------------------------------
# 5.2.3 native atomic Redis leaky bucket
# ---------------------------------------------------------------------------


def test_redis_native_leaky_bucket_atomic():
    from django_smart_ratelimit.backends.redis_backend import RedisBackend

    backend = RedisBackend()
    key = "lbtest:v460"
    backend.reset(key)
    # capacity 5, negligible leak during the test -> exactly 5 admitted.
    decisions = [backend.leaky_bucket_check(key, 5, 0.0001, 1)[0] for _ in range(7)]
    assert decisions == [True, True, True, True, True, False, False]
    info = backend.leaky_bucket_info(key, 5, 0.0001)
    assert info["bucket_level"] > 4.0  # near full, read-only (no mutation)
    backend.reset(key)
