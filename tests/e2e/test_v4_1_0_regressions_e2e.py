"""Regression tests for the v4.1.0 Tier 1-4 fixes.

Grouped by phase; each test fails on pre-fix code and passes after.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from django.http import HttpResponse
from django.test import override_settings

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.enums import Algorithm
from django_smart_ratelimit.middleware import RateLimitMiddleware

from .conftest import make_request, skip_unless_postgres, use_backend

# ===========================================================================
# Phase A: Prometheus middleware + observability
# ===========================================================================


def test_prometheus_middleware_records_bucket_path_traffic():
    """Auto-instrumentation works for token-bucket traffic (request.ratelimit is
    now attached on the bucket path, not just the sliding/fixed-window path).
    """
    from django_smart_ratelimit.prometheus import (
        PrometheusMetrics,
        PrometheusMetricsMiddleware,
        get_prometheus_metrics,
    )

    from .test_observability_e2e import _counter_value

    with use_backend("memory"):

        @rate_limit(
            key="ip",
            rate="2/m",
            algorithm=Algorithm.TOKEN_BUCKET,
            algorithm_config={"bucket_size": 2, "refill_rate": 0},
        )
        def view(_request):
            return HttpResponse("ok")

        PrometheusMetrics.reset()
        middleware = PrometheusMetricsMiddleware(lambda request: view(request))
        codes = [middleware(make_request(ip="9.1.1.1")).status_code for _ in range(4)]
        assert codes == [200, 200, 429, 429]

        text = get_prometheus_metrics().generate_metrics()
        allowed = _counter_value(
            text, "django_ratelimit_requests_total", result="allowed"
        )
        denied = _counter_value(
            text, "django_ratelimit_requests_total", result="denied"
        )
        assert allowed == 2.0
        assert denied == 2.0


@pytest.mark.parametrize(
    "algorithm,config",
    [
        (Algorithm.TOKEN_BUCKET, {"bucket_size": 5}),
        (Algorithm.SLIDING_WINDOW, None),
    ],
)
def test_decorator_attaches_request_ratelimit_context(algorithm, config):
    """The decorator attaches request.ratelimit (with .allowed / .backend_name)
    on the bucket and window paths alike.
    """
    with use_backend("memory"):

        @rate_limit(key="ip", rate="5/m", algorithm=algorithm, algorithm_config=config)
        def view(_request):
            return HttpResponse("ok")

        request = make_request(ip="9.2.2.2")
        view(request)
        ctx = getattr(request, "ratelimit", None)
        assert ctx is not None
        assert ctx.allowed is True
        assert ctx.backend_name == "MemoryBackend"


def test_middleware_header_merge_tolerates_missing_remaining():
    """A downstream response that sets X-RateLimit-Limit but not -Remaining must
    not crash the header merge (was int(float('inf')) -> OverflowError).
    """

    def view(_request):
        response = HttpResponse("ok")
        response["X-RateLimit-Limit"] = "100"  # Limit set, Remaining absent
        return response

    with override_settings(
        RATELIMIT_MIDDLEWARE={"BACKEND": "memory", "DEFAULT_RATE": "50/m"}
    ):
        clear_backend_cache()
        middleware = RateLimitMiddleware(view)
        response = middleware(make_request(ip="9.3.3.3", path="/x"))
        assert response.status_code == 200
        # The stricter middleware limit (50) wins the merge.
        assert response.headers["X-RateLimit-Limit"] == "50"
        clear_backend_cache()


# ===========================================================================
# Phase C: DatabaseBackend sliding_window is atomic under concurrency
# ===========================================================================


@skip_unless_postgres
@pytest.mark.django_db(transaction=True)
def test_database_sliding_window_atomic_under_concurrency():
    """Concurrent increments for one key admit EXACTLY the limit on PostgreSQL.

    Without the per-key advisory lock, simultaneous transactions miss each
    other's uncommitted inserts (READ COMMITTED) and all admit -- exceeding the
    limit. The lock serializes them so admission is exact. SQLite serializes
    writers already and uses a per-connection :memory: DB, so this is skipped
    there.
    """
    from django.db import connections

    from django_smart_ratelimit.backends.database import DatabaseBackend

    backend = DatabaseBackend(algorithm="sliding_window")
    assert backend._algorithm == "sliding_window"

    n, limit, period = 30, 10, 60
    key = "v410:concurrency"
    barrier = threading.Barrier(n)

    def worker(_i):
        try:
            barrier.wait(timeout=20)  # release all threads together
            return backend.incr(key, period)
        finally:
            connections.close_all()  # each thread used its own connection

    with ThreadPoolExecutor(max_workers=n) as pool:
        counts = list(pool.map(worker, range(n)))

    admitted = sum(1 for c in counts if c is not None and c <= limit)
    assert admitted == limit, f"expected exactly {limit} admitted, got {admitted}"


# ===========================================================================
# Phase D: numeric / validation / lock fixes
# ===========================================================================


def test_validate_rejects_negative_leaky_leak_rate():
    """A negative leaky-bucket leak_rate is a misconfiguration, not a silent
    fill-over-time limiter.
    """
    from django.core.exceptions import ImproperlyConfigured

    from django_smart_ratelimit.backends.utils import validate_rate_config

    with pytest.raises(ImproperlyConfigured):
        validate_rate_config("10/m", "leaky_bucket", {"leak_rate": -1})
    with pytest.raises(ImproperlyConfigured):
        validate_rate_config("10/m", "leaky_bucket", {"bucket_capacity": 0})


class _StrKVBackend:
    """Minimal key/value backend that round-trips strings and has NO native
    bucket methods, so the algorithms take their generic Python path (the one
    whose elapsed-time clamp is under test).
    """

    def __init__(self):
        self._store = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value, *args, **kwargs):
        self._store[key] = value


def test_token_bucket_clock_step_backward_does_not_drain():
    """A wall-clock step backward must not remove tokens (false rate limiting)."""
    from django_smart_ratelimit.algorithms.token_bucket import TokenBucketAlgorithm

    backend = _StrKVBackend()
    algo = TokenBucketAlgorithm(
        {"bucket_size": 5, "refill_rate": 1.0, "initial_tokens": 5}
    )
    times = iter([1000.0, 990.0, 990.0, 990.0])  # second call sees an earlier time
    algo.get_current_time = lambda: next(times)

    first, _ = algo.is_allowed(backend, "clk", 5, 60, tokens_requested=1)
    second, _ = algo.is_allowed(backend, "clk", 5, 60, tokens_requested=1)
    assert first is True
    assert second is True  # not spuriously blocked by negative elapsed time


def test_leaky_bucket_clock_step_backward_does_not_fill():
    """A wall-clock step backward must not add to the leaky-bucket level."""
    from django_smart_ratelimit.algorithms.leaky_bucket import LeakyBucketAlgorithm

    backend = _StrKVBackend()
    algo = LeakyBucketAlgorithm({"bucket_capacity": 3, "leak_rate": 1.0})
    times = iter([1000.0, 990.0, 990.0, 990.0])
    algo.get_current_time = lambda: next(times)

    first, _ = algo.is_allowed(backend, "clk2", 3, 60, request_cost=1)
    second, _ = algo.is_allowed(backend, "clk2", 3, 60, request_cost=1)
    assert first is True
    assert second is True


@pytest.mark.django_db
def test_token_bucket_model_accepts_large_bucket_size():
    """bucket_size above 2**31-1 is storable (fields widened to BigInteger)."""
    from django.utils import timezone

    from django_smart_ratelimit.models import RateLimitTokenBucket

    big = 3_000_000_000  # > 2**31 - 1
    bucket = RateLimitTokenBucket.objects.create(
        key="v410:big",
        tokens=float(big),
        bucket_size=big,
        refill_rate=1.0,
        last_update=timezone.now(),
    )
    bucket.refresh_from_db()
    assert bucket.bucket_size == big


def test_adaptive_add_indicator_is_thread_safe():
    """Concurrently adding indicators while computing the limit must not raise
    'list changed size during iteration'.
    """
    from django_smart_ratelimit.adaptive import (
        AdaptiveRateLimiter,
        CustomLoadIndicator,
    )

    limiter = AdaptiveRateLimiter(base_limit=100, update_interval=0.0)
    errors = []
    stop = threading.Event()

    def adder(start):
        i = start
        while not stop.is_set():
            try:
                limiter.add_indicator(
                    CustomLoadIndicator(f"ind-{i}", lambda: 0.5), weight=1.0
                )
                limiter.remove_indicator(f"ind-{i}")
            except Exception as exc:  # pragma: no cover - the bug would land here
                errors.append(exc)
                return
            i += 100

    def reader():
        while not stop.is_set():
            try:
                limiter.get_effective_limit()
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
                return

    threads = [threading.Thread(target=adder, args=(n,)) for n in range(3)]
    threads.append(threading.Thread(target=reader))
    for t in threads:
        t.start()
    threading.Event().wait(0.3)
    stop.set()
    for t in threads:
        t.join(timeout=5)
    assert not errors, f"thread-safety error: {errors[:1]}"


# ===========================================================================
# Phase F: e2e coverage gaps (unicode/long keys, round_robin, two-store failover)
# ===========================================================================

from .conftest import (  # noqa: E402
    MEMORY,
    MONGODB,
    REDIS,
    skip_without_mongo,
    skip_without_redis,
)

_KEY_BACKENDS = [
    pytest.param("memory", id="memory"),
    pytest.param("redis", id="redis", marks=skip_without_redis),
]


@pytest.mark.parametrize("backend_name", _KEY_BACKENDS)
def test_unicode_and_long_key_values_isolate_buckets(backend_name):
    """A unicode and a very-long key value each get their own bucket, and an
    identical value shares one (no collision/truncation).
    """
    with use_backend(backend_name):

        def tenant_key(req, *args, **kwargs):
            return "t:" + req.META.get("HTTP_X_TENANT", "")

        @rate_limit(key=tenant_key, rate="2/m")
        def view(_request):
            return HttpResponse("ok")

        def hit(value):
            request = make_request(ip="203.0.113.77", headers={"X-Tenant": value})
            return view(request).status_code

        unicode_value = "té-ναμε-🔑-账户"
        long_value = "x" * 512

        # Each distinct value gets its own 2/min budget.
        assert [hit(unicode_value) for _ in range(3)] == [200, 200, 429]
        assert [hit(long_value) for _ in range(3)] == [200, 200, 429]
        # A different value is unaffected (independent bucket).
        assert hit("other") == 200


@skip_without_redis
def test_multi_backend_round_robin_distributes_writes():
    """round_robin strategy spreads increments across the configured backends."""
    from django_smart_ratelimit.backends.multi import MultiBackend

    with override_settings(
        RATELIMIT_BACKENDS=[
            {"name": "a", "backend": MEMORY, "config": {}},
            {"name": "b", "backend": MEMORY, "config": {}},
        ],
        RATELIMIT_MULTI_BACKEND_STRATEGY="round_robin",
        RATELIMIT_HEALTH_CHECK_INTERVAL=30,
    ):
        multi = MultiBackend()
        try:
            for _ in range(6):
                multi.incr("rr:key", 60)
            (_an, a), (_bn, b) = multi.backends
            # Both backends received at least one write (not all on one).
            assert a.get_count("rr:key", 60) > 0
            assert b.get_count("rr:key", 60) > 0
        finally:
            multi.shutdown()


@skip_without_mongo
def test_multi_backend_fails_over_to_a_second_live_store():
    """With a dead primary and a LIVE secondary (MongoDB), enforcement still
    works -- failover lands on the second real store, not just memory.
    """
    from django_smart_ratelimit.backends import clear_backend_cache, get_backend

    with override_settings(
        RATELIMIT_BACKEND="django_smart_ratelimit.backends.multi.MultiBackend",
        RATELIMIT_BACKENDS=[
            {
                "name": "dead",
                "backend": REDIS,
                "config": {"host": "127.0.0.1", "port": 6399},
            },
            {
                "name": "mongo",
                "backend": MONGODB,
                "config": {"host": "localhost", "port": 27017, "database": "ratelimit"},
            },
        ],
        RATELIMIT_MULTI_BACKEND_STRATEGY="first_healthy",
        RATELIMIT_FAIL_OPEN=True,
        RATELIMIT_HEALTH_CHECK_INTERVAL=0,
    ):
        from pymongo import MongoClient

        MongoClient(host="localhost", port=27017).drop_database("ratelimit")
        clear_backend_cache()
        try:
            backend = get_backend()
            counts = [backend.incr("failover:key", 60) for _ in range(3)]
            # MongoDB (the live secondary) served and counted the requests.
            assert counts == [1, 2, 3]
        finally:
            clear_backend_cache()
            MongoClient(host="localhost", port=27017).drop_database("ratelimit")
