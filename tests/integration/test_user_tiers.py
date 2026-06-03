"""Tests for the Phase 3 user-integration feature.

Covers tiers + assignments, per-user overrides, Django-group tier resolution,
API keys, and the middleware integration (an authenticated user is limited at
their effective tier/override rate, in their own bucket).
"""

from datetime import timedelta

import pytest

from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.utils import timezone

import django_smart_ratelimit.admin  # noqa: F401  (registers the ModelAdmins)
from django_smart_ratelimit.api_keys import (
    api_key_key,
    extract_api_key,
    get_api_key_record,
    get_api_key_tier,
)
from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.groups import get_tier_from_groups, group_key
from django_smart_ratelimit.middleware import RateLimitMiddleware
from django_smart_ratelimit.models import (
    APIKey,
    GroupRateLimit,
    UserRateLimitOverride,
    UserTier,
    UserTierAssignment,
)
from django_smart_ratelimit.tiers import (
    apply_tier_to_rate,
    get_user_override,
    get_user_tier,
    resolve_effective_user_rate,
)

pytestmark = pytest.mark.django_db


def _req(user=None, ip="203.0.113.5", path="/api/x", headers=None):
    request = RequestFactory().get(path)
    request.META["REMOTE_ADDR"] = ip
    for name, value in (headers or {}).items():
        request.META["HTTP_" + name.upper().replace("-", "_")] = value
    if user is not None:
        request.user = user
    return request


class _Anon:
    is_authenticated = False


# ---------------------------------------------------------------------------
# Tier resolution
# ---------------------------------------------------------------------------


def test_apply_tier_multiplier_and_explicit():
    tier = UserTier.objects.create(name="t", rate_multiplier=2.0)
    assert apply_tier_to_rate("10/m", tier) == "20/60s"
    tier.explicit_limits = {"api": "5000/h"}
    assert apply_tier_to_rate("10/m", tier, "api") == "5000/h"
    assert apply_tier_to_rate("10/m", None) == "10/m"  # no tier -> unchanged


def test_get_user_tier_explicit_and_expiry():
    tier = UserTier.objects.create(name="premium", rate_multiplier=2.0)
    user = User.objects.create(username="u1")
    UserTierAssignment.objects.create(user=user, tier=tier)
    assert get_user_tier(user).name == "premium"

    # expired assignment falls back (no group) to None
    user.ratelimit_tier.expires_at = timezone.now() - timedelta(hours=1)
    user.ratelimit_tier.save()
    assert get_user_tier(user) is None


def test_get_user_tier_from_groups():
    tier = UserTier.objects.create(name="vip", rate_multiplier=3.0, priority=5)
    user = User.objects.create(username="g1")
    group = Group.objects.create(name="vips")
    user.groups.add(group)
    GroupRateLimit.objects.create(group=group, tier=tier)
    assert get_tier_from_groups(user).name == "vip"
    assert get_user_tier(user).name == "vip"  # no explicit assignment -> group


def test_anonymous_user_has_no_tier():
    assert get_user_tier(_Anon()) is None
    assert get_tier_from_groups(_Anon()) is None


# ---------------------------------------------------------------------------
# Per-user overrides
# ---------------------------------------------------------------------------


def test_override_precedence_and_expiry():
    user = User.objects.create(username="o1")
    now = timezone.now()
    UserRateLimitOverride.objects.create(
        user=user, rate="999/m", expires_at=now + timedelta(hours=1)
    )
    assert get_user_override(user) == "999/m"

    # expired override is ignored
    UserRateLimitOverride.objects.update(expires_at=now - timedelta(minutes=1))
    assert get_user_override(user) is None


def test_scope_specific_override_beats_blank():
    user = User.objects.create(username="o2")
    now = timezone.now()
    UserRateLimitOverride.objects.create(
        user=user, rate="5/m", rule_name="", expires_at=now + timedelta(hours=1)
    )
    UserRateLimitOverride.objects.create(
        user=user, rate="50/m", rule_name="api", expires_at=now + timedelta(hours=1)
    )
    assert get_user_override(user, "api") == "50/m"
    assert get_user_override(user, "other") == "5/m"  # falls back to blank


def test_resolve_precedence_override_then_tier():
    tier = UserTier.objects.create(name="t", rate_multiplier=2.0)
    user = User.objects.create(username="o3")
    UserTierAssignment.objects.create(user=user, tier=tier)
    assert resolve_effective_user_rate(_req(user), "10/m") == "20/60s"  # tier
    UserRateLimitOverride.objects.create(
        user=user, rate="1/m", expires_at=timezone.now() + timedelta(hours=1)
    )
    assert resolve_effective_user_rate(_req(user), "10/m") == "1/m"  # override wins


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


def test_extract_api_key_sources():
    assert extract_api_key(_req(headers={"X-API-Key": "h"})) == "h"
    assert extract_api_key(_req(headers={"Authorization": "Bearer tok"})) == "tok"
    request = RequestFactory().get("/?api_key=q")
    assert extract_api_key(request) == "q"
    assert extract_api_key(_req()) is None


def test_api_key_record_active_inactive_and_tier():
    tier = UserTier.objects.create(name="api-tier", rate_multiplier=4.0)
    APIKey.objects.create(key="live", name="L", tier=tier, is_active=True)
    APIKey.objects.create(key="dead", name="D", is_active=False)
    assert get_api_key_record("live") is not None
    assert get_api_key_record("dead") is None
    assert get_api_key_tier(_req(headers={"X-API-Key": "live"})).name == "api-tier"

    # touch updates last_used_at
    assert get_api_key_record("live").last_used_at is None
    get_api_key_record("live", touch=True)
    assert APIKey.objects.get(key="live").last_used_at is not None


def test_api_key_key_function_and_group_key():
    assert api_key_key(_req(headers={"X-API-Key": "k"})) == "api_key:k"
    user = User.objects.create(username="grpkey")
    user.groups.add(Group.objects.create(name="g1"))
    assert group_key(_req(user)) == "group:g1"
    assert group_key(_req(_Anon())) == "group:anonymous"


# ---------------------------------------------------------------------------
# Middleware integration
# ---------------------------------------------------------------------------


@override_settings(
    RATELIMIT_USE_USER_TIERS=True,
    RATELIMIT_MIDDLEWARE={"BACKEND": "memory", "DEFAULT_RATE": "2/m"},
)
def test_middleware_premium_user_gets_higher_limit():
    clear_backend_cache()
    premium = UserTier.objects.create(name="premium", rate_multiplier=3.0)
    user = User.objects.create(username="prem")
    UserTierAssignment.objects.create(user=user, tier=premium)
    middleware = RateLimitMiddleware(lambda req: HttpResponse("ok"))

    # Base 2/m * 3 = 6/m for the premium user; the 7th is blocked.
    codes = [middleware(_req(user, path="/x")).status_code for _ in range(7)]
    assert codes.count(200) == 6
    assert codes[-1] == 429
    clear_backend_cache()


@override_settings(
    RATELIMIT_USE_USER_TIERS=True,
    RATELIMIT_MIDDLEWARE={"BACKEND": "memory", "DEFAULT_RATE": "2/m"},
)
def test_middleware_override_applies_and_per_user_bucket():
    clear_backend_cache()
    u1 = User.objects.create(username="a")
    u2 = User.objects.create(username="b")
    UserRateLimitOverride.objects.create(
        user=u1, rate="5/m", expires_at=timezone.now() + timedelta(hours=1)
    )
    middleware = RateLimitMiddleware(lambda req: HttpResponse("ok"))

    # u1 (override 5/m) and u2 (default 2/m) share an IP but have separate buckets.
    u1_codes = [
        middleware(_req(u1, ip="9.9.9.9", path="/x")).status_code for _ in range(6)
    ]
    u2_codes = [
        middleware(_req(u2, ip="9.9.9.9", path="/x")).status_code for _ in range(3)
    ]
    assert u1_codes.count(200) == 5  # override
    assert u2_codes == [200, 200, 429]  # default, independent bucket
    clear_backend_cache()


def test_admin_registrations():
    for model in (
        UserTier,
        UserTierAssignment,
        GroupRateLimit,
        UserRateLimitOverride,
        APIKey,
    ):
        assert admin.site.is_registered(model)
