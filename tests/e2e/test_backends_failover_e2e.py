"""Real-backend end-to-end tests for backend storage behavior and failover.

These scenarios exercise the public backend API against REAL storage (a live
Redis, a live MongoDB, the in-memory store, and the real Django test database) --
no mocking of the rate-limit store. Each scenario uses DISTINCT keys/IPs and the
``real_backend`` fixture flushes the store before and after, so tests are fully
self-contained.

Coverage:
    - Per-backend storage round-trip: ``incr`` / ``get_count`` /
      ``get_reset_time`` / ``reset`` behave correctly against the real store,
      independent buckets per distinct key, a limit is enforced and then resets.
    - MultiBackend failover: a primary + fallback configured via
      ``RATELIMIT_BACKENDS`` / ``RATELIMIT_MULTI_BACKENDS`` (e.g. redis primary +
      memory fallback) keeps serving and limiting while the primary is healthy,
      and transparently falls over to the secondary when the primary is dead.
    - Real outage scenario: a Redis backend pointed at a DEAD port fails open
      (``fail_open=True`` allows) or closed (``fail_open=False`` denies / refuses
      to construct), observable at both the backend layer and the HTTP layer.
    - Database backend (``@pytest.mark.django_db``) round-trip and enforcement.
"""

import time

import pytest

from django.test import override_settings

from django_smart_ratelimit.backends import clear_backend_cache, get_backend
from django_smart_ratelimit.backends.multi import MultiBackend
from django_smart_ratelimit.decorator import rate_limit

from .conftest import (  # noqa: F401  (real_backend is a pytest fixture)
    MEMORY,
    REDIS,
    exhaust,
    real_backend,
    skip_without_redis,
    use_backend,
)

# A port nothing listens on -- a "dead" Redis so we can exercise outage paths.
DEAD_REDIS_PORT = 6390


def _ok_view(_request):
    """Return a trivial 200 response; wrapped by the rate_limit decorator."""
    from django.http import HttpResponse

    return HttpResponse("ok")


# ---------------------------------------------------------------------------
# Per-backend storage round-trip on the REAL store (every available backend).
# ---------------------------------------------------------------------------


def test_incr_get_count_round_trip_on_real_store(real_backend):  # noqa: F811
    """Storage round-trip: each incr is durably recorded on the real store.

    A counter that is incremented N times reports a count of N via get_count on
    the very same real backend (memory dict / live Redis / live MongoDB) -- the
    write is observable by an independent read.
    """
    backend = get_backend()
    key = f"e2e:roundtrip:{real_backend}"

    assert backend.get_count(key, 60) == 0
    for expected in range(1, 6):
        assert backend.incr(key, 60) == expected
    assert backend.get_count(key, 60) == 5


def test_distinct_keys_are_independent_buckets(real_backend):  # noqa: F811
    """Two distinct keys never share a counter on the real store.

    Hammering bucket A leaves bucket B untouched -- the backend keys requests
    independently, which is what makes per-IP / per-user limiting work.
    """
    backend = get_backend()
    key_a = f"e2e:independent:A:{real_backend}"
    key_b = f"e2e:independent:B:{real_backend}"

    for _ in range(7):
        backend.incr(key_a, 60)

    assert backend.get_count(key_a, 60) == 7
    assert backend.get_count(key_b, 60) == 0
    assert backend.incr(key_b, 60) == 1
    # A is still untouched by B's activity.
    assert backend.get_count(key_a, 60) == 7


def test_get_reset_time_is_in_the_future(real_backend):  # noqa: F811
    """get_reset_time returns a future expiry once a key exists, None otherwise.

    Before any request the key has no reset time; after the first incr the real
    store reports a reset timestamp roughly one window into the future (used to
    populate the X-RateLimit-Reset header).
    """
    backend = get_backend()
    key = f"e2e:resettime:{real_backend}"

    assert backend.get_reset_time(key) is None

    before = int(time.time())
    backend.incr(key, 60)
    reset = backend.get_reset_time(key)

    assert reset is not None
    # Reset is in the future and within (roughly) one window of "now".
    assert reset >= before
    assert reset <= before + 60 + 5


def test_reset_clears_the_counter_on_real_store(real_backend):  # noqa: F811
    """reset() wipes the counter so a fresh budget starts on the real store.

    After exhausting some budget, reset() drops the count back to 0 and the next
    incr starts the window over from 1 -- the manual "unblock this key" path.
    """
    backend = get_backend()
    key = f"e2e:reset:{real_backend}"

    for _ in range(4):
        backend.incr(key, 60)
    assert backend.get_count(key, 60) == 4

    backend.reset(key)

    assert backend.get_count(key, 60) == 0
    assert backend.incr(key, 60) == 1


def test_limit_enforced_then_resets_on_real_store(real_backend):  # noqa: F811
    """A 3/window limit blocks the 4th request, then reset re-opens the budget.

    check_rate_limit (the primitive every algorithm builds on) returns allowed
    for the first 3 requests and denied for the 4th against the real store; after
    reset(), the key is allowed again.
    """
    backend = get_backend()
    key = f"e2e:enforced:{real_backend}"
    limit, period = 3, 60

    decisions = [backend.check_rate_limit(key, limit, period)[0] for _ in range(4)]
    assert decisions == [True, True, True, False]

    backend.reset(key)

    allowed, meta = backend.check_rate_limit(key, limit, period)
    assert allowed is True
    assert meta["count"] == 1


def test_increment_reports_remaining_budget(real_backend):  # noqa: F811
    """increment() returns (count, remaining) so callers can emit headers.

    Against the real store, the remaining budget counts down as requests arrive
    and never goes negative once the limit is blown.
    """
    backend = get_backend()
    key = f"e2e:remaining:{real_backend}"
    limit, period = 5, 60

    seen = [backend.increment(key, period, limit) for _ in range(7)]
    counts = [c for c, _ in seen]
    remaining = [r for _, r in seen]

    assert counts == [1, 2, 3, 4, 5, 6, 7]
    assert remaining == [4, 3, 2, 1, 0, 0, 0]


def test_short_window_expires_and_budget_refreshes(real_backend):  # noqa: F811
    """A 1-second window expires on the real store and the budget refreshes.

    After filling a 2/1s bucket and waiting out the window, the real backend's
    TTL/eviction has dropped the old entries and a fresh request is allowed --
    proving expiry is enforced by the live store, not just in memory bookkeeping.
    """
    backend = get_backend()
    key = f"e2e:expiry:{real_backend}"
    limit, period = 2, 1

    first = [backend.check_rate_limit(key, limit, period)[0] for _ in range(3)]
    assert first == [True, True, False]

    # Wait out the window (plus margin) so the live store expires the entries.
    time.sleep(1.6)

    allowed, _ = backend.check_rate_limit(key, limit, period)
    assert allowed is True


# ---------------------------------------------------------------------------
# Multi-backend failover against the REAL store.
# ---------------------------------------------------------------------------


@skip_without_redis
def test_multi_backend_serves_through_healthy_primary():
    """RATELIMIT_BACKENDS with redis primary + memory fallback limits normally.

    With a healthy redis primary the MultiBackend routes everything to redis and
    enforces a 3/window limit just like a single backend -- the fallback is dormant
    but configured. Verified end-to-end through the real redis store.
    """
    backends = [
        {
            "name": "primary-redis",
            "backend": REDIS,
            "config": {"host": "localhost", "port": 6379, "db": 0},
        },
        {"name": "fallback-memory", "backend": MEMORY, "config": {}},
    ]
    with override_settings(
        RATELIMIT_BACKEND="multi",
        RATELIMIT_BACKENDS=backends,
        RATELIMIT_MULTI_BACKEND_STRATEGY="first_healthy",
        RATELIMIT_HEALTH_CHECK_INTERVAL=0,
        RATELIMIT_REDIS={"host": "localhost", "port": 6379, "db": 0},
    ):
        clear_backend_cache()
        try:
            import redis as _redis

            _redis.Redis(host="localhost", port=6379, db=0).flushdb()

            backend = get_backend()
            assert isinstance(backend, MultiBackend)

            key = "e2e:multi:healthy:primary"
            decisions = [backend.check_rate_limit(key, 3, 60)[0] for _ in range(4)]
            assert decisions == [True, True, True, False]

            # The write landed on the real redis primary, not the memory fallback.
            _, redis_backend = backend.backends[0]
            assert redis_backend.get_count(key, 60) == 4
        finally:
            clear_backend_cache()
            _redis.Redis(host="localhost", port=6379, db=0).flushdb()


@skip_without_redis
def test_multi_backend_fails_over_to_memory_when_primary_is_dead():
    """Dead redis primary -> MultiBackend transparently uses the memory fallback.

    The primary points at a dead port. A fail-closed redis backend cannot connect
    at startup, so the MultiBackend drops it during initialization and is left with
    only the live memory fallback, which then serves every request and still
    enforces the 2/window limit. This is the resilience promise: a redis outage
    degrades to local limiting instead of taking the limiter down.
    """
    backends = [
        {
            "name": "primary-dead-redis",
            "backend": REDIS,
            "config": {"host": "localhost", "port": DEAD_REDIS_PORT},
        },
        {"name": "fallback-memory", "backend": MEMORY, "config": {}},
    ]
    with override_settings(
        RATELIMIT_BACKEND="multi",
        RATELIMIT_MULTI_BACKENDS=backends,
        RATELIMIT_MULTI_BACKEND_STRATEGY="first_healthy",
        RATELIMIT_HEALTH_CHECK_INTERVAL=0,
        RATELIMIT_REDIS={"host": "localhost", "port": DEAD_REDIS_PORT},
    ):
        clear_backend_cache()
        try:
            backend = get_backend()
            assert isinstance(backend, MultiBackend)

            # The unreachable primary was dropped; only the memory fallback remains.
            surviving = [name for name, _ in backend.backends]
            assert surviving == ["fallback-memory"]

            key = "e2e:multi:failover:dead-primary"
            decisions = [backend.check_rate_limit(key, 2, 60)[0] for _ in range(3)]
            assert decisions == [True, True, False]

            # State materialized on the surviving memory fallback.
            _, mem_backend = backend.backends[-1]
            assert mem_backend.get_count(key, 60) == 3
        finally:
            clear_backend_cache()


def test_multi_backend_memory_pair_round_trip():
    """Two memory backends behind MultiBackend: primary serves, state round-trips.

    A backend-agnostic failover topology (memory primary + memory fallback) that
    runs without any external service: requests are counted on the primary and a
    3/window limit is enforced through the multi layer.
    """
    backends = [
        {"name": "primary-mem", "backend": MEMORY, "config": {}},
        {"name": "fallback-mem", "backend": MEMORY, "config": {}},
    ]
    with override_settings(
        RATELIMIT_BACKEND="multi",
        RATELIMIT_MULTI_BACKENDS=backends,
        RATELIMIT_MULTI_BACKEND_STRATEGY="first_healthy",
        RATELIMIT_HEALTH_CHECK_INTERVAL=0,
    ):
        clear_backend_cache()
        try:
            backend = get_backend()
            assert isinstance(backend, MultiBackend)

            key = "e2e:multi:memory-pair"
            decisions = [backend.check_rate_limit(key, 3, 60)[0] for _ in range(4)]
            assert decisions == [True, True, True, False]

            _, primary = backend.backends[0]
            assert primary.get_count(key, 60) == 4
        finally:
            clear_backend_cache()


# ---------------------------------------------------------------------------
# Real outage scenario: redis on a DEAD port + fail_open semantics.
# ---------------------------------------------------------------------------


@skip_without_redis
def test_dead_redis_fail_open_true_allows_requests():
    """Redis pointed at a dead port with fail_open=True keeps allowing traffic.

    A misconfigured/unreachable Redis must not take the site down: with
    fail_open=True the backend constructs (redis handle is None) and incr returns
    a safe "allowed" value, so the HTTP endpoint keeps returning 200 during the
    outage instead of 5xx-ing every visitor.
    """
    with override_settings(
        RATELIMIT_BACKEND=REDIS,
        RATELIMIT_REDIS={"host": "localhost", "port": DEAD_REDIS_PORT},
        RATELIMIT_FAIL_OPEN=True,
    ):
        clear_backend_cache()
        try:
            backend = get_backend()
            assert backend.fail_open is True
            # Backend came up despite the dead port and fails open on incr.
            assert backend.incr("e2e:dead:fail-open", 60) == 0

            view = rate_limit(key="ip", rate="2/m")(_ok_view)
            codes = exhaust(view, 5, ip="198.51.100.7")
            # Never blocked: the outage degrades to "allow everything".
            assert codes == [200, 200, 200, 200, 200]
        finally:
            clear_backend_cache()


@skip_without_redis
def test_dead_redis_fail_open_false_denies():
    """Redis on a dead port with fail_open=False refuses rather than silently allow.

    Fail-closed deployments treat a backend outage as a hard error: constructing
    the Redis backend against a dead port raises ImproperlyConfigured (the limiter
    will not silently let everyone through). This is the security-first posture.
    """
    from django.core.exceptions import ImproperlyConfigured

    with override_settings(
        RATELIMIT_BACKEND=REDIS,
        RATELIMIT_REDIS={"host": "localhost", "port": DEAD_REDIS_PORT},
        RATELIMIT_FAIL_OPEN=False,
    ):
        clear_backend_cache()
        try:
            with pytest.raises(ImproperlyConfigured):
                get_backend()
        finally:
            clear_backend_cache()


# ---------------------------------------------------------------------------
# Database backend against the REAL test DB.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_database_backend_round_trip_and_enforcement():
    """Database backend: incr/get_count/reset round-trip on the real test DB.

    The SQL-backed limiter durably records each increment as rows, reports the
    count back via an independent read, enforces a 3/window limit, and reset()
    deletes the rows so the budget re-opens -- all against the real Django DB.
    """
    with use_backend("database"):
        backend = get_backend()
        key = "e2e:db:round-trip"

        assert backend.get_count(key, 60) == 0
        for expected in range(1, 4):
            assert backend.incr(key, 60) == expected
        assert backend.get_count(key, 60) == 3

        # 4th request over a 3/window limit is denied.
        decisions = [backend.check_rate_limit(key, 3, 60)[0] for _ in range(2)]
        # Two more increments land us at counts 4 and 5 -> both over the limit.
        assert decisions == [False, False]

        backend.reset(key)
        assert backend.get_count(key, 60) == 0


@pytest.mark.django_db
def test_database_backend_distinct_keys_independent():
    """Database backend keys distinct buckets independently on the real DB.

    Two keys (e.g. two different client IPs) accumulate counts without bleeding
    into each other -- the per-key WHERE clause isolates their rows.
    """
    with use_backend("database"):
        backend = get_backend()
        key_a = "e2e:db:independent:A"
        key_b = "e2e:db:independent:B"

        for _ in range(5):
            backend.incr(key_a, 60)
        backend.incr(key_b, 60)

        assert backend.get_count(key_a, 60) == 5
        assert backend.get_count(key_b, 60) == 1

        backend.reset(key_a)
        assert backend.get_count(key_a, 60) == 0
        # Resetting A leaves B intact.
        assert backend.get_count(key_b, 60) == 1


@pytest.mark.django_db
def test_database_backend_get_reset_time_in_future():
    """Database backend reports a future reset time once a key has activity.

    get_reset_time is None for an untouched key and a future timestamp after the
    first incr, sourced from the window_end / expires_at columns on the real DB.
    """
    with use_backend("database"):
        backend = get_backend()
        key = "e2e:db:reset-time"

        assert backend.get_reset_time(key) is None

        before = int(time.time())
        backend.incr(key, 60)
        reset = backend.get_reset_time(key)

        assert reset is not None
        assert reset >= before
