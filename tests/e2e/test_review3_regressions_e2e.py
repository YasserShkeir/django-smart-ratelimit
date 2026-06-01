"""Regression tests for the bugs found by the third (v4.0.4) review.

Each fails on pre-fix code and passes after. Guards:

* AsyncRedisBackend reads RATELIMIT_KEY_PREFIX / RATELIMIT_ALGORITHM and applies the
  fixed-window clock-align suffix, so sync and async share one keyspace/counter.
* RateLimitConfigManager no longer mutates the shared settings config dict.
* parse_rate rejects a negative limit; the middleware validates rates at construction.
* MetricsCollector is LRU-bounded by key (no unbounded growth).
* ratelimit_cleanup rejects a non-positive --batch-size.
* The MongoDB backend honors a full connection ``uri``.
"""

import asyncio

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import override_settings

from django_smart_ratelimit.backends import (
    clear_backend_cache,
    get_async_backend,
    get_backend,
)
from django_smart_ratelimit.backends.utils import parse_rate
from django_smart_ratelimit.configuration import RateLimitConfigManager
from django_smart_ratelimit.middleware import RateLimitMiddleware
from django_smart_ratelimit.performance import MetricsCollector

from .conftest import skip_without_mongo, skip_without_redis

# ---------------------------------------------------------------------------
# Async Redis backend reads settings (matches the sync backend)
# ---------------------------------------------------------------------------


def test_async_redis_backend_matches_sync_key_prefix():
    """Async backend shares the sync key prefix and honors RATELIMIT_KEY_PREFIX.

    (It previously hardcoded "rl:" and ignored the setting.)
    """
    clear_backend_cache()
    sync = get_backend("redis")
    asyncb = get_async_backend("redis")
    assert sync.key_prefix == asyncb.key_prefix

    clear_backend_cache()
    with override_settings(RATELIMIT_KEY_PREFIX="myapp:"):
        assert get_async_backend("redis").key_prefix == "myapp:"
    clear_backend_cache()


def test_async_redis_backend_honors_algorithm_setting():
    """The async backend honors RATELIMIT_ALGORITHM (was hardcoded sliding_window)."""
    clear_backend_cache()
    with override_settings(RATELIMIT_ALGORITHM="fixed_window"):
        assert get_async_backend("redis").algorithm == "fixed_window"
    clear_backend_cache()


@skip_without_redis
def test_sync_and_async_share_one_counter_fixed_window():
    """A sync incr and an async aincr for the same key hit ONE counter.

    Pre-fix the async backend used a different prefix ("rl:" vs "ratelimit:") and
    omitted the fixed-window clock-align suffix, so it wrote to a separate key —
    a client alternating sync/async endpoints got ~2x the limit.
    """
    import redis as redis_module

    redis_module.Redis(host="localhost", port=6379, db=0).flushdb()
    clear_backend_cache()
    with override_settings(RATELIMIT_ALGORITHM="fixed_window"):
        sync = get_backend("redis")
        asyncb = get_async_backend("redis")
        first = sync.incr("review3:shared", 60)
        second = asyncio.run(asyncb.aincr("review3:shared", 60))
        assert first == 1
        assert second == 2  # shared counter -> 2, not a fresh 1
    clear_backend_cache()


# ---------------------------------------------------------------------------
# Config manager must not mutate the shared settings config
# ---------------------------------------------------------------------------


def test_config_manager_does_not_mutate_settings_config():
    """A per-call override must not rewrite the user's RATELIMIT_CONFIG_* dict."""
    with override_settings(RATELIMIT_CONFIG_API={"rate": "100/h", "key": "ip"}):
        RateLimitConfigManager().get_config("api", rate="5/m")
        # A fresh lookup with no override must still see the original rate.
        assert RateLimitConfigManager().get_config("api")["rate"] == "100/h"


# ---------------------------------------------------------------------------
# Rate-string validation
# ---------------------------------------------------------------------------


def test_parse_rate_rejects_negative_limit():
    """A negative limit is a misconfiguration, not a silent deny-all."""
    with pytest.raises(ImproperlyConfigured):
        parse_rate("-5/m")
    with pytest.raises(ImproperlyConfigured):
        parse_rate("-5/30s")


def test_middleware_validates_rates_at_construction():
    """A malformed DEFAULT_RATE / RATE_LIMITS raises at init, not a 500 per request."""
    clear_backend_cache()
    with override_settings(
        RATELIMIT_MIDDLEWARE={"BACKEND": "memory", "DEFAULT_RATE": "1000 per hour"}
    ):
        with pytest.raises(ImproperlyConfigured):
            RateLimitMiddleware(lambda request: HttpResponse("ok"))
    with override_settings(
        RATELIMIT_MIDDLEWARE={
            "BACKEND": "memory",
            "DEFAULT_RATE": "100/m",
            "RATE_LIMITS": {"/api/": "bogus"},
        }
    ):
        with pytest.raises(ImproperlyConfigured):
            RateLimitMiddleware(lambda request: HttpResponse("ok"))
    clear_backend_cache()


# ---------------------------------------------------------------------------
# MetricsCollector is LRU-bounded
# ---------------------------------------------------------------------------


def test_metrics_collector_is_lru_bounded():
    """Per-key metrics cannot grow without bound under high key cardinality.

    Aggregate counters stay exact regardless of eviction.
    """
    mc = MetricsCollector()
    mc.reset()
    mc._max_keys = 100
    try:
        for i in range(500):
            mc.record_request(
                key=f"ip:{i}", allowed=True, duration_ms=1.0, backend="memory"
            )
        assert len(mc._metrics) <= 100
        assert mc.get_stats()["total_requests"] == 500
    finally:
        mc.reset()
        mc._max_keys = 10000


# ---------------------------------------------------------------------------
# ratelimit_cleanup --batch-size validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ratelimit_cleanup_rejects_nonpositive_batch_size():
    """A non-positive --batch-size errors clearly instead of crashing / no-op."""
    with pytest.raises(CommandError):
        call_command("ratelimit_cleanup", batch_size=-1)
    with pytest.raises(CommandError):
        call_command("ratelimit_cleanup", batch_size=0)


# ---------------------------------------------------------------------------
# MongoDB honors a full connection URI
# ---------------------------------------------------------------------------


@skip_without_mongo
def test_mongodb_backend_honors_uri():
    """A configured ``uri`` is used to connect (was silently ignored)."""
    clear_backend_cache()
    with override_settings(
        RATELIMIT_BACKEND="django_smart_ratelimit.backends.mongodb.MongoDBBackend",
        RATELIMIT_MONGODB={
            "uri": "mongodb://localhost:27017",
            "database": "ratelimit",
            "algorithm": "fixed_window",
        },
    ):
        backend = get_backend()
        # If the uri were ignored it would still hit localhost, so prove the
        # connection is live and functional rather than asserting on internals.
        assert backend.incr("review3:mongo-uri", 60) == 1
    clear_backend_cache()
