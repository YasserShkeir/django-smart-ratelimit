"""Tests for Phase 5.4-5.6: geographic, multi-tenant, and GraphQL rate limiting.

External providers (geoip2 / graphene / strawberry) are optional and not required
here: geo uses a fake provider, GraphQL uses a duck-typed info/next.
"""

import pytest

from django.contrib import admin
from django.test import RequestFactory

import django_smart_ratelimit.admin  # noqa: F401
from django_smart_ratelimit import geo, graphql, tenants
from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.models import TenantQuota


def _req(ip="203.0.113.5", headers=None, host=None):
    request = RequestFactory().get("/")
    request.META["REMOTE_ADDR"] = ip
    for name, value in (headers or {}).items():
        request.META["HTTP_" + name.upper().replace("-", "_")] = value
    if host:
        request.META["HTTP_HOST"] = host
    return request


class _Anon:
    is_authenticated = False


# ---------------------------------------------------------------------------
# 5.4 Geographic
# ---------------------------------------------------------------------------


class _FakeGeo(geo.GeoProvider):
    def lookup(self, ip):
        return geo.GeoLocation(country="CN" if ip.startswith("1.") else "US")


def test_geo_key_and_country(monkeypatch):
    geo.set_geo_provider(_FakeGeo())
    try:
        assert geo.geo_key(_req(ip="8.8.8.8")) == "geo:US"
        assert geo.geo_key(_req(ip="1.2.3.4")) == "geo:CN"
        assert geo.get_country("1.2.3.4") == "CN"
    finally:
        geo.set_geo_provider(None)


def test_null_provider_returns_unknown():
    geo.set_geo_provider(geo.NullGeoProvider())
    try:
        assert geo.geo_key(_req(ip="8.8.8.8")) == "geo:unknown"
        assert geo.get_country("8.8.8.8") is None
    finally:
        geo.set_geo_provider(None)


def test_rate_for_country():
    rates = {"CN": "10/h", "US": "1000/h", "*": "50/h"}
    assert geo.get_rate_for_country("CN", rates, "100/h") == "10/h"
    assert geo.get_rate_for_country("DE", rates, "100/h") == "50/h"  # wildcard
    assert geo.get_rate_for_country("DE", {"CN": "10/h"}, "100/h") == "100/h"  # default
    assert geo.get_rate_for_country(None, {}, "100/h") == "100/h"


# ---------------------------------------------------------------------------
# 5.5 Multi-tenant
# ---------------------------------------------------------------------------


def test_extract_tenant_sources():
    assert tenants.extract_tenant(_req(headers={"X-Tenant-ID": "acme"})) == "acme"
    assert tenants.extract_tenant(_req(host="sub.example.com")) == "sub"
    assert tenants.extract_tenant(_req(host="example.com")) is None  # no subdomain
    assert tenants.extract_tenant(_req()) is None


def test_tenant_key():
    assert tenants.tenant_key(_req(headers={"X-Tenant-ID": "acme"})) == "tenant:acme"
    assert tenants.tenant_key(_req()) == "tenant:default"


@pytest.mark.django_db
def test_tenant_quota_resolution():
    TenantQuota.objects.create(tenant_id="acme", rate="500/h")
    assert tenants.get_tenant_quota("acme") == "500/h"
    assert tenants.get_tenant_quota("ghost") is None
    req = _req(headers={"X-Tenant-ID": "acme"})
    assert tenants.resolve_tenant_rate(req, "100/m") == "500/h"
    assert tenants.resolve_tenant_rate(_req(), "100/m") == "100/m"


@pytest.mark.django_db
def test_tenant_quota_validates_rate():
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        TenantQuota(tenant_id="bad", rate="nope").save()


# ---------------------------------------------------------------------------
# 5.6 GraphQL
# ---------------------------------------------------------------------------


def test_estimate_query_complexity():
    assert graphql.estimate_query_complexity("") == 1
    simple = graphql.estimate_query_complexity("{ user { id } }")
    nested = graphql.estimate_query_complexity("query { a { b { c d } } posts { t } }")
    assert nested > simple >= 1


@pytest.mark.django_db
def test_graphene_middleware_limits_top_level_operations():
    from django_smart_ratelimit.backends import get_backend

    clear_backend_cache()
    # The default test backend is the shared live Redis; clear this key's state
    # so the count starts at zero regardless of prior runs.
    get_backend().reset("graphql:ip:5.5.5.5")
    middleware = graphql.GrapheneRateLimitMiddleware(rate="2/m")

    class _Info:
        def __init__(self, request):
            self.context = request

    request = _req(ip="5.5.5.5")

    def _next(root, info, **args):
        return "ok"

    results = []
    for _ in range(4):
        try:
            results.append(middleware.resolve(_next, None, _Info(request)))
        except graphql.GraphQLRateLimitExceeded:
            results.append("LIMITED")
    assert results == ["ok", "ok", "LIMITED", "LIMITED"]
    clear_backend_cache()


@pytest.mark.django_db
def test_graphene_middleware_ignores_nested_resolvers():
    clear_backend_cache()
    middleware = graphql.GrapheneRateLimitMiddleware(rate="1/m")

    class _Info:
        context = _req(ip="6.6.6.6")

    def _next(root, info, **args):
        return "child"

    # root is not None -> a nested resolver -> never counted/limited.
    for _ in range(5):
        assert middleware.resolve(_next, object(), _Info()) == "child"
    clear_backend_cache()


def test_tenant_and_geo_admin_registered():
    assert admin.site.is_registered(TenantQuota)
