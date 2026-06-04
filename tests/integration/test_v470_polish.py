"""v4.7.0 polish: top-level re-exports + async-native Redis leaky bucket."""

import time

import pytest

# ---------------------------------------------------------------------------
# Discoverability: v4.x feature symbols are re-exported at the package top level
# ---------------------------------------------------------------------------


def test_v4x_features_are_top_level_exports():
    import django_smart_ratelimit as d

    expected = [
        # dynamic rules
        "RuleEngine",
        "rule_engine",
        "get_rule_engine",
        # tiers / groups / overrides / api keys
        "get_user_tier",
        "tier_key",
        "create_user_override",
        "get_tier_from_groups",
        "group_key",
        "extract_api_key",
        "api_key_key",
        "get_api_key_tier",
        # analytics
        "get_traffic_summary",
        "get_top_offenders",
        "get_offender_detail",
        "find_alertable_offenders",
        "send_offender_alerts",
        # geo / tenant / graphql
        "geo_key",
        "get_rate_for_country",
        "GeoProvider",
        "extract_tenant",
        "tenant_key",
        "resolve_tenant_rate",
        "GrapheneRateLimitMiddleware",
        "estimate_query_complexity",
        # statsd
        "StatsDClient",
        "StatsDMetrics",
        "get_statsd_metrics",
    ]
    missing = [s for s in expected if not hasattr(d, s)]
    assert missing == [], f"not re-exported: {missing}"
    # every name is also advertised in __all__
    not_in_all = [s for s in expected if s not in d.__all__]
    assert not_in_all == [], f"missing from __all__: {not_in_all}"


def test_reexports_are_the_same_objects_as_submodules():
    import django_smart_ratelimit as d
    from django_smart_ratelimit import analytics, geo, tenants, tiers

    assert d.geo_key is geo.geo_key
    assert d.tenant_key is tenants.tenant_key
    assert d.tier_key is tiers.tier_key
    assert d.get_traffic_summary is analytics.get_traffic_summary


def test_no_dangling_all_names():
    import django_smart_ratelimit as d

    dangling = [n for n in d.__all__ if not hasattr(d, n)]
    assert dangling == [], f"__all__ lists names that don't resolve: {dangling}"


# ---------------------------------------------------------------------------
# Async-native Redis leaky bucket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_redis_leaky_bucket_atomic():
    from django_smart_ratelimit.backends.redis_backend import AsyncRedisBackend

    backend = AsyncRedisBackend()
    key = "albtest:v470:%d" % int(time.time() * 1000)
    # capacity 4, negligible leak during the test -> exactly 4 admitted.
    decisions = []
    for _ in range(6):
        allowed, meta = await backend.aleaky_bucket_check(key, 4, 0.0001, 1)
        decisions.append(allowed)
    assert decisions == [True, True, True, True, False, False]

    info = await backend.aleaky_bucket_info(key, 4, 0.0001)
    assert info["bucket_level"] > 3.0  # near full, read-only (no mutation)
    assert info["space_remaining"] < 1.0


@pytest.mark.asyncio
async def test_async_redis_leaky_bucket_leaks_over_time():
    import asyncio

    from django_smart_ratelimit.backends.redis_backend import AsyncRedisBackend

    backend = AsyncRedisBackend()
    key = "albtest2:v470:%d" % int(time.time() * 1000)
    # Fill to capacity (cost 2 == capacity 2), then it's immediately full.
    await backend.aleaky_bucket_check(key, 2, 100.0, 2)
    denied, _ = await backend.aleaky_bucket_check(key, 2, 100.0, 2)
    assert denied is False
    # leak_rate 100/s drains the bucket within 0.1s.
    await asyncio.sleep(0.1)
    allowed, _ = await backend.aleaky_bucket_check(key, 2, 100.0, 2)
    assert allowed is True
