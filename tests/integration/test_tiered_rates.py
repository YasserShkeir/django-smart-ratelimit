"""Tests for tier-based rates: tiered() + callable @rate_limit rate (roadmap #76)."""

import time

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import RequestFactory

from django_smart_ratelimit import rate_limit, tiered
from django_smart_ratelimit.backends import clear_backend_cache, get_backend


class _User:
    is_authenticated = True

    def __init__(self, plan):
        self.plan = plan


def _req(plan=None, ip="203.0.113.5"):
    request = RequestFactory().get("/")
    request.META["REMOTE_ADDR"] = ip
    if plan is not None:
        request.user = _User(plan)
    return request


# ---------------------------------------------------------------------------
# tiered() resolution
# ---------------------------------------------------------------------------


def test_tiered_by_attribute_path():
    fn = tiered({"free": "100/h", "pro": "10000/h"}, by="user.plan", default="100/h")
    assert fn(_req(plan="pro")) == "10000/h"
    assert fn(_req(plan="free")) == "100/h"


def test_tiered_by_callable():
    fn = tiered({"a": "1/m", "b": "2/m"}, by=lambda r: r.headers.get("X-Tier"))
    req = RequestFactory().get("/")
    req.META["HTTP_X_TIER"] = "b"
    assert fn(req) == "2/m"


def test_tiered_wildcard_and_default():
    # "*" wildcard covers unlisted tiers.
    fn = tiered({"pro": "1000/h", "*": "50/h"}, by="user.plan")
    assert fn(_req(plan="enterprise")) == "50/h"
    # default covers a missing tier when there's no "*".
    fn2 = tiered({"pro": "1000/h"}, by="user.plan", default="10/h")
    assert fn2(_req(plan="free")) == "10/h"
    assert fn2(_req()) == "10/h"  # no user.plan at all


def test_tiered_raises_without_match_or_default():
    fn = tiered({"pro": "1000/h"}, by="user.plan")
    with pytest.raises(ImproperlyConfigured):
        fn(_req(plan="free"))


# ---------------------------------------------------------------------------
# Decorator with a callable / tiered rate
# ---------------------------------------------------------------------------


def _uid():
    return time.time_ns()


def test_decorator_tiered_rate_enforced_per_plan():
    clear_backend_cache()
    get_backend("memory")
    bucket = _uid()

    @rate_limit(
        key=lambda r, *a, **k: f"u:{r.user.plan}:{bucket}",
        rate=tiered({"free": "2/m", "pro": "5/m"}, by="user.plan", default="2/m"),
        algorithm="fixed_window",
        backend="memory",
    )
    def view(_request):
        return HttpResponse("ok")

    free = [view(_req(plan="free")).status_code for _ in range(4)]
    pro = [view(_req(plan="pro")).status_code for _ in range(7)]
    assert free == [200, 200, 429, 429]
    assert pro == [200, 200, 200, 200, 200, 429, 429]
    clear_backend_cache()


def test_decorator_plain_callable_rate():
    clear_backend_cache()
    get_backend("memory")
    bucket = _uid()

    @rate_limit(
        key=lambda r, *a, **k: f"c:{bucket}",
        rate=lambda r, *a, **k: "3/m",
        algorithm="fixed_window",
        backend="memory",
    )
    def view(_request):
        return HttpResponse("ok")

    codes = [view(_req(ip="9.9.9.9")).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    clear_backend_cache()


@pytest.mark.asyncio
async def test_decorator_tiered_rate_async():
    clear_backend_cache()
    get_backend("memory")
    bucket = _uid()

    @rate_limit(
        key=lambda r, *a, **k: f"a:{r.user.plan}:{bucket}",
        rate=tiered({"free": "1/m", "pro": "3/m"}, by="user.plan", default="1/m"),
        algorithm="fixed_window",
        backend="memory",
    )
    async def view(_request):
        return HttpResponse("ok")

    free = []
    for _ in range(2):
        free.append((await view(_req(plan="free"))).status_code)
    pro = []
    for _ in range(4):
        pro.append((await view(_req(plan="pro"))).status_code)
    assert free == [200, 429]
    assert pro == [200, 200, 200, 429]
    clear_backend_cache()
