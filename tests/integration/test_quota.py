"""Tests for quota management (cumulative long-horizon usage; roadmap #76)."""

from datetime import timedelta

import pytest

from django.contrib import admin
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

import django_smart_ratelimit.admin  # noqa: F401  (registers QuotaAdmin)
from django_smart_ratelimit import (
    consume_quota,
    get_quota_usage,
    quota,
    reset_quota,
)
from django_smart_ratelimit.models import Quota
from django_smart_ratelimit.quota import _period_bounds

pytestmark = pytest.mark.django_db


def _req(ip="203.0.113.5"):
    request = RequestFactory().get("/")
    request.META["REMOTE_ADDR"] = ip
    return request


# ---------------------------------------------------------------------------
# Period bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "period,days",
    [("day", 1), ("week", 7), ("year", 365), ("30d", 30), (7, 7)],
)
def test_period_bounds_span(period, days):
    start, reset = _period_bounds(period, timezone.now())
    assert round((reset - start).total_seconds() / 86400) == days


def test_period_bounds_month_is_calendar_aligned():
    start, reset = _period_bounds("month", timezone.now())
    assert start.day == 1 and reset.day == 1
    assert reset > start


def test_invalid_period_raises():
    with pytest.raises(ValueError):
        _period_bounds("0d", timezone.now())


# ---------------------------------------------------------------------------
# consume_quota
# ---------------------------------------------------------------------------


def test_consume_allows_up_to_limit_then_blocks():
    results = [consume_quota("user:1", 3, "month")[0] for _ in range(5)]
    assert results == [True, True, True, False, False]
    # The denied requests did not over-charge usage.
    assert Quota.objects.get(key="user:1").used == 3


def test_consume_reports_usage_info():
    _, info = consume_quota("user:2", 10, "month", cost=4)
    assert info["used"] == 4
    assert info["limit"] == 10
    assert info["remaining"] == 6
    assert info["period"] == "month"


def test_consume_scopes_are_independent():
    consume_quota("user:3", 1, "month", scope="export")
    # A different scope has its own counter.
    assert consume_quota("user:3", 1, "month", scope="upload")[0] is True
    assert consume_quota("user:3", 1, "month", scope="export")[0] is False


def test_consume_rolls_over_when_period_elapses():
    consume_quota("user:4", 2, "month")
    consume_quota("user:4", 2, "month")
    assert consume_quota("user:4", 2, "month")[0] is False  # at limit
    # Force the reset time into the past, as if a new month started.
    Quota.objects.filter(key="user:4").update(
        reset_at=timezone.now() - timedelta(days=1)
    )
    allowed, info = consume_quota("user:4", 2, "month")
    assert allowed is True and info["used"] == 1


def test_consume_cost_greater_than_one():
    allowed, info = consume_quota("user:5", 5, "month", cost=5)
    assert allowed is True and info["remaining"] == 0
    assert consume_quota("user:5", 5, "month", cost=1)[0] is False


# ---------------------------------------------------------------------------
# Introspection + reset
# ---------------------------------------------------------------------------


def test_get_quota_usage_none_when_unused():
    assert get_quota_usage("never:seen") is None


def test_get_quota_usage_reports_zero_after_reset():
    consume_quota("user:6", 5, "month")
    Quota.objects.filter(key="user:6").update(
        reset_at=timezone.now() - timedelta(days=1)
    )
    # Past the reset time, introspection reports a fresh window.
    assert get_quota_usage("user:6")["used"] == 0


def test_reset_quota_clears_usage():
    consume_quota("user:7", 5, "month")
    reset_quota("user:7")
    assert get_quota_usage("user:7") is None


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def test_decorator_blocks_over_quota():
    @quota(key="ip", limit=3, period="month")
    def view(_request):
        return HttpResponse("ok")

    codes = [view(_req(ip="1.2.3.4")).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_decorator_non_block_passes_through():
    @quota(key="ip", limit=1, period="month", block=False)
    def view(_request):
        return HttpResponse("ok")

    codes = [view(_req(ip="5.6.7.8")).status_code for _ in range(3)]
    assert codes == [200, 200, 200]  # never blocks, just tracks


def test_decorator_callable_key_and_cost():
    @quota(
        key=lambda r, *a, **k: f"team:{r.headers.get('X-Team', 'none')}",
        limit=10,
        period="month",
        cost=lambda r: 5,
    )
    def view(_request):
        return HttpResponse("ok")

    def call(team):
        req = RequestFactory().get("/")
        req.META["HTTP_X_TEAM"] = team
        return view(req).status_code

    # cost 5 each, limit 10 -> two allowed, third blocked, per team.
    assert [call("a") for _ in range(3)] == [200, 200, 429]
    assert call("b") == 200  # separate team, fresh quota


@pytest.mark.asyncio
async def test_decorator_async():
    @quota(key="ip", limit=2, period="month")
    async def view(_request):
        return HttpResponse("ok")

    codes = []
    for _ in range(3):
        resp = await view(_req(ip="9.9.9.9"))
        codes.append(resp.status_code)
    assert codes == [200, 200, 429]


def test_admin_registered():
    assert admin.site.is_registered(Quota)
