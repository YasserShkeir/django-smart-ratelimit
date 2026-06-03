"""Tests for the Phase 4 analytics feature.

Covers RateLimitEvent recording (middleware), the analytics aggregations, the
staff-gated dashboard view, the CSV export, and event cleanup.
"""

from datetime import timedelta

import pytest

from django.contrib import admin
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.utils import timezone

import django_smart_ratelimit.admin  # noqa: F401
from django_smart_ratelimit import analytics
from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.middleware import RateLimitMiddleware
from django_smart_ratelimit.models import RateLimitEvent
from django_smart_ratelimit.views import RateLimitDashboardView, offenders_csv_view

pytestmark = pytest.mark.django_db


def _req(path="/api/x", ip="203.0.113.5"):
    request = RequestFactory().get(path)
    request.META["REMOTE_ADDR"] = ip
    return request


def _seed(n_allowed=2, n_blocked=3, key="k", days_ago=0):
    when = timezone.now() - timedelta(days=days_ago)
    for i in range(n_allowed + n_blocked):
        ev = RateLimitEvent.objects.create(
            key=key,
            path="/api/",
            method="GET",
            allowed=(i < n_allowed),
            count=i + 1,
            limit=n_allowed,
        )
        if days_ago:
            RateLimitEvent.objects.filter(pk=ev.pk).update(timestamp=when)


# ---------------------------------------------------------------------------
# Event recording
# ---------------------------------------------------------------------------


@override_settings(
    RATELIMIT_LOG_EVENTS=True,
    RATELIMIT_MIDDLEWARE={"BACKEND": "memory", "DEFAULT_RATE": "2/m"},
)
def test_middleware_records_events():
    clear_backend_cache()
    codes = [
        RateLimitMiddleware(lambda r: HttpResponse("ok"))(_req()).status_code
        for _ in range(5)
    ]
    assert codes == [200, 200, 429, 429, 429]
    assert RateLimitEvent.objects.count() == 5
    assert RateLimitEvent.objects.filter(allowed=False).count() == 3
    clear_backend_cache()


@override_settings(
    RATELIMIT_LOG_EVENTS=False,
    RATELIMIT_MIDDLEWARE={"BACKEND": "memory", "DEFAULT_RATE": "2/m"},
)
def test_no_events_when_disabled():
    clear_backend_cache()
    for _ in range(3):
        RateLimitMiddleware(lambda r: HttpResponse("ok"))(_req())
    assert RateLimitEvent.objects.count() == 0
    clear_backend_cache()


# ---------------------------------------------------------------------------
# Analytics aggregations
# ---------------------------------------------------------------------------


def test_traffic_summary():
    _seed(n_allowed=2, n_blocked=3)
    summary = analytics.get_traffic_summary(days=1)
    assert summary["total"] == 5
    assert summary["blocked"] == 3
    assert summary["allowed"] == 2
    assert abs(summary["block_rate"] - 0.6) < 1e-9


def test_top_offenders_orders_by_blocked():
    _seed(n_allowed=0, n_blocked=5, key="bad")
    _seed(n_allowed=0, n_blocked=2, key="meh")
    offenders = analytics.get_top_offenders(days=1)
    assert offenders[0] == {"key": "bad", "blocked_count": 5}
    assert offenders[1] == {"key": "meh", "blocked_count": 2}


def test_rule_hit_counts():
    RateLimitEvent.objects.create(
        key="k",
        rule_name="api",
        path="/a",
        method="GET",
        allowed=True,
        count=1,
        limit=5,
    )
    RateLimitEvent.objects.create(
        key="k",
        rule_name="api",
        path="/a",
        method="GET",
        allowed=False,
        count=6,
        limit=5,
    )
    rows = analytics.get_rule_hit_counts(days=1)
    assert rows[0]["rule_name"] == "api"
    assert rows[0]["hits"] == 2
    assert rows[0]["blocked"] == 1


def test_offenders_csv():
    _seed(n_allowed=0, n_blocked=4, key="bad")
    csv_text = analytics.offenders_csv(days=1)
    assert "key,blocked_count" in csv_text
    assert "bad,4" in csv_text


def test_window_excludes_old_events():
    _seed(n_allowed=0, n_blocked=3, key="recent", days_ago=0)
    _seed(n_allowed=0, n_blocked=9, key="old", days_ago=40)
    summary = analytics.get_traffic_summary(days=7)
    assert summary["blocked"] == 3  # the 40-day-old events are outside the window


# ---------------------------------------------------------------------------
# Dashboard + CSV views
# ---------------------------------------------------------------------------


def test_dashboard_staff_only():
    _seed()
    staff = User.objects.create(username="admin", is_staff=True)
    regular = User.objects.create(username="joe", is_staff=False)

    request = RequestFactory().get("/dashboard/?days=7")
    request.user = staff
    assert RateLimitDashboardView.as_view()(request).status_code == 200

    request2 = RequestFactory().get("/dashboard/")
    request2.user = regular
    assert RateLimitDashboardView.as_view()(request2).status_code == 403


def test_offenders_csv_view():
    _seed(n_allowed=0, n_blocked=2, key="bad")
    staff = User.objects.create(username="admin", is_staff=True)
    request = RequestFactory().get("/offenders.csv?days=1")
    request.user = staff
    response = offenders_csv_view(request)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert b"bad,2" in response.content


# ---------------------------------------------------------------------------
# Cleanup + admin
# ---------------------------------------------------------------------------


def test_event_cleanup_old():
    _seed(n_allowed=1, n_blocked=1, key="recent", days_ago=0)
    _seed(n_allowed=2, n_blocked=2, key="old", days_ago=40)
    deleted = RateLimitEvent.cleanup_old(older_than_days=30)
    assert deleted == 4
    assert RateLimitEvent.objects.count() == 2


def test_event_admin_registered_read_only():
    assert admin.site.is_registered(RateLimitEvent)
    event_admin = admin.site._registry[RateLimitEvent]
    assert event_admin.has_add_permission(None) is False
    assert event_admin.has_change_permission(None) is False
