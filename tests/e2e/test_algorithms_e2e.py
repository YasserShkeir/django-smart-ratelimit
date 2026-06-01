"""Real-backend end-to-end scenarios for the four rate-limit algorithms.

Each test drives the public ``@rate_limit`` decorator against a REAL store
(live Redis, live MongoDB, the in-process memory backend, or the real Django
test database) — never a mock. Scenarios are written from a real-life angle:
a bursty client vs a steady client, an API key allowed to burst then throttled,
a never-refill quota bucket, a smoothly-draining leaky bucket, etc.

Coverage map (by algorithm / option):

* sliding_window  — rolling window blocks-after-N; independent buckets per key;
  the window slides (old hits age out) rather than resetting on a hard edge.
* fixed_window    — clock-aligned counting; ``get_count``/``reset`` correctness
  read back off the real store; rollover at the clock boundary.
* token_bucket    — burst up to ``bucket_size`` then block; refill over time;
  ``initial_tokens`` (cold start empty/partial); ``tokens_per_request`` weight;
  ``refill_rate=0`` never-refill quota edge (asserted to truly never refill on
  Redis, i.e. NOT a silent window fallback); per-key isolation; bucket headers.
* leaky_bucket    — database backend via ``use_backend('database')``: smooth
  drain at ``leak_rate``, ``bucket_capacity`` overflow, ``cost_per_request``
  weighting, per-key isolation.

The ``real_backend`` fixture flushes the store and sets fresh state before and
after every test, and every test uses DISTINCT IPs/keys, so tests never depend
on one another.
"""

import time

import pytest

from django.http import HttpResponse, JsonResponse
from django.test import override_settings

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import clear_backend_cache, get_backend
from django_smart_ratelimit.enums import Algorithm

from .conftest import (
    MEMORY,
    REDIS,
    exhaust,
    make_request,
    skip_without_redis,
    use_backend,
)

# ``real_backend`` / ``native_bucket_backend`` are pytest fixtures from
# conftest.py; they are auto-discovered by name when used as test parameters,
# so they need no explicit import here.

# ---------------------------------------------------------------------------
# Small view factories. Each returns a fresh decorated view so a test's bucket
# state lives only on the real store, not in any decorator-level cache.
# ---------------------------------------------------------------------------


def _ok_view(**decorator_kwargs):
    """Build a JSON view wrapped with @rate_limit(**decorator_kwargs)."""

    @rate_limit(**decorator_kwargs)
    def view(_request):
        return JsonResponse({"ok": True})

    return view


def _hdr_view(**decorator_kwargs):
    """Build a plain HttpResponse view (carries .headers for assertions)."""

    @rate_limit(**decorator_kwargs)
    def view(_request):
        return HttpResponse("ok")

    return view


def _set_backend_algorithm(algorithm):
    """Pin the backend's *counting* algorithm and rebuild the cached backend.

    The standard sliding/fixed window path counts according to the backend's
    own ``_algorithm`` attribute, which is read from ``RATELIMIT_ALGORITHM`` at
    construction time (the decorator's ``algorithm=`` arg only routes the
    bucket algorithms). Tests that assert ``get_count``/``reset`` semantics on
    the real store must therefore set the setting and force a fresh backend.
    """
    ov = override_settings(RATELIMIT_ALGORITHM=str(algorithm))
    ov.enable()
    clear_backend_cache()
    return ov


# ===========================================================================
# SLIDING WINDOW
# ===========================================================================


def test_sliding_window_blocks_after_n_and_isolates_keys(real_backend):
    """Sliding window 3/min per IP.

    A single client hammering one IP gets exactly 3 OKs then 429s, while a
    second client on a different IP is completely unaffected (independent
    buckets keyed by IP). Verified on every real backend.
    """
    view = _ok_view(key="ip", rate="3/m", algorithm=Algorithm.SLIDING_WINDOW)

    attacker = exhaust(view, 5, ip="198.51.100.1")
    assert attacker == [200, 200, 200, 429, 429]

    # A different IP shares nothing with the throttled one.
    legit = exhaust(view, 3, ip="198.51.100.2")
    assert legit == [200, 200, 200]


def test_sliding_window_rolls_off_old_hits(real_backend):
    """Sliding window 2/2s: the window genuinely slides.

    Fill the window, get blocked, then wait just past the window and confirm
    the oldest hits have aged out so requests are allowed again — i.e. it is a
    rolling window on the real store, not a hard fixed reset.
    """
    view = _ok_view(key="ip", rate="2/2s", algorithm=Algorithm.SLIDING_WINDOW)
    ip = "198.51.100.3"

    assert exhaust(view, 3, ip=ip) == [200, 200, 429]
    time.sleep(2.2)
    # Old entries have slid out of the 2s window; budget is available again.
    assert exhaust(view, 2, ip=ip) == [200, 200]


def test_sliding_window_per_user_bucket(real_backend):
    """Sliding window 2/min keyed by user id.

    Two authenticated users each get their own 2/min budget regardless of the
    shared client IP — the key template ``user:{user.id}`` isolates them.
    """
    from .conftest import AuthedUser

    view = _ok_view(
        key="user:{user.id}", rate="2/m", algorithm=Algorithm.SLIDING_WINDOW
    )

    u1 = AuthedUser(uid=8001)
    u2 = AuthedUser(uid=8002)
    shared_ip = "198.51.100.4"

    codes_u1 = [view(make_request(ip=shared_ip, user=u1)).status_code for _ in range(3)]
    codes_u2 = [view(make_request(ip=shared_ip, user=u2)).status_code for _ in range(3)]
    assert codes_u1 == [200, 200, 429]
    assert codes_u2 == [200, 200, 429]


# ===========================================================================
# FIXED WINDOW
# ===========================================================================


def test_fixed_window_blocks_after_n_and_isolates_keys(real_backend):
    """Fixed window 3/min per IP.

    Backend pinned to fixed_window counting. One IP gets 3 OKs then 429s; a
    different IP is unaffected. Exercised on every real backend.
    """
    ov = _set_backend_algorithm(Algorithm.FIXED_WINDOW)
    try:
        view = _ok_view(key="ip", rate="3/m", algorithm=Algorithm.FIXED_WINDOW)
        assert exhaust(view, 5, ip="203.0.113.21") == [200, 200, 200, 429, 429]
        assert exhaust(view, 3, ip="203.0.113.22") == [200, 200, 200]
    finally:
        ov.disable()
        clear_backend_cache()


def test_fixed_window_get_count_and_reset_on_real_store(real_backend):
    """Fixed window get_count/reset round-trips against the real store.

    Drive a fixed-window view a few times, then read the live counter back via
    the backend's ``get_count`` (clock-aligned key) and assert it matches the
    number of requests. Then ``reset`` the key on the real store and confirm
    the count is wiped and the budget is fresh again.
    """
    ov = _set_backend_algorithm(Algorithm.FIXED_WINDOW)
    try:
        key = "ip:203.0.113.23"
        view = _ok_view(key="ip", rate="5/m", algorithm=Algorithm.FIXED_WINDOW)

        assert exhaust(view, 3, ip="203.0.113.23") == [200, 200, 200]

        backend = get_backend()
        # The live counter reflects exactly the requests we made.
        assert backend.get_count(key, period=60) == 3

        # Reset wipes the real counter; a subsequent read sees zero and the
        # full budget is available again.
        backend.reset(key)
        assert backend.get_count(key, period=60) == 0
        assert exhaust(view, 5, ip="203.0.113.23") == [200, 200, 200, 200, 200]
    finally:
        ov.disable()
        clear_backend_cache()


def test_fixed_window_short_window_rolls_over(real_backend):
    """Fixed window 2/1s: a new clock window restores the budget.

    Exhaust the 1-second window, observe the block, then sleep past the next
    clock boundary and confirm the counter has rolled over so requests pass
    again — the canonical fixed-window reset behavior on the real store.
    """
    ov = _set_backend_algorithm(Algorithm.FIXED_WINDOW)
    try:
        view = _ok_view(key="ip", rate="2/1s", algorithm=Algorithm.FIXED_WINDOW)
        ip = "203.0.113.24"
        assert exhaust(view, 3, ip=ip) == [200, 200, 429]
        # Sleep well past a 1s clock-aligned bucket boundary.
        time.sleep(1.2)
        assert 200 in exhaust(view, 2, ip=ip)
    finally:
        ov.disable()
        clear_backend_cache()


# ===========================================================================
# TOKEN BUCKET
# ===========================================================================


def test_token_bucket_burst_then_block(native_bucket_backend):
    """Token bucket: an API client may burst up to bucket_size, then is blocked.

    Rate 2/m with bucket_size=5 and refill_rate=0 (so no tokens trickle back
    during the test): the very first burst of 5 requests succeeds, the 6th is
    rejected with 429. Models "allow a short burst, then throttle".
    """
    view = _ok_view(
        key="ip",
        rate="2/m",
        algorithm=Algorithm.TOKEN_BUCKET,
        algorithm_config={"bucket_size": 5, "refill_rate": 0},
    )
    codes = exhaust(view, 7, ip="192.0.2.31")
    assert codes[:5] == [200, 200, 200, 200, 200]
    assert codes[5:] == [429, 429]


def test_token_bucket_refills_over_time(native_bucket_backend):
    """Token bucket refills at refill_rate and lets traffic through again.

    bucket_size=2, refill_rate=5 tokens/sec. Drain the 2 tokens (2 OK, 1
    block), wait ~0.6s (>= 2 tokens refilled), and confirm requests succeed
    again. Demonstrates steady-state refill on the real store.
    """
    view = _ok_view(
        key="ip",
        rate="2/s",
        algorithm=Algorithm.TOKEN_BUCKET,
        algorithm_config={"bucket_size": 2, "refill_rate": 5},
    )
    ip = "192.0.2.32"
    assert exhaust(view, 3, ip=ip) == [200, 200, 429]
    time.sleep(0.6)  # ~3 tokens refilled at 5/s, capped at bucket_size
    assert exhaust(view, 2, ip=ip) == [200, 200]


def test_token_bucket_initial_tokens_cold_start_empty(native_bucket_backend):
    """Token bucket with initial_tokens=0 starts EMPTY (cold start).

    bucket_size=5 but initial_tokens=0 and refill_rate=0: the bucket begins
    empty, so the first request is immediately blocked even though capacity
    exists. Models a quota that must be granted (refilled) before any use.
    """
    view = _ok_view(
        key="ip",
        rate="5/m",
        algorithm=Algorithm.TOKEN_BUCKET,
        algorithm_config={
            "bucket_size": 5,
            "initial_tokens": 0,
            "refill_rate": 0,
        },
    )
    assert exhaust(view, 2, ip="192.0.2.33") == [429, 429]


def test_token_bucket_initial_tokens_partial(native_bucket_backend):
    """Token bucket with a partial initial fill.

    bucket_size=10, initial_tokens=2, refill_rate=0: exactly 2 requests are
    served from the partial starting balance, then the bucket is empty.
    """
    view = _ok_view(
        key="ip",
        rate="10/m",
        algorithm=Algorithm.TOKEN_BUCKET,
        algorithm_config={
            "bucket_size": 10,
            "initial_tokens": 2,
            "refill_rate": 0,
        },
    )
    assert exhaust(view, 4, ip="192.0.2.34") == [200, 200, 429, 429]


def test_token_bucket_weighted_cost_per_request(native_bucket_backend):
    """Token bucket where each request costs more than one token (cost=2).

    bucket_size=6, refill_rate=0, and the decorator ``cost=2`` makes every
    request consume two tokens, so 3 requests drain the bucket and the 4th is
    blocked. Models weighted/expensive operations consuming extra budget — this
    is the public ``cost=`` weighting path the token bucket honors natively.
    """
    view = _ok_view(
        key="ip",
        rate="6/m",
        algorithm=Algorithm.TOKEN_BUCKET,
        algorithm_config={"bucket_size": 6, "refill_rate": 0},
        cost=2,
    )
    assert exhaust(view, 4, ip="192.0.2.35") == [200, 200, 200, 429]


def test_token_bucket_never_refill_quota_redis_only():
    """refill_rate=0 is a true never-refill quota on REAL Redis.

    This is the important edge: with refill_rate=0 the bucket must NEVER refill
    and must NOT silently fall back to window counting. We assert on real Redis
    specifically (native Lua token_bucket_check): a bucket of 3 grants exactly
    3 lifetime requests, and after a wait that WOULD have refilled any
    window/positive-rate bucket, the client is still blocked.
    """
    from .conftest import REDIS_UP

    if not REDIS_UP:
        pytest.skip("live Redis unavailable")

    with use_backend("redis"):
        # Confirm we are exercising the native atomic token-bucket path, not a
        # generic fallback — that is the whole point of this assertion.
        backend = get_backend()
        assert hasattr(backend, "token_bucket_check")

        view = _ok_view(
            key="ip",
            rate="100/s",  # period is large; refill_rate=0 overrides any drip
            algorithm=Algorithm.TOKEN_BUCKET,
            algorithm_config={"bucket_size": 3, "refill_rate": 0},
        )
        ip = "192.0.2.36"
        assert exhaust(view, 4, ip=ip) == [200, 200, 200, 429]

        # Wait long enough that a refilling bucket (or a 1s window) would have
        # recovered. A never-refill bucket stays empty.
        time.sleep(1.2)
        assert exhaust(view, 2, ip=ip) == [429, 429]


def test_token_bucket_isolated_per_api_key(native_bucket_backend):
    """Token bucket keyed per API key: one tenant's burst doesn't starve another.

    bucket_size=2, refill_rate=0, key on the X-Api-Key header. Tenant A drains
    its bucket and gets blocked; tenant B still has its full burst available.
    """
    view = _ok_view(
        key="header:X-Api-Key",
        rate="2/m",
        algorithm=Algorithm.TOKEN_BUCKET,
        algorithm_config={"bucket_size": 2, "refill_rate": 0},
    )

    def hit(api_key):
        req = make_request(ip="192.0.2.37", headers={"X-Api-Key": api_key})
        return view(req).status_code

    a = [hit("tenant-A") for _ in range(3)]
    b = [hit("tenant-B") for _ in range(3)]
    assert a == [200, 200, 429]
    assert b == [200, 200, 429]


def test_token_bucket_headers_on_allowed_response(native_bucket_backend):
    """Allowed token-bucket responses carry bucket headers reflecting drain.

    Each served request decrements X-RateLimit-Bucket-Remaining and the
    response advertises X-RateLimit-Bucket-Size. (Blocked 429s use the generic
    error response, so we assert the informative headers on the 2xx path.)
    """
    view = _hdr_view(
        key="ip",
        rate="4/m",
        algorithm=Algorithm.TOKEN_BUCKET,
        algorithm_config={"bucket_size": 4, "refill_rate": 0},
    )
    ip = "192.0.2.38"

    r1 = view(make_request(ip=ip))
    assert r1.status_code == 200
    assert r1.headers["X-RateLimit-Bucket-Size"] == "4"
    rem1 = int(r1.headers["X-RateLimit-Bucket-Remaining"])

    r2 = view(make_request(ip=ip))
    rem2 = int(r2.headers["X-RateLimit-Bucket-Remaining"])
    # Consuming a token strictly reduces the advertised remaining tokens.
    assert rem2 < rem1


# ===========================================================================
# LEAKY BUCKET  (database backend — native leaky_bucket_check)
# ===========================================================================


@pytest.mark.django_db
def test_leaky_bucket_capacity_then_overflow_database():
    """Leaky bucket on the database backend: fill to capacity, then overflow.

    bucket_capacity=3, leak_rate=0 (no drain during the test): the bucket
    accepts exactly 3 requests then rejects the rest. The database backend
    provides the native, atomic ``leaky_bucket_check`` this algorithm needs.
    """
    with use_backend("database"):
        backend = get_backend()
        assert hasattr(backend, "leaky_bucket_check")

        view = _ok_view(
            key="ip",
            rate="3/m",
            algorithm=Algorithm.LEAKY_BUCKET,
            algorithm_config={"bucket_capacity": 3, "leak_rate": 0},
        )
        assert exhaust(view, 5, ip="192.0.2.41") == [200, 200, 200, 429, 429]


@pytest.mark.django_db
def test_leaky_bucket_smooth_drain_database():
    """Leaky bucket drains smoothly at leak_rate, admitting new traffic.

    bucket_capacity=2, leak_rate=5/s. Fill the bucket (2 OK, 1 reject), wait
    ~0.6s so several units leak out, then confirm new requests are admitted —
    the smooth, burst-free drain that distinguishes leaky from token bucket.
    """
    with use_backend("database"):
        view = _ok_view(
            key="ip",
            rate="2/s",
            algorithm=Algorithm.LEAKY_BUCKET,
            algorithm_config={"bucket_capacity": 2, "leak_rate": 5},
        )
        ip = "192.0.2.42"
        assert exhaust(view, 3, ip=ip) == [200, 200, 429]
        time.sleep(0.6)  # ~3 units drained at 5/s
        assert exhaust(view, 2, ip=ip) == [200, 200]


@pytest.mark.django_db
def test_leaky_bucket_weighted_cost_per_request_database():
    """Leaky bucket honoring a per-request weight (cost=2) on the DB backend.

    bucket_capacity=4, leak_rate=0, and the decorator ``cost=2`` makes each
    request add 2 to the level, so 2 requests fill the bucket and the 3rd
    overflows. This is the public ``cost=`` weighting path for leaky bucket.
    """
    with use_backend("database"):
        view = _ok_view(
            key="ip",
            rate="4/m",
            algorithm=Algorithm.LEAKY_BUCKET,
            algorithm_config={"bucket_capacity": 4, "leak_rate": 0},
            cost=2,
        )
        assert exhaust(view, 3, ip="192.0.2.43") == [200, 200, 429]


@pytest.mark.django_db
def test_leaky_bucket_isolated_per_key_database():
    """Leaky buckets are independent per key on the database backend.

    Two distinct IPs each get their own capacity-2 bucket; exhausting one
    leaves the other untouched.
    """
    with use_backend("database"):
        view = _ok_view(
            key="ip",
            rate="2/m",
            algorithm=Algorithm.LEAKY_BUCKET,
            algorithm_config={"bucket_capacity": 2, "leak_rate": 0},
        )
        assert exhaust(view, 3, ip="192.0.2.44") == [200, 200, 429]
        assert exhaust(view, 2, ip="192.0.2.45") == [200, 200]


# ===========================================================================
# TOKEN BUCKET  (database backend — native token_bucket_check)
# ===========================================================================


@pytest.mark.django_db
def test_token_bucket_burst_then_block_database():
    """Token bucket on the database backend uses the native token_bucket_check.

    bucket_size=3, refill_rate=0: the first 3 requests burst through and the
    rest are blocked. The database backend implements a native, row-locked
    ``token_bucket_check`` (it does NOT silently fall back to window counting),
    so this exercises the DB bucket path directly — the analogue of the
    Redis/memory native-bucket tests above.
    """
    with use_backend("database"):
        backend = get_backend()
        assert hasattr(backend, "token_bucket_check")

        view = _ok_view(
            key="ip",
            rate="3/m",
            algorithm=Algorithm.TOKEN_BUCKET,
            algorithm_config={"bucket_size": 3, "refill_rate": 0},
        )
        assert exhaust(view, 5, ip="192.0.2.51") == [200, 200, 200, 429, 429]


@pytest.mark.django_db
def test_token_bucket_isolated_per_key_database():
    """Native DB token buckets are independent per key.

    Two IPs each get their own capacity-2 bucket; draining one leaves the other
    with its full allowance.
    """
    with use_backend("database"):
        view = _ok_view(
            key="ip",
            rate="2/m",
            algorithm=Algorithm.TOKEN_BUCKET,
            algorithm_config={"bucket_size": 2, "refill_rate": 0},
        )
        assert exhaust(view, 3, ip="192.0.2.52") == [200, 200, 429]
        assert exhaust(view, 2, ip="192.0.2.53") == [200, 200]


# ===========================================================================
# MULTI BACKEND  (bucket algorithms degrade to window counting)
# ===========================================================================


@skip_without_redis
def test_multibackend_token_bucket_falls_back_to_window():
    """A MultiBackend has no native bucket op, so token_bucket degrades to window.

    ``MultiBackend`` delegates ``incr()`` / ``get_count()`` to its child backends
    but does not implement ``token_bucket_check``, so the decorator catches the
    ``NotImplementedError`` and falls back to plain window counting (the same
    graceful degradation MongoDB uses). This test PINS that documented behavior:
    with ``rate=2/m`` the ``bucket_size=5`` config is ignored and exactly 2
    requests pass per window — NOT a 5-token burst. If ``MultiBackend`` ever
    gains native bucket routing, update this test to assert burst semantics.
    """
    redis_module = pytest.importorskip("redis")
    client = redis_module.Redis(host="localhost", port=6379, db=0)
    client.flushdb()
    ov = override_settings(
        RATELIMIT_BACKEND="django_smart_ratelimit.backends.multi.MultiBackend",
        RATELIMIT_BACKENDS=[
            {
                "name": "primary",
                "backend": REDIS,
                "config": {"host": "localhost", "port": 6379, "db": 0},
            },
            {"name": "fallback", "backend": MEMORY, "config": {}},
        ],
        RATELIMIT_MULTI_BACKEND_STRATEGY="first_healthy",
    )
    ov.enable()
    clear_backend_cache()
    try:
        view = _ok_view(
            key="ip",
            rate="2/m",
            algorithm=Algorithm.TOKEN_BUCKET,
            algorithm_config={"bucket_size": 5, "refill_rate": 0},
        )
        # Native bucket_size=5 would allow a 5-burst; window fallback allows 2.
        assert exhaust(view, 5, ip="192.0.2.61") == [200, 200, 429, 429, 429]
    finally:
        clear_backend_cache()
        client.flushdb()
        ov.disable()
