"""Phase 3 completion (v4.6.0): decorator-level tiers/overrides + helpers.

Covers the `@rate_limit` decorator honoring `RATELIMIT_USE_USER_TIERS` (so the
decorator reaches parity with the middleware), the `tier_key` key function, and
the `create_user_override` programmatic helper.
"""

from datetime import timedelta

import pytest

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.utils import timezone

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.models import (
    UserRateLimitOverride,
    UserTier,
    UserTierAssignment,
)
from django_smart_ratelimit.tiers import (
    create_user_override,
    get_user_override,
    tier_key,
)

pytestmark = pytest.mark.django_db


def _req(user=None, ip="203.0.113.5", path="/api/x"):
    request = RequestFactory().get(path)
    request.META["REMOTE_ADDR"] = ip
    if user is not None:
        request.user = user
    return request


class _Anon:
    is_authenticated = False
    pk = None


# ---------------------------------------------------------------------------
# 3.3.2 decorator honors tiers/overrides
# ---------------------------------------------------------------------------


@override_settings(RATELIMIT_USE_USER_TIERS=True)
def test_decorator_premium_user_gets_higher_limit():
    clear_backend_cache()
    premium = UserTier.objects.create(name="premium", rate_multiplier=3.0)
    user = User.objects.create(username="dprem")
    UserTierAssignment.objects.create(user=user, tier=premium)

    @rate_limit(key="ip", rate="2/m", backend="memory")
    def view(request):
        return HttpResponse("ok")

    # Base 2/m * 3 = 6/m for the premium user; the 7th is blocked.
    codes = [view(_req(user, ip="7.7.7.7")).status_code for _ in range(7)]
    assert codes.count(200) == 6
    assert codes[-1] == 429
    clear_backend_cache()


@override_settings(RATELIMIT_USE_USER_TIERS=True)
def test_decorator_override_applies_and_per_user_bucket():
    clear_backend_cache()
    u1 = User.objects.create(username="da")
    u2 = User.objects.create(username="db")
    UserRateLimitOverride.objects.create(
        user=u1, rate="5/m", expires_at=timezone.now() + timedelta(hours=1)
    )

    @rate_limit(key="ip", rate="2/m", backend="memory")
    def view(request):
        return HttpResponse("ok")

    # u1 (override 5/m) and u2 (default 2/m) share an IP but bucket separately.
    u1_codes = [view(_req(u1, ip="8.8.8.8")).status_code for _ in range(6)]
    u2_codes = [view(_req(u2, ip="8.8.8.8")).status_code for _ in range(3)]
    assert u1_codes.count(200) == 5
    assert u2_codes == [200, 200, 429]
    clear_backend_cache()


@override_settings(RATELIMIT_USE_USER_TIERS=True)
def test_decorator_anonymous_unaffected_by_tiers():
    clear_backend_cache()

    @rate_limit(key="ip", rate="2/m", backend="memory")
    def view(request):
        return HttpResponse("ok")

    codes = [view(_req(_Anon(), ip="6.6.6.6")).status_code for _ in range(3)]
    assert codes == [200, 200, 429]  # plain base rate
    clear_backend_cache()


def test_decorator_no_tiers_setting_is_noop():
    # With the setting off (default), the decorator ignores tiers entirely.
    clear_backend_cache()
    premium = UserTier.objects.create(name="premium2", rate_multiplier=5.0)
    user = User.objects.create(username="dnoop")
    UserTierAssignment.objects.create(user=user, tier=premium)

    @rate_limit(key="ip", rate="2/m", backend="memory")
    def view(request):
        return HttpResponse("ok")

    codes = [view(_req(user, ip="5.5.5.4")).status_code for _ in range(3)]
    assert codes == [200, 200, 429]  # base 2/m, tier ignored
    clear_backend_cache()


# ---------------------------------------------------------------------------
# 3.1.4 tier_key key function
# ---------------------------------------------------------------------------


def test_tier_key():
    assert tier_key(_req(_Anon())) == "tier:anonymous"
    plain = User.objects.create(username="plain")
    assert tier_key(_req(plain)) == "tier:default"
    gold = UserTier.objects.create(name="gold", rate_multiplier=2.0)
    vip = User.objects.create(username="vip")
    UserTierAssignment.objects.create(user=vip, tier=gold)
    assert tier_key(_req(vip)) == "tier:gold"


# ---------------------------------------------------------------------------
# 3.3.4 programmatic override creation
# ---------------------------------------------------------------------------


def test_create_user_override_defaults_and_lookup():
    user = User.objects.create(username="ovr")
    override = create_user_override(user, "50/h", reason="support ticket")
    assert override.rate == "50/h"
    assert override.reason == "support ticket"
    # Active immediately, expires ~1h out by default.
    assert get_user_override(user) == "50/h"
    delta = override.expires_at - override.starts_at
    assert abs(delta.total_seconds() - 3600) < 5


def test_create_user_override_scope_and_duration():
    user = User.objects.create(username="ovr2")
    create_user_override(user, "10/m", scope="upload", duration_seconds=60)
    assert get_user_override(user, scope="upload") == "10/m"
    assert get_user_override(user, scope="other") is None  # scoped, no blanket


def test_create_user_override_rejects_bad_rate():
    user = User.objects.create(username="ovr3")
    with pytest.raises(ValidationError):
        create_user_override(user, "not-a-rate")
