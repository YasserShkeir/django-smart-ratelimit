"""Real-backend end-to-end tests for the reliability feature surface.

These scenarios exercise the public reliability APIs against REAL infrastructure
(a live Redis for distributed circuit-breaker state, a dead TCP port for the
fail-open/fail-closed scenarios, and the real Django test database for the
cleanup command) -- never a mocked backend or a mocked state store.

Covered API surface:
    - ``circuit_breaker`` decorator + ``circuit_breaker_registry``: a repeatedly
      failing function trips the breaker (``CircuitBreakerError``) and recovers
      after the recovery timeout; the distributed variant keeps its state on a
      REAL Redis (``RATELIMIT_CIRCUIT_BREAKER_STORAGE="redis"`` + a real URL).
    - ``fail_open`` vs fail-closed: a ``RedisBackend`` pointed at a dead port
      either allows (fail-open) or denies/raises (fail-closed), both at the
      backend layer and end-to-end through the ``rate_limit`` decorator.
    - Adaptive limiting: a registered ``AdaptiveRateLimiter`` driven by a real
      ``CustomLoadIndicator`` changes the effective limit the decorator enforces.
    - Management commands via ``call_command``: ``ratelimit_health`` reports a
      real backend as healthy/unhealthy, and ``ratelimit_cleanup`` reports and
      removes expired rows on the real database backend.
"""

import time
import uuid
from io import StringIO

import pytest

from django.core.management import call_command
from django.http import HttpResponse
from django.test import override_settings

from django_smart_ratelimit import (
    AdaptiveRateLimiter,
    rate_limit,
    register_adaptive_limiter,
    unregister_adaptive_limiter,
)
from django_smart_ratelimit.adaptive import CustomLoadIndicator
from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.backends.redis_backend import RedisBackend

# NOTE: the package root re-exports a *different* CircuitBreakerError (from
# ``exceptions``); the ``circuit_breaker`` decorator actually raises the one
# defined in ``circuit_breaker``, so import the matching class from there.
from django_smart_ratelimit.circuit_breaker import (
    CircuitBreakerError,
    circuit_breaker,
    circuit_breaker_registry,
)
from django_smart_ratelimit.config import reset_settings

from .conftest import (
    REDIS,
    REDIS_HOST,
    REDIS_PORT,
    make_request,
    skip_without_redis,
    use_backend,
)

# A TCP port nothing listens on -- used to simulate an unreachable Redis.
DEAD_REDIS_PORT = 1


# ---------------------------------------------------------------------------
# circuit_breaker decorator + registry (in-process / memory state)
# ---------------------------------------------------------------------------


def test_circuit_breaker_trips_after_repeated_failures():
    """A flaky dependency that keeps raising trips the breaker after N failures.

    Real-life: an upstream API call keeps failing. After ``failure_threshold``
    consecutive failures the breaker OPENs and short-circuits further calls,
    raising ``CircuitBreakerError`` instead of hammering the dead dependency.
    """
    name = f"cb-trip-{uuid.uuid4().hex}"
    calls = {"n": 0}

    @circuit_breaker(failure_threshold=3, recovery_timeout=60, name=name)
    def flaky_upstream():
        calls["n"] += 1
        raise ConnectionError("upstream down")

    # The first three calls reach the function and raise the real error.
    for _ in range(3):
        with pytest.raises(ConnectionError):
            flaky_upstream()

    assert calls["n"] == 3

    # The breaker is now OPEN: the next call is short-circuited and the
    # underlying function is NOT invoked again.
    with pytest.raises(CircuitBreakerError) as exc_info:
        flaky_upstream()

    assert calls["n"] == 3  # function was not called while OPEN
    assert exc_info.value.breaker_name == name
    breaker = flaky_upstream.circuit_breaker
    assert breaker.state.value == "open"

    circuit_breaker_registry.remove(name)


def test_circuit_breaker_recovers_after_recovery_timeout():
    """The breaker probes recovery once the recovery timeout elapses.

    Real-life: the upstream comes back. After ``recovery_timeout`` the breaker
    goes HALF_OPEN, lets one probe through, and a success CLOSEs it again.
    """
    name = f"cb-recover-{uuid.uuid4().hex}"
    state = {"fail": True}

    @circuit_breaker(failure_threshold=2, recovery_timeout=1, name=name)
    def upstream():
        if state["fail"]:
            raise ConnectionError("still down")
        return "ok"

    for _ in range(2):
        with pytest.raises(ConnectionError):
            upstream()

    breaker = upstream.circuit_breaker
    assert breaker.state.value == "open"

    # While OPEN (before the timeout) the breaker short-circuits.
    with pytest.raises(CircuitBreakerError):
        upstream()

    # Upstream recovers; wait out the recovery_timeout then probe.
    state["fail"] = False
    time.sleep(1.2)

    assert upstream() == "ok"
    assert breaker.state.value == "closed"

    circuit_breaker_registry.remove(name)


def test_circuit_breaker_only_trips_on_expected_exception():
    """Only the configured exception type counts toward tripping the breaker.

    Real-life: a 4xx ``ValueError`` is the caller's fault and should not open
    the breaker, while ``ConnectionError`` (the dependency being down) should.
    """
    name = f"cb-expected-{uuid.uuid4().hex}"

    @circuit_breaker(
        failure_threshold=2,
        recovery_timeout=60,
        expected_exception=ConnectionError,
        name=name,
    )
    def upstream(kind):
        raise kind("boom")

    # Many ValueErrors do NOT trip the breaker (wrong exception type).
    for _ in range(5):
        with pytest.raises(ValueError):
            upstream(ValueError)

    breaker = upstream.circuit_breaker
    assert breaker.state.value == "closed"

    # ConnectionErrors do count and trip it.
    for _ in range(2):
        with pytest.raises(ConnectionError):
            upstream(ConnectionError)

    assert breaker.state.value == "open"
    with pytest.raises(CircuitBreakerError):
        upstream(ConnectionError)

    circuit_breaker_registry.remove(name)


def test_circuit_breaker_fallback_function_serves_while_open():
    """When OPEN, the configured fallback is served instead of raising.

    Real-life: a recommendations service is down; rather than error out we serve
    a cached/default payload from the fallback while the breaker is OPEN.
    """
    name = f"cb-fallback-{uuid.uuid4().hex}"

    def fallback():
        return "cached-default"

    @circuit_breaker(
        failure_threshold=2,
        recovery_timeout=60,
        name=name,
        fallback_function=fallback,
    )
    def recommendations():
        raise ConnectionError("recs down")

    # Failures still propagate while the breaker is CLOSED...
    for _ in range(2):
        with pytest.raises(ConnectionError):
            recommendations()

    # ...but once OPEN, the fallback is served (no exception).
    assert recommendations() == "cached-default"
    assert recommendations() == "cached-default"
    assert recommendations.circuit_breaker.state.value == "open"

    circuit_breaker_registry.remove(name)


def test_circuit_breaker_registry_tracks_and_resets():
    """The global registry exposes/manages breakers; reset re-CLOSEs them.

    Real-life: an ops dashboard reads ``circuit_breaker_registry`` to show every
    breaker's status and an operator manually resets one after a fix.
    """
    name = f"cb-registry-{uuid.uuid4().hex}"

    @circuit_breaker(failure_threshold=2, recovery_timeout=60, name=name)
    def svc():
        raise ConnectionError("down")

    for _ in range(2):
        with pytest.raises(ConnectionError):
            svc()

    # Registry can hand back the same breaker by name.
    assert circuit_breaker_registry.get(name) is svc.circuit_breaker

    status = circuit_breaker_registry.get_all_status()
    assert name in status
    assert status[name]["state"] == "open"

    # Manual reset returns it to CLOSED so traffic flows again.
    circuit_breaker_registry.get(name).reset()
    assert svc.circuit_breaker.state.value == "closed"

    circuit_breaker_registry.remove(name)


# ---------------------------------------------------------------------------
# Distributed circuit breaker on REAL Redis state storage
# ---------------------------------------------------------------------------


@skip_without_redis
def test_circuit_breaker_state_on_real_redis():
    """Circuit-breaker state lives on REAL Redis and trips/recovers there.

    Real-life: multiple app processes share one breaker via Redis so that one
    worker observing a dead dependency protects the whole fleet. Here we drive
    the breaker, then read the failure/state keys straight from the live Redis
    to prove the state is genuinely persisted to the store.
    """
    import redis as _redis

    name = f"cb-redis-{uuid.uuid4().hex}"
    redis_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
    client = _redis.from_url(redis_url)

    # Clean any prior state for this (unique) breaker name.
    for suffix in ("state", "failures", "last_failure", "half_open_calls"):
        client.delete(f"circuit:{name}:{suffix}")

    with override_settings(
        RATELIMIT_CIRCUIT_BREAKER_STORAGE="redis",
        RATELIMIT_CIRCUIT_BREAKER_REDIS_URL=redis_url,
    ):
        reset_settings()
        try:

            @circuit_breaker(failure_threshold=3, recovery_timeout=1, name=name)
            def upstream():
                raise ConnectionError("down")

            # Confirm the breaker actually attached the Redis-backed storage.
            storage = upstream.circuit_breaker._storage
            assert storage.__class__.__name__ == "RedisCircuitBreakerState"

            for _ in range(3):
                with pytest.raises(ConnectionError):
                    upstream()

            # State is persisted on the REAL Redis, not just in memory.
            assert client.get(f"circuit:{name}:state").decode() == "open"
            assert int(client.get(f"circuit:{name}:failures")) >= 3
            assert upstream.circuit_breaker.state.value == "open"

            # OPEN short-circuits before the recovery timeout.
            with pytest.raises(CircuitBreakerError):
                upstream()

            # After recovery_timeout the breaker probes HALF_OPEN again. The
            # probe call still fails, so it re-OPENs -- but the important part is
            # that it stopped short-circuiting and actually invoked upstream.
            time.sleep(1.2)
            with pytest.raises(ConnectionError):
                upstream()
        finally:
            for suffix in ("state", "failures", "last_failure", "half_open_calls"):
                client.delete(f"circuit:{name}:{suffix}")
            circuit_breaker_registry.remove(name)
            reset_settings()


# ---------------------------------------------------------------------------
# fail_open vs fail_closed against an unreachable (dead-port) Redis
# ---------------------------------------------------------------------------


def test_backend_fail_open_allows_when_redis_unreachable():
    """fail_open=True: an unreachable Redis degrades to ALLOW, never blocks.

    Real-life: Redis falls over; with fail-open the site keeps serving (rate
    limiting silently disabled) rather than 500-ing every request.
    """
    # RedisBackend reads its connection config from RATELIMIT_REDIS, so point
    # that at a dead port for the duration of this scenario.
    with override_settings(
        RATELIMIT_REDIS={"host": REDIS_HOST, "port": DEAD_REDIS_PORT, "db": 0}
    ):
        reset_settings()
        try:
            backend = RedisBackend(fail_open=True)
            # Construction succeeds even though Redis is unreachable; client is None.
            assert backend.redis is None
            # incr() returns 0 (== allowed) instead of raising.
            assert backend.incr("fail-open-key", period=60) == 0
        finally:
            reset_settings()


def test_backend_fail_closed_raises_when_redis_unreachable():
    """fail_open=False: an unreachable Redis is a hard error (deny).

    Real-life: a payment endpoint must never run unprotected -- if the limiter's
    store is down, fail CLOSED rather than silently allowing unlimited traffic.
    """
    from django.core.exceptions import ImproperlyConfigured

    with override_settings(
        RATELIMIT_REDIS={"host": REDIS_HOST, "port": DEAD_REDIS_PORT, "db": 0}
    ):
        reset_settings()
        try:
            with pytest.raises(ImproperlyConfigured):
                RedisBackend(fail_open=False)
        finally:
            reset_settings()


def test_decorator_fail_open_serves_200_when_redis_unreachable():
    """End-to-end: a view stays available (200) under fail-open when Redis dies.

    Real-life: the limiter's Redis is unreachable but the public read endpoint
    keeps returning 200 because RATELIMIT_FAIL_OPEN is on.
    """
    with override_settings(
        RATELIMIT_BACKEND=REDIS,
        RATELIMIT_REDIS={"host": REDIS_HOST, "port": DEAD_REDIS_PORT, "db": 0},
        RATELIMIT_FAIL_OPEN=True,
    ):
        reset_settings()
        clear_backend_cache()
        try:

            @rate_limit(key="ip", rate="2/m", backend=REDIS)
            def view(request):
                return HttpResponse("ok")

            # Even past the nominal 2/m limit, fail-open keeps serving 200.
            codes = [
                view(make_request(ip="198.51.100.7")).status_code for _ in range(5)
            ]
            assert codes == [200, 200, 200, 200, 200]
        finally:
            clear_backend_cache()
            reset_settings()


def test_decorator_fail_closed_does_not_silently_allow_when_redis_unreachable():
    """End-to-end: fail-closed refuses to serve normally when Redis is dead.

    Real-life: with fail-closed, an unreachable store must not turn into a free
    pass -- the request errors out instead of returning a normal 200.
    """
    from django.core.exceptions import ImproperlyConfigured

    with override_settings(
        RATELIMIT_BACKEND=REDIS,
        RATELIMIT_REDIS={"host": REDIS_HOST, "port": DEAD_REDIS_PORT, "db": 0},
        RATELIMIT_FAIL_OPEN=False,
    ):
        reset_settings()
        clear_backend_cache()
        try:

            @rate_limit(key="ip", rate="2/m", backend=REDIS)
            def view(request):
                return HttpResponse("ok")

            # The dead-port backend cannot be constructed under fail-closed, so
            # the call surfaces an error rather than a normal 200 response.
            with pytest.raises(ImproperlyConfigured):
                view(make_request(ip="198.51.100.8"))
        finally:
            clear_backend_cache()
            reset_settings()


# ---------------------------------------------------------------------------
# Adaptive rate limiting with a real custom indicator (every real backend)
# ---------------------------------------------------------------------------


def test_adaptive_high_load_tightens_decorator_limit(real_backend):
    """Under HIGH load the adaptive limiter clamps the effective limit to min.

    Real-life: a system-load probe reports the box is saturated, so the API's
    effective limit drops to its floor (1 req) and a client is blocked after a
    single request -- verified against every real backend.
    """
    load = {"value": 1.0}  # max load
    limiter = AdaptiveRateLimiter(
        base_limit=100,
        min_limit=1,
        max_limit=1000,
        indicators=[CustomLoadIndicator(lambda: load["value"], name="probe")],
        smoothing_factor=1.0,
        update_interval=0,
    )
    name = f"adaptive-high-{real_backend}-{uuid.uuid4().hex}"
    register_adaptive_limiter(name, limiter)

    # Effective limit collapses to min_limit under max load.
    assert limiter.get_effective_limit() == 1

    @rate_limit(key="ip", rate="100/m", adaptive=name, backend=real_backend)
    def view(request):
        return HttpResponse("ok")

    ip = "203.0.113.41"
    first = view(make_request(ip=ip)).status_code
    second = view(make_request(ip=ip)).status_code

    assert first == 200  # only one request allowed
    assert second == 429  # adaptive floor of 1 blocks the rest

    unregister_adaptive_limiter(name)


def test_adaptive_low_load_relaxes_decorator_limit(real_backend):
    """Under LOW load the adaptive limiter raises the effective limit to max.

    Real-life: the box is idle, so the same endpoint becomes far more permissive
    (effective limit climbs to max_limit) and a burst that would trip the base
    rate sails through -- verified against every real backend.
    """
    load = {"value": 0.0}  # no load
    limiter = AdaptiveRateLimiter(
        base_limit=2,
        min_limit=1,
        max_limit=50,
        indicators=[CustomLoadIndicator(lambda: load["value"], name="probe")],
        smoothing_factor=1.0,
        update_interval=0,
    )
    name = f"adaptive-low-{real_backend}-{uuid.uuid4().hex}"
    register_adaptive_limiter(name, limiter)

    # With zero load the effective limit jumps to max_limit.
    assert limiter.get_effective_limit() == 50

    @rate_limit(key="ip", rate="2/m", adaptive=name, backend=real_backend)
    def view(request):
        return HttpResponse("ok")

    ip = "203.0.113.42"
    # A 10-request burst (well over the base rate of 2/m) is all allowed because
    # the adaptive effective limit is 50.
    codes = [view(make_request(ip=ip)).status_code for _ in range(10)]
    assert codes == [200] * 10

    unregister_adaptive_limiter(name)


def test_adaptive_limit_tracks_changing_indicator(real_backend):
    """The effective limit follows the live indicator as load changes.

    Real-life: load ramps from idle to saturated; the adaptive limiter re-reads
    its real indicator and tightens the effective limit in lock-step.
    """
    load = {"value": 0.0}
    limiter = AdaptiveRateLimiter(
        base_limit=10,
        min_limit=2,
        max_limit=40,
        indicators=[CustomLoadIndicator(lambda: load["value"], name="probe")],
        smoothing_factor=1.0,
        update_interval=0,
    )

    assert limiter.get_effective_limit() == 40  # idle -> max
    load["value"] = 1.0
    assert limiter.get_effective_limit() == 2  # saturated -> min
    load["value"] = 0.5  # midway between low (0.3) and high (0.7) thresholds
    mid = limiter.get_effective_limit()
    assert 2 < mid < 40  # interpolated between min and max


# ---------------------------------------------------------------------------
# Management command: ratelimit_health against real backends
# ---------------------------------------------------------------------------


def test_ratelimit_health_reports_healthy(real_backend):
    """``ratelimit_health`` probes a reachable real backend and reports status.

    Real-life: a monitoring cron runs ``manage.py ratelimit_health --json``.
    For the memory/redis/mongodb backends (which expose a synchronous
    ``health_check`` / ``get_count`` probe) it reports ``healthy: true`` while
    the service is up. The ``async_redis`` backend has no synchronous probe
    (its ``get_count`` raises ``NotImplementedError``), so the sync command
    honestly reports it unhealthy -- a real, observable backend limitation.
    """
    import json

    out = StringIO()
    call_command("ratelimit_health", "--json", stdout=out)
    data = json.loads(out.getvalue())

    if real_backend == "async_redis":
        assert data["healthy"] is False
        assert data.get("error")
    else:
        assert data["healthy"] is True
        assert data.get("error") in (None, "")


@skip_without_redis
def test_ratelimit_health_reports_unhealthy_when_backend_down():
    """``ratelimit_health`` reports an unreachable Redis as unhealthy.

    Real-life: Redis is down; the health command's JSON shows ``healthy: false``
    with an error so the monitor can page someone. fail-open is enabled so the
    backend constructs, but ``health_check()`` still probes the real connection
    and reports the failure (it does not get masked by fail-open).
    """
    import json

    with override_settings(
        RATELIMIT_BACKEND=REDIS,
        RATELIMIT_REDIS={"host": REDIS_HOST, "port": DEAD_REDIS_PORT, "db": 0},
        RATELIMIT_FAIL_OPEN=True,
    ):
        reset_settings()
        clear_backend_cache()
        try:
            out = StringIO()
            call_command("ratelimit_health", "--json", stdout=out)
            data = json.loads(out.getvalue())
            assert data["healthy"] is False
            assert data.get("error")
        finally:
            clear_backend_cache()
            reset_settings()


# ---------------------------------------------------------------------------
# Management command: ratelimit_cleanup on the REAL database backend
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ratelimit_cleanup_reports_and_removes_expired_rows():
    """``ratelimit_cleanup`` reports then deletes expired DB rate-limit rows.

    Real-life: a nightly cron prunes the rate-limit tables. We seed expired
    counters/entries plus a fresh (non-expired) one, prove ``--dry-run`` finds
    but does not delete them, then prove a real run deletes only the expired
    rows and leaves the live one intact.
    """
    import json
    from datetime import timedelta

    from django.utils import timezone

    from django_smart_ratelimit.models import RateLimitCounter, RateLimitEntry

    with use_backend("database"):
        now = timezone.now()
        past = now - timedelta(minutes=5)
        future = now + timedelta(minutes=5)

        # Two expired rows (window_end / expires_at in the past)...
        expired_counter = RateLimitCounter.objects.create(
            key=f"cleanup-counter-expired-{uuid.uuid4().hex}",
            count=1,
            window_start=past - timedelta(minutes=1),
            window_end=past,
        )
        expired_entry = RateLimitEntry.objects.create(
            key=f"cleanup-entry-expired-{uuid.uuid4().hex}",
            timestamp=past,
            expires_at=past,
        )
        # ...and one still-live counter that must survive cleanup.
        live_counter = RateLimitCounter.objects.create(
            key=f"cleanup-counter-live-{uuid.uuid4().hex}",
            count=1,
            window_start=now,
            window_end=future,
        )

        # Dry run: it should FIND the expired rows but delete nothing.
        out = StringIO()
        call_command("ratelimit_cleanup", "--dry-run", "--json", stdout=out)
        dry = json.loads(out.getvalue())
        assert dry["dry_run"] is True
        assert dry["counters"]["found"] >= 1
        assert dry["entries"]["found"] >= 1
        assert dry["total_deleted"] == 0
        assert RateLimitCounter.objects.filter(id=expired_counter.id).exists()
        assert RateLimitEntry.objects.filter(id=expired_entry.id).exists()

        # Real run: expired rows are deleted, the live row stays.
        out = StringIO()
        call_command("ratelimit_cleanup", "--json", stdout=out)
        real = json.loads(out.getvalue())
        assert real["dry_run"] is False
        assert real["counters"]["deleted"] >= 1
        assert real["entries"]["deleted"] >= 1
        assert not RateLimitCounter.objects.filter(id=expired_counter.id).exists()
        assert not RateLimitEntry.objects.filter(id=expired_entry.id).exists()
        assert RateLimitCounter.objects.filter(id=live_counter.id).exists()


@pytest.mark.django_db
def test_ratelimit_cleanup_removes_stale_token_buckets():
    """``ratelimit_cleanup --stale-days`` prunes stale token buckets only.

    Real-life: old token-bucket rows for keys that went quiet pile up; the
    cleanup command removes buckets untouched beyond ``--stale-days`` while
    keeping recently-active ones.
    """
    import json
    from datetime import timedelta

    from django.utils import timezone

    from django_smart_ratelimit.models import RateLimitTokenBucket

    with use_backend("database"):
        now = timezone.now()
        stale = RateLimitTokenBucket.objects.create(
            key=f"cleanup-bucket-stale-{uuid.uuid4().hex}",
            tokens=5.0,
            last_update=now - timedelta(days=30),
            bucket_size=10,
            refill_rate=1.0,
        )
        fresh = RateLimitTokenBucket.objects.create(
            key=f"cleanup-bucket-fresh-{uuid.uuid4().hex}",
            tokens=5.0,
            last_update=now,
            bucket_size=10,
            refill_rate=1.0,
        )

        out = StringIO()
        call_command("ratelimit_cleanup", "--stale-days=7", "--json", stdout=out)
        data = json.loads(out.getvalue())
        assert data["token_buckets"]["found"] >= 1
        assert data["token_buckets"]["deleted"] >= 1
        assert not RateLimitTokenBucket.objects.filter(id=stale.id).exists()
        assert RateLimitTokenBucket.objects.filter(id=fresh.id).exists()
