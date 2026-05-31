"""Real-backend end-to-end scenarios for ASYNC rate limiting.

These exercise the two async public entry points against REAL storage (live
Redis / live MongoDB / in-process memory) -- never a mocked backend:

    * ``@rate_limit`` applied to an ``async def`` view. The decorator
      auto-detects the coroutine and runs an async wrapper that awaits the
      view, increments the real store via ``aincr`` / ``sync_to_async(incr)``,
      and honors ``block=``, ``cost=`` and ``algorithm="token_bucket"`` with
      true bucket semantics (run off the event loop) on backends with native
      ``token_bucket_check`` support.
    * the standalone ``@aratelimit`` decorator. NOTE: ``@aratelimit`` is
      WINDOW-ONLY -- it always calls ``acheck_rate_limit`` (a counting
      increment) and has no ``algorithm`` / ``cost`` knobs, so its bucket of
      ``N`` is a plain per-window counter.

Real-life framing: an async API endpoint (ASGI) is hammered by a client
burst; we assert exactly when the 4xx kicks in, that distinct callers get
independent buckets, and that the advertised ``X-RateLimit-*`` headers match.

asyncio_mode=auto is configured for the suite, so ``async def`` tests run under
pytest-asyncio; tests are additionally marked ``asyncio`` to match project
style.
"""

import pytest

from django.http import HttpResponse, JsonResponse

from django_smart_ratelimit import aratelimit, rate_limit

from .conftest import (
    MEMORY,
    REDIS,
    REDIS_UP,
    AuthedUser,
    make_request,
    skip_without_redis,
    use_backend,
)

pytestmark = pytest.mark.asyncio


async def aexhaust(view, n, ip="198.51.100.7", **kwargs):
    """Await an async view ``n`` times from one IP; return the status codes.

    The sync ``exhaust`` helper in conftest cannot drive a coroutine view, so
    this is the async sibling: each call is a fresh realistic request from the
    same client IP, hitting the real backend store every time.
    """
    codes = []
    for _ in range(n):
        resp = await view(make_request(ip=ip, **kwargs))
        codes.append(getattr(resp, "status_code", resp))
    return codes


# Token-bucket scenarios need a backend that implements an atomic, native
# ``token_bucket_check`` (memory + redis do). The async ``@rate_limit`` path
# runs that sync check off the event loop via ``sync_to_async`` so async views
# get real bucket semantics rather than window counting. async_redis / mongodb
# have no native bucket support, so they are intentionally excluded here.
_NATIVE_BUCKET_BACKENDS = [
    pytest.param("memory", MEMORY, {}, id="memory"),
    pytest.param(
        "redis",
        REDIS,
        {"RATELIMIT_REDIS": {"host": "localhost", "port": 6379, "db": 0}},
        id="redis",
        marks=skip_without_redis,
    ),
]


# ---------------------------------------------------------------------------
# @rate_limit on an async def view (coroutine auto-detected)
# ---------------------------------------------------------------------------


class TestAsyncRateLimitDecorator:
    """``@rate_limit`` auto-detecting an ``async def`` view, on every backend."""

    async def test_async_endpoint_burst_blocked_after_n(self, async_real_backend):
        """Async profile API: 5/min per IP.

        A client bursting the async endpoint gets the first 5 requests served
        (200) and is throttled (429) from the 6th onward -- verified against
        the real store on every available backend.
        """

        @rate_limit(key="ip", rate="5/m", backend=async_real_backend)
        async def profile(_request):
            return JsonResponse({"ok": True})

        codes = await aexhaust(profile, 7, ip="198.51.100.10")

        assert codes[:5] == [200] * 5
        assert codes[5:] == [429, 429]

    async def test_independent_buckets_per_ip(self, async_real_backend):
        """Two async clients from distinct IPs do not share a bucket.

        An attacker hammering from one IP is blocked while a legitimate user on
        another IP keeps getting 200s -- each IP keys its own real-store bucket.
        """

        @rate_limit(key="ip", rate="3/m", backend=async_real_backend)
        async def search(_request):
            return JsonResponse({"results": []})

        attacker = await aexhaust(search, 5, ip="198.51.100.21")
        victim = await aexhaust(search, 3, ip="198.51.100.22")

        assert attacker == [200, 200, 200, 429, 429]
        assert victim == [200, 200, 200]

    async def test_per_user_key_template_isolates_accounts(self, async_real_backend):
        """Async endpoint keyed by ``user:{user.id}``: budgets are per account.

        User 1001 exhausting their quota does not consume user 2002's budget,
        even when both arrive over the same connection/IP.
        """

        @rate_limit(key="user:{user.id}", rate="2/m", backend=async_real_backend)
        async def dashboard(_request):
            return HttpResponse("dash")

        u1 = AuthedUser(uid=1001)
        u2 = AuthedUser(uid=2002)

        first = [
            (await dashboard(make_request(ip="198.51.100.30", user=u1))).status_code
            for _ in range(3)
        ]
        second = [
            (await dashboard(make_request(ip="198.51.100.30", user=u2))).status_code
            for _ in range(2)
        ]

        assert first == [200, 200, 429]
        assert second == [200, 200]

    async def test_rate_limit_headers_present_on_async_response(
        self, async_real_backend
    ):
        """Async responses advertise X-RateLimit-* so clients can self-throttle.

        The very first request reports the full limit and a decremented
        remaining count; these come from the real backend's count.
        """

        @rate_limit(key="ip", rate="10/m", backend=async_real_backend)
        async def feed(_request):
            return JsonResponse({"items": []})

        resp = await feed(make_request(ip="198.51.100.40"))

        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Limit"] == "10"
        # First hit consumes one unit -> 9 remain.
        assert resp.headers["X-RateLimit-Remaining"] == "9"
        assert "X-RateLimit-Reset" in resp.headers

    async def test_block_false_shadows_allows_but_marks_request(
        self, async_real_backend
    ):
        """``block=False`` async endpoint: never returns 429, flags the breach.

        With non-blocking mode the over-limit request is still served (200) but
        the wrapper sets ``request.rate_limit_exceeded`` so the view (or
        downstream middleware) can react -- e.g. log, degrade, or add a banner.
        Real counts in the store drive when the flag flips on.
        """
        seen_flags = []

        @rate_limit(key="ip", rate="2/m", block=False, backend=async_real_backend)
        async def soft_limited(request):
            seen_flags.append(getattr(request, "rate_limit_exceeded", False))
            return HttpResponse("served")

        codes = await aexhaust(soft_limited, 4, ip="198.51.100.50")

        # Never blocked under block=False.
        assert codes == [200, 200, 200, 200]
        # First two requests are within budget; the 3rd and 4th breach it and
        # are flagged even though they were still served.
        assert seen_flags == [False, False, True, True]

    async def test_cost_consumes_multiple_units_per_request(self, async_real_backend):
        """Weighted async endpoint: each call costs 2 units of a 6/min budget.

        ``cost=2`` means three calls (2+2+2 = 6) exactly drain the window and
        the fourth is throttled -- exercising cost accounting through the real
        backend increment path on every backend.
        """

        @rate_limit(key="ip", rate="6/m", cost=2, backend=async_real_backend)
        async def expensive(_request):
            return JsonResponse({"ok": True})

        codes = await aexhaust(expensive, 4, ip="198.51.100.60")

        assert codes == [200, 200, 200, 429]

    async def test_cost_callable_charges_by_request(self, async_real_backend):
        """Async endpoint with a per-request cost callable on a 10/min budget.

        ``/export`` requests cost 5 units each; cheap reads cost 1. Two exports
        (10) exhaust the budget so a following export is blocked, while the
        callable is evaluated against the real request object.
        """

        def price(request):
            return 5 if request.path.startswith("/export") else 1

        @rate_limit(key="ip", rate="10/m", cost=price, backend=async_real_backend)
        async def api(_request):
            return JsonResponse({"ok": True})

        ip = "198.51.100.70"
        first = (await api(make_request(ip=ip, path="/export/big"))).status_code
        second = (await api(make_request(ip=ip, path="/export/big"))).status_code
        third = (await api(make_request(ip=ip, path="/export/big"))).status_code

        assert first == 200  # 5/10 used
        assert second == 200  # 10/10 used
        assert third == 429  # would be 15/10 -> blocked

    async def test_skip_if_async_predicate_bypasses_limit(self, async_real_backend):
        """Async endpoint skipping internal traffic via an async ``skip_if``.

        Requests carrying the internal marker bypass the limiter entirely (the
        backend is never touched), so the internal caller is never throttled
        even far beyond the public 1/min limit.
        """

        async def is_internal(request):
            return request.META.get("HTTP_X_INTERNAL") == "yes"

        @rate_limit(
            key="ip", rate="1/m", skip_if=is_internal, backend=async_real_backend
        )
        async def metrics(_request):
            return HttpResponse("metrics")

        internal_codes = [
            (
                await metrics(
                    make_request(ip="198.51.100.80", headers={"X-Internal": "yes"})
                )
            ).status_code
            for _ in range(5)
        ]
        # A public caller on a different IP still hits the 1/min wall.
        public_codes = await aexhaust(metrics, 2, ip="198.51.100.81")

        assert internal_codes == [200] * 5
        assert public_codes == [200, 429]


# ---------------------------------------------------------------------------
# @rate_limit token_bucket on an async view (native-support backends)
# ---------------------------------------------------------------------------


class TestAsyncTokenBucketDecorator:
    """Async ``@rate_limit(algorithm='token_bucket')`` with real bucket math.

    The async wrapper runs the synchronous bucket check off the event loop via
    ``sync_to_async`` on backends that expose a native ``token_bucket_check``
    (memory + redis), so an async view gets genuine burst-then-refill behavior
    rather than plain window counting.
    """

    @pytest.mark.parametrize("name,path,extra", _NATIVE_BUCKET_BACKENDS)
    async def test_bucket_size_allows_burst_beyond_window_rate(self, name, path, extra):
        """Token bucket: bucket_size=10 absorbs a burst the 2/min window can't.

        rate='2/m' sets the steady refill (2 tokens/min) but bucket_size=10
        lets a fresh client spend up to 10 tokens immediately. So a 10-request
        burst all succeeds (window counting would have blocked after 2), and
        the 11th -- with the bucket drained and effectively no refill within
        the burst -- is throttled. This is the whole point of token_bucket on
        an async endpoint, and it is honored only because the backend has
        native bucket support.
        """
        with use_backend(name):

            @rate_limit(
                key="ip",
                rate="2/m",
                algorithm="token_bucket",
                algorithm_config={"bucket_size": 10},
                backend=name,
            )
            async def burst_api(_request):
                return JsonResponse({"ok": True})

            codes = await aexhaust(burst_api, 11, ip="198.51.100.90")

        assert codes[:10] == [200] * 10  # full bucket burst allowed
        assert codes[10] == 429  # bucket drained -> blocked

    @pytest.mark.parametrize("name,path,extra", _NATIVE_BUCKET_BACKENDS)
    async def test_bucket_emits_token_bucket_headers(self, name, path, extra):
        """Token-bucket async responses carry bucket-specific headers.

        On a native-support backend the wrapper attaches
        ``X-RateLimit-Bucket-Size`` / ``X-RateLimit-Bucket-Remaining`` (plus
        the standard limit/remaining/reset) so clients see the real bucket
        state, not just a window counter.
        """
        with use_backend(name):

            @rate_limit(
                key="ip",
                rate="3/m",
                algorithm="token_bucket",
                algorithm_config={"bucket_size": 5},
                backend=name,
            )
            async def metered(_request):
                return JsonResponse({"ok": True})

            resp = await metered(make_request(ip="198.51.100.95"))

        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Bucket-Size"] == "5"
        # One token spent out of five -> four remain in the bucket.
        assert resp.headers["X-RateLimit-Bucket-Remaining"] == "4"
        assert "X-RateLimit-Remaining" in resp.headers

    @pytest.mark.parametrize("name,path,extra", _NATIVE_BUCKET_BACKENDS)
    async def test_bucket_cost_drains_multiple_tokens(self, name, path, extra):
        """Token bucket honors ``cost`` natively as tokens-per-request.

        bucket_size=6 with cost=3 means two requests (3+3) drain the bucket and
        the third is throttled -- cost flows straight into the bucket's
        ``tokens_requested`` on a native-support backend.
        """
        with use_backend(name):

            @rate_limit(
                key="ip",
                rate="2/m",
                algorithm="token_bucket",
                algorithm_config={"bucket_size": 6},
                cost=3,
                backend=name,
            )
            async def heavy(_request):
                return JsonResponse({"ok": True})

            codes = await aexhaust(heavy, 3, ip="198.51.100.99")

        assert codes == [200, 200, 429]


# ---------------------------------------------------------------------------
# Standalone @aratelimit decorator (WINDOW-ONLY)
# ---------------------------------------------------------------------------


class TestAratelimitDecorator:
    """The standalone ``@aratelimit`` decorator against real async backends.

    ``@aratelimit`` is WINDOW-ONLY: it always runs ``acheck_rate_limit`` (a
    counting increment) and exposes no algorithm/cost options, so its limit of
    ``N`` is a plain per-window counter. It resolves its backend via
    ``get_async_backend`` (which promotes ``redis`` to the true AsyncRedis
    backend).
    """

    async def test_window_limit_blocks_after_n(self, async_real_backend):
        """@aratelimit login endpoint: 5/min per IP, window counting.

        An attacker hammering the async login from one IP is blocked after 5
        attempts; the count lives in the real store.
        """

        @aratelimit(key="ip", rate="5/m", backend=async_real_backend)
        async def login(_request):
            return JsonResponse({"token": "abc"})

        codes = await aexhaust(login, 7, ip="198.51.100.110")

        assert codes[:5] == [200] * 5
        assert codes[5:] == [429, 429]

    async def test_distinct_ips_have_independent_windows(self, async_real_backend):
        """@aratelimit keeps a separate window per IP key.

        One IP exhausting its 2/min window leaves a second IP's window
        untouched.
        """

        @aratelimit(key="ip", rate="2/m", backend=async_real_backend)
        async def signup(_request):
            return JsonResponse({"ok": True})

        a = await aexhaust(signup, 3, ip="198.51.100.120")
        b = await aexhaust(signup, 2, ip="198.51.100.121")

        assert a == [200, 200, 429]
        assert b == [200, 200]

    async def test_block_false_allows_but_flags_request(self, async_real_backend):
        """@aratelimit ``block=False``: serve over-limit but flag the request.

        Non-blocking mode never returns 429; instead the over-limit request is
        served and ``request.rate_limit_exceeded`` is set true so the view can
        observe the soft breach. Counts come from the real backend.
        """
        flags = []

        @aratelimit(key="ip", rate="2/m", block=False, backend=async_real_backend)
        async def soft(request):
            flags.append(getattr(request, "rate_limit_exceeded", False))
            return HttpResponse("ok")

        codes = await aexhaust(soft, 4, ip="198.51.100.130")

        assert codes == [200, 200, 200, 200]
        # The 3rd and 4th calls exceed the 2/min window and are flagged.
        assert flags[2] is True and flags[3] is True

    async def test_method_scoping_only_limits_targeted_verb(self, async_real_backend):
        """@aratelimit ``method='POST'`` limits writes but never reads.

        A write-heavy async endpoint throttles POSTs after the window fills,
        while GETs to the same key bypass the limit entirely (method filter
        short-circuits before any backend work).
        """

        @aratelimit(key="ip", rate="2/m", method="POST", backend=async_real_backend)
        async def resource(_request):
            return JsonResponse({"ok": True})

        ip = "198.51.100.140"
        posts = [
            (await resource(make_request(ip=ip, method="post"))).status_code
            for _ in range(3)
        ]
        gets = [
            (await resource(make_request(ip=ip, method="get"))).status_code
            for _ in range(5)
        ]

        assert posts == [200, 200, 429]
        assert gets == [200] * 5

    async def test_headers_advertise_window_state(self, async_real_backend):
        """@aratelimit attaches X-RateLimit-* describing the window.

        The response advertises the configured limit so async clients can pace
        themselves; remaining/reset are derived from the real backend metadata.
        """

        @aratelimit(key="ip", rate="8/m", backend=async_real_backend)
        async def feed(_request):
            return JsonResponse({"items": []})

        resp = await feed(make_request(ip="198.51.100.150"))

        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Limit"] == "8"
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers


@pytest.mark.skipif(not REDIS_UP, reason="live Redis unavailable")
class TestAratelimitAsyncRedisBackend:
    """@aratelimit explicitly resolving the native AsyncRedis backend.

    ``get_async_backend`` promotes the ``redis`` name to the true async Redis
    client (non-blocking ``aincr`` Lua eval), so this verifies the standalone
    async decorator end-to-end against the dedicated async backend rather than
    a sync-wrapped one.
    """

    async def test_async_redis_window_counts_real_store(self):
        """@aratelimit(backend='redis') hits the real async Redis store.

        Window of 4/min: the burst is allowed for 4 calls then blocked, with
        the counter persisted in the live Redis via the async Lua increment.
        """
        with use_backend("async_redis"):

            @aratelimit(key="ip", rate="4/m", backend="redis")
            async def ping(_request):
                return JsonResponse({"pong": True})

            codes = await aexhaust(ping, 6, ip="198.51.100.160")

        assert codes[:4] == [200] * 4
        assert codes[4:] == [429, 429]
