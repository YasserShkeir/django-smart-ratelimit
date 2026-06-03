"""Tests for the Phase 2 dynamic rate-limit rules feature.

Covers the RateLimitRule model + validation, the RuleEngine (matching, caching,
invalidation), the middleware integration (a matching DB rule overrides the
static config; hot reload), the admin actions, and the reload command.
"""

import pytest

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

import django_smart_ratelimit.admin  # noqa: F401  (registers the ModelAdmins)
from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.middleware import RateLimitMiddleware
from django_smart_ratelimit.models import RateLimitCounter, RateLimitRule
from django_smart_ratelimit.rules import RuleEngine, rule_engine

pytestmark = pytest.mark.django_db


def _req(path="/api/x", method="GET", ip="203.0.113.5"):
    request = RequestFactory().generic(method, path)
    request.META["REMOTE_ADDR"] = ip
    return request


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_rule_creation_and_methods():
    rule = RateLimitRule.objects.create(
        name="api", path_pattern=r"^/api/", rate="100/m", key="ip", priority=5
    )
    assert str(rule).startswith("api")
    assert rule.methods() == ["ALL"]
    rule.method = "GET, POST"
    assert rule.methods() == ["GET", "POST"]


def test_rule_name_uniqueness():
    RateLimitRule.objects.create(name="dup", path_pattern="^/a", rate="1/m")
    with pytest.raises(Exception):
        RateLimitRule.objects.create(name="dup", path_pattern="^/b", rate="1/m")


def test_rule_rejects_invalid_rate():
    with pytest.raises(ValidationError) as exc:
        RateLimitRule(name="r", path_pattern="^/a", rate="not-a-rate").save()
    assert "rate" in exc.value.message_dict


def test_rule_rejects_invalid_regex():
    with pytest.raises(ValidationError) as exc:
        RateLimitRule(name="r", path_pattern="[unclosed", rate="5/m").save()
    assert "path_pattern" in exc.value.message_dict


def test_rule_priority_ordering():
    RateLimitRule.objects.create(name="low", path_pattern="^/", rate="1/m", priority=1)
    RateLimitRule.objects.create(name="high", path_pattern="^/", rate="1/m", priority=9)
    names = list(RateLimitRule.objects.values_list("name", flat=True))
    assert names == ["high", "low"]  # -priority ordering


# ---------------------------------------------------------------------------
# RuleEngine
# ---------------------------------------------------------------------------


def test_engine_matches_path_and_method():
    engine = RuleEngine(cache_timeout=0)
    RateLimitRule.objects.create(
        name="post-only", path_pattern=r"^/api/", method="POST", rate="1/m"
    )
    assert engine.get_rule_for_request(_req("/api/x", "POST")) is not None
    assert engine.get_rule_for_request(_req("/api/x", "GET")) is None
    assert engine.get_rule_for_request(_req("/other", "POST")) is None


def test_engine_returns_highest_priority_match():
    engine = RuleEngine(cache_timeout=0)
    RateLimitRule.objects.create(
        name="lo", path_pattern="^/api/", rate="9/m", priority=1
    )
    RateLimitRule.objects.create(
        name="hi", path_pattern="^/api/", rate="1/m", priority=9
    )
    rule = engine.get_rule_for_request(_req("/api/x"))
    assert rule.name == "hi"


def test_engine_ignores_inactive_rules():
    engine = RuleEngine(cache_timeout=0)
    RateLimitRule.objects.create(
        name="off", path_pattern="^/api/", rate="1/m", is_active=False
    )
    assert engine.get_rule_for_request(_req("/api/x")) is None


def test_engine_cache_invalidates_on_save_and_delete():
    engine = RuleEngine(cache_timeout=300)  # long TTL -> rely on invalidation
    engine.invalidate_cache()
    assert engine.get_rule_for_request(_req("/api/x")) is None
    rule = RateLimitRule.objects.create(name="r", path_pattern="^/api/", rate="1/m")
    engine.invalidate_cache()  # save signal targets the singleton; force here
    assert engine.get_rule_for_request(_req("/api/x")) is not None
    rule.delete()
    engine.invalidate_cache()
    assert engine.get_rule_for_request(_req("/api/x")) is None


# ---------------------------------------------------------------------------
# Middleware integration
# ---------------------------------------------------------------------------


@override_settings(
    RATELIMIT_USE_DYNAMIC_RULES=True,
    RATELIMIT_MIDDLEWARE={"BACKEND": "memory", "DEFAULT_RATE": "1000/m"},
)
def test_middleware_applies_matching_rule_and_falls_back():
    clear_backend_cache()
    rule_engine.invalidate_cache()
    RateLimitRule.objects.create(
        name="api-strict", path_pattern=r"^/api/", rate="2/m", key="ip", priority=10
    )
    middleware = RateLimitMiddleware(lambda req: HttpResponse("ok"))

    api = [middleware(_req("/api/x", ip="9.9.9.9")).status_code for _ in range(4)]
    other = [middleware(_req("/other", ip="9.9.9.9")).status_code for _ in range(4)]
    assert api == [200, 200, 429, 429]  # rule's 2/m enforced
    assert other == [200, 200, 200, 200]  # default 1000/m
    clear_backend_cache()


@override_settings(
    RATELIMIT_USE_DYNAMIC_RULES=True,
    RATELIMIT_MIDDLEWARE={"BACKEND": "memory", "DEFAULT_RATE": "1000/m"},
)
def test_middleware_rule_hot_reload():
    clear_backend_cache()
    rule_engine.invalidate_cache()
    rule = RateLimitRule.objects.create(
        name="r", path_pattern=r"^/api/", rate="2/m", priority=5
    )
    middleware = RateLimitMiddleware(lambda req: HttpResponse("ok"))
    assert [middleware(_req("/api/a", ip="1.1.1.1")).status_code for _ in range(3)] == [
        200,
        200,
        429,
    ]
    # Raise the limit at runtime; the save signal invalidates the cache.
    rule.rate = "10/m"
    rule.save()
    assert middleware(_req("/api/a", ip="2.2.2.2")).status_code == 200
    clear_backend_cache()


@override_settings(
    RATELIMIT_USE_DYNAMIC_RULES=True,
    RATELIMIT_MIDDLEWARE={"BACKEND": "memory", "DEFAULT_RATE": "1000/m"},
)
def test_middleware_rule_block_false_does_not_enforce():
    clear_backend_cache()
    rule_engine.invalidate_cache()
    RateLimitRule.objects.create(
        name="soft", path_pattern=r"^/api/", rate="1/m", block=False
    )
    middleware = RateLimitMiddleware(lambda req: HttpResponse("ok"))
    codes = [middleware(_req("/api/x", ip="3.3.3.3")).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 200]  # over limit but block=False
    clear_backend_cache()


# ---------------------------------------------------------------------------
# Admin + management command
# ---------------------------------------------------------------------------


def test_admin_registrations_and_bulk_actions():
    assert admin.site.is_registered(RateLimitRule)
    assert admin.site.is_registered(RateLimitCounter)

    rule_admin = admin.site._registry[RateLimitRule]
    r1 = RateLimitRule.objects.create(name="a", path_pattern="^/a", rate="1/m")
    r2 = RateLimitRule.objects.create(name="b", path_pattern="^/b", rate="1/m")

    class _Req:
        def __init__(self):
            self._messages = []

    fake = _Req()
    rule_admin.message_user = lambda req, msg, *a, **k: req._messages.append(msg)
    rule_admin.disable_rules(fake, RateLimitRule.objects.filter(name__in=["a", "b"]))
    r1.refresh_from_db()
    r2.refresh_from_db()
    assert not r1.is_active and not r2.is_active

    # Counter admin is read-only.
    counter_admin = admin.site._registry[RateLimitCounter]
    assert counter_admin.has_add_permission(None) is False
    assert counter_admin.has_change_permission(None) is False


def test_reload_rules_command():
    RateLimitRule.objects.create(name="x", path_pattern="^/x", rate="1/m")
    call_command("ratelimit_reload_rules")  # should not raise
