"""Real-backend end-to-end scenarios for the SYNC ``rate_limit`` decorator.

Every scenario drives the decorator (and its ``ratelimit`` alias) against REAL
storage — a live Redis, a live MongoDB, the real Django test DB, or the
in-process memory backend — via the shared harness in ``conftest.py``. Nothing
about the rate-limit store is mocked: the limiter actually increments real
counters and the assertions check observable behavior (HTTP 200 vs 429,
``X-RateLimit-*`` headers, per-key bucket isolation, soft-limit flags, shadow
logging, CIDR allow/deny policy, custom 429 bodies).

The ``real_backend`` fixture re-runs each backend-agnostic scenario on every
available non-DB backend; database-backend scenarios use
``use_backend("database")`` together with ``@pytest.mark.django_db``. Each test
uses distinct IPs / keys so the tests stay independent even though they share
one live store.
"""

import logging

import pytest

from django.http import HttpResponse, JsonResponse

from django_smart_ratelimit import rate_limit, ratelimit
from django_smart_ratelimit.enums import RateLimitKey

from .conftest import (
    AnonUser,
    AuthedUser,
    exhaust,
    make_request,
    use_backend,
)

# Logger that emits the SHADOW_RATE_LIMIT_BLOCK line (see pipeline.py).
SHADOW_LOGGER = "django_smart_ratelimit.pipeline"


# ---------------------------------------------------------------------------
# Rate parsing: "N/s", "N/m", "N/h" all enforced against the real store.
# ---------------------------------------------------------------------------


class TestRateParsing:
    """The ``rate`` string maps to a real limit/period enforced by the store."""

    def test_per_minute_blocks_after_n(self, real_backend):
        """5/m: the first 5 requests from one IP pass, the 6th is blocked (429)."""

        @rate_limit(key="ip", rate="5/m")
        def view(_request):
            return HttpResponse("ok")

        codes = exhaust(view, 6, ip="198.51.100.1")
        assert codes[:5] == [200, 200, 200, 200, 200]
        assert codes[5] == 429

    def test_per_hour_limit(self, real_backend):
        """100/h: request 100 passes, request 101 is blocked."""

        @rate_limit(key="ip", rate="100/h")
        def view(_request):
            return HttpResponse("ok")

        codes = exhaust(view, 101, ip="198.51.100.2")
        assert codes.count(200) == 100
        assert codes[-1] == 429

    def test_per_second_limit(self, real_backend):
        """10/s: ten quick requests pass, the eleventh in the same second blocks."""

        @rate_limit(key="ip", rate="10/s")
        def view(_request):
            return HttpResponse("ok")

        codes = exhaust(view, 11, ip="198.51.100.3")
        assert codes[:10] == [200] * 10
        assert codes[10] == 429


# ---------------------------------------------------------------------------
# Key types: ip / user / user_or_ip / header / param / custom callable.
# Each must produce INDEPENDENT buckets per distinct key value.
# ---------------------------------------------------------------------------


class TestKeyTypes:
    """Every supported key type buckets distinct principals independently."""

    def test_key_ip_independent_buckets(self, real_backend):
        """Login throttle: an attacker hammering one IP is blocked.

        A legitimate user on another IP is completely unaffected.
        """

        @rate_limit(key="ip", rate="5/m")
        def login(_request):
            return HttpResponse("ok")

        attacker = exhaust(login, 7, ip="203.0.113.50")
        assert attacker[:5] == [200] * 5
        assert attacker[5] == 429 and attacker[6] == 429

        # A different IP has its own fresh bucket.
        victim = exhaust(login, 5, ip="203.0.113.51")
        assert victim == [200] * 5

    def test_key_user_buckets_by_user_id(self, real_backend):
        """Key='user' gives two authenticated users separate buckets.

        The same user is throttled across requests regardless of source IP.
        """

        @rate_limit(key="user", rate="3/m")
        def view(_request):
            return HttpResponse("ok")

        u1 = AuthedUser(uid=9001)
        codes_u1 = [
            view(make_request(ip="203.0.113.60", user=u1)).status_code for _ in range(4)
        ]
        assert codes_u1 == [200, 200, 200, 429]

        # Same user from a *different* IP shares the (already-exhausted) bucket.
        assert view(make_request(ip="203.0.113.61", user=u1)).status_code == 429

        # A different user is unaffected.
        u2 = AuthedUser(uid=9002)
        assert view(make_request(ip="203.0.113.60", user=u2)).status_code == 200

    def test_key_user_or_ip_falls_back_to_ip_when_anonymous(self, real_backend):
        """Key='user_or_ip' keys anonymous traffic on IP, auth traffic on user.

        So an anonymous flood does not consume an authenticated user's quota.
        """

        @rate_limit(key="user_or_ip", rate="3/m")
        def view(_request):
            return HttpResponse("ok")

        # Anonymous: buckets by IP.
        anon = [
            view(make_request(ip="203.0.113.70", user=AnonUser())).status_code
            for _ in range(4)
        ]
        assert anon == [200, 200, 200, 429]

        # Authenticated user from the SAME IP has an independent (user) bucket.
        authed = AuthedUser(uid=7777)
        assert view(make_request(ip="203.0.113.70", user=authed)).status_code == 200

    def test_key_header_api_key(self, real_backend):
        """Keying on the X-Api-Key header gives each API key its own quota.

        One noisy key cannot exhaust another tenant's budget.
        """

        @rate_limit(key=f"{RateLimitKey.HEADER}:X-Api-Key", rate="4/m")
        def api(_request):
            return JsonResponse({"ok": True})

        def call(api_key):
            return api(
                make_request(ip="203.0.113.80", headers={"X-Api-Key": api_key})
            ).status_code

        first_key = [call("key-aaa") for _ in range(5)]
        assert first_key == [200, 200, 200, 200, 429]

        # A different API key from the same IP is on its own bucket.
        assert call("key-bbb") == 200

    def test_key_param_tenant(self, real_backend):
        """Keying on the ?tenant= query param defines the bucket per tenant.

        Per-tenant quotas hold even when requests share one source IP.
        """

        @rate_limit(key=f"{RateLimitKey.PARAM}:tenant", rate="3/m")
        def view(_request):
            return HttpResponse("ok")

        def call(tenant):
            return view(
                make_request(ip="203.0.113.90", params={"tenant": tenant})
            ).status_code

        acme = [call("acme") for _ in range(4)]
        assert acme == [200, 200, 200, 429]

        # Distinct tenant value -> distinct bucket.
        assert call("globex") == 200

    def test_custom_callable_key(self, real_backend):
        """A custom callable key (per-account bucket) is honored end to end.

        Buckets are isolated exactly as the callable's return value dictates.
        """

        def account_key(request, *args, **kwargs):
            return f"account:{request.META.get('HTTP_X_ACCOUNT', 'anon')}"

        @rate_limit(key=account_key, rate="2/m")
        def view(_request):
            return HttpResponse("ok")

        def call(account):
            return view(
                make_request(ip="203.0.113.100", headers={"X-Account": account})
            ).status_code

        acc1 = [call("alpha") for _ in range(3)]
        assert acc1 == [200, 200, 429]
        # Different account => fresh bucket.
        assert call("beta") == 200


# ---------------------------------------------------------------------------
# block=True / block=False behavior.
# ---------------------------------------------------------------------------


class TestBlockMode:
    """block=True returns 429; block=False sets a flag but still serves 200."""

    def test_block_true_returns_429(self, real_backend):
        """block=True (the default): over-limit requests get a hard 429."""

        @rate_limit(key="ip", rate="2/m", block=True)
        def view(_request):
            return HttpResponse("ok")

        codes = exhaust(view, 3, ip="203.0.113.110")
        assert codes == [200, 200, 429]

    def test_block_false_sets_flag_but_serves_200(self, real_backend):
        """Soft limit: block=False never returns 429.

        It marks request.rate_limit_exceeded so the view can degrade gracefully.
        """

        seen_flags = []

        @rate_limit(key="ip", rate="2/m", block=False)
        def view(request):
            seen_flags.append(getattr(request, "rate_limit_exceeded", False))
            return HttpResponse("ok")

        codes = exhaust(view, 4, ip="203.0.113.111")
        # Every request is served.
        assert codes == [200, 200, 200, 200]
        # The first two are within limit; the over-limit ones are flagged.
        assert seen_flags[0] is False and seen_flags[1] is False
        assert seen_flags[2] is True and seen_flags[3] is True


# ---------------------------------------------------------------------------
# skip_if: conditionally bypass rate limiting entirely.
# ---------------------------------------------------------------------------


class TestSkipIf:
    """skip_if short-circuits rate limiting when it returns True."""

    def test_skip_if_bypasses_limit_for_staff(self, real_backend):
        """Skip_if lets staff users bypass the limit entirely.

        Regular users are still throttled on the same endpoint.
        """

        @rate_limit(
            key="ip",
            rate="2/m",
            skip_if=lambda request: getattr(request.user, "is_staff", False),
        )
        def view(_request):
            return HttpResponse("ok")

        # Staff user — never counted, never blocked even past the limit.
        staff = AuthedUser(uid=1)
        staff.is_staff = True
        staff_codes = [
            view(make_request(ip="203.0.113.120", user=staff)).status_code
            for _ in range(5)
        ]
        assert staff_codes == [200] * 5

        # A non-staff caller on a different IP is throttled normally.
        regular = exhaust(view, 3, ip="203.0.113.121")
        assert regular == [200, 200, 429]


# ---------------------------------------------------------------------------
# cost: weighted requests, as an int and as a callable.
# ---------------------------------------------------------------------------


class TestCost:
    """cost lets expensive operations consume more of the budget."""

    def test_integer_cost_consumes_budget(self, real_backend):
        """cost=2 against a 6/m budget: 3 calls fit (2+2+2=6), the 4th blocks."""

        @rate_limit(key="ip", rate="6/m", cost=2)
        def view(_request):
            return HttpResponse("ok")

        codes = exhaust(view, 4, ip="203.0.113.130")
        assert codes == [200, 200, 200, 429]

    def test_callable_cost_weights_expensive_endpoint(self, real_backend):
        """Weighted endpoint: a callable cost charges POSTs (exports) 3x.

        Cheap GETs cost 1; all draw from the same 5/m budget.
        """

        def cost_fn(request):
            return 3 if request.method == "POST" else 1

        @rate_limit(key="ip", rate="5/m", cost=cost_fn)
        def view(_request):
            return HttpResponse("ok")

        ip = "203.0.113.131"
        # GET(1) + POST(3) + GET(1) = 5  -> all allowed.
        assert view(make_request(ip=ip, method="get")).status_code == 200
        assert view(make_request(ip=ip, method="post")).status_code == 200
        assert view(make_request(ip=ip, method="get")).status_code == 200
        # Budget exhausted: the next request is blocked.
        assert view(make_request(ip=ip, method="get")).status_code == 429


# ---------------------------------------------------------------------------
# shadow=True: allows past the limit but logs SHADOW_RATE_LIMIT_BLOCK.
# ---------------------------------------------------------------------------


class TestShadowMode:
    """shadow mode observes what *would* be blocked without enforcing it."""

    def test_shadow_allows_but_logs(self, real_backend, caplog):
        """Soft-rollout monitoring: shadow=True serves every request 200.

        It still emits a SHADOW_RATE_LIMIT_BLOCK log line once the limit spills.
        """

        @rate_limit(key="ip", rate="2/m", shadow=True)
        def view(_request):
            return HttpResponse("ok")

        with caplog.at_level(logging.INFO, logger=SHADOW_LOGGER):
            codes = exhaust(view, 6, ip="203.0.113.140")

        # Nothing is ever blocked in shadow mode.
        assert codes == [200] * 6
        # But the over-limit calls were logged for the operator to review.
        assert any(
            "SHADOW_RATE_LIMIT_BLOCK" in rec.getMessage() for rec in caplog.records
        )

    def test_shadow_false_enforces(self, real_backend):
        """Control: with shadow=False the same config enforces a hard 429."""

        @rate_limit(key="ip", rate="2/m", shadow=False)
        def view(_request):
            return HttpResponse("ok")

        codes = exhaust(view, 3, ip="203.0.113.141")
        assert codes == [200, 200, 429]


# ---------------------------------------------------------------------------
# allow_list (CIDR bypass) and deny_list (CIDR block); deny wins.
# ---------------------------------------------------------------------------


class TestAllowDenyLists:
    """CIDR allow/deny policy is evaluated before the backend; deny precedes."""

    def test_allow_list_internal_cidr_bypasses_limit(self, real_backend):
        """Internal-CIDR allowlist: hosts in 10.0.0.0/8 skip rate limiting.

        External IPs remain throttled.
        """

        @rate_limit(key="ip", rate="2/m", allow_list=["10.0.0.0/8"])
        def view(_request):
            return HttpResponse("ok")

        # Internal IP: bypasses the limit no matter how many calls.
        internal = exhaust(view, 6, ip="10.1.2.3")
        assert internal == [200] * 6

        # External IP: throttled normally.
        external = exhaust(view, 3, ip="203.0.113.150")
        assert external == [200, 200, 429]

    def test_deny_list_abusive_cidr_blocked(self, real_backend):
        """Abusive-IP denylist: a known-bad /24 is blocked with 429.

        The block happens from the very first request, before any quota is used.
        """

        @rate_limit(key="ip", rate="1000/m", deny_list=["192.0.2.0/24"])
        def view(_request):
            return HttpResponse("ok")

        # Deny-listed source is blocked immediately despite a huge limit.
        denied = exhaust(view, 3, ip="192.0.2.55")
        assert denied == [429, 429, 429]

        # A non-listed IP is served.
        assert view(make_request(ip="203.0.113.151")).status_code == 200

    def test_deny_wins_over_allow(self, real_backend):
        """When an IP matches both lists, deny takes precedence (fail-closed)."""

        @rate_limit(
            key="ip",
            rate="1000/m",
            allow_list=["10.0.0.0/8"],
            deny_list=["10.0.0.99"],
        )
        def view(_request):
            return HttpResponse("ok")

        # In allow CIDR but also explicitly denied -> blocked.
        assert view(make_request(ip="10.0.0.99")).status_code == 429
        # In allow CIDR and NOT denied -> bypasses the limit.
        assert view(make_request(ip="10.0.0.100")).status_code == 200


# ---------------------------------------------------------------------------
# response_callback: custom 429 body / status.
# ---------------------------------------------------------------------------


class TestResponseCallback:
    """response_callback fully controls the over-limit response."""

    def test_custom_429_body_and_status(self, real_backend):
        """A custom response_callback returns a branded JSON 429 body.

        Allowed requests still flow through the real view.
        """

        def custom_response(_request):
            return JsonResponse(
                {"error": "slow down", "support": "help@example.com"},
                status=429,
            )

        @rate_limit(key="ip", rate="1/m", response_callback=custom_response)
        def view(_request):
            return HttpResponse("ok")

        ip = "203.0.113.160"
        first = view(make_request(ip=ip))
        assert first.status_code == 200

        blocked = view(make_request(ip=ip))
        assert blocked.status_code == 429
        assert b"slow down" in blocked.content
        assert b"help@example.com" in blocked.content


# ---------------------------------------------------------------------------
# X-RateLimit-* headers on allowed responses (and on the 429).
# ---------------------------------------------------------------------------


class TestRateLimitHeaders:
    """Allowed responses advertise the standard X-RateLimit-* headers."""

    def test_headers_present_and_decrementing(self, real_backend):
        """Each allowed response carries X-RateLimit-Limit and Remaining.

        Remaining decreases as the bucket fills; the 429 reports zero remaining.
        """

        @rate_limit(key="ip", rate="3/m")
        def view(_request):
            return HttpResponse("ok")

        ip = "203.0.113.170"
        r1 = view(make_request(ip=ip))
        r2 = view(make_request(ip=ip))
        r3 = view(make_request(ip=ip))
        r4 = view(make_request(ip=ip))

        # Limit header is advertised on every allowed response.
        assert r1.headers["X-RateLimit-Limit"] == "3"
        assert "X-RateLimit-Reset" in r1.headers

        # Remaining counts down monotonically.
        remaining = [int(r.headers["X-RateLimit-Remaining"]) for r in (r1, r2, r3)]
        assert remaining == sorted(remaining, reverse=True)
        assert remaining[0] >= remaining[-1]

        # The blocked response reports the limit with zero remaining.
        assert r4.status_code == 429
        assert r4.headers["X-RateLimit-Limit"] == "3"
        assert r4.headers["X-RateLimit-Remaining"] == "0"


# ---------------------------------------------------------------------------
# The ``ratelimit`` alias behaves identically to ``rate_limit``.
# ---------------------------------------------------------------------------


class TestRatelimitAlias:
    """The django-ratelimit-compatible ``ratelimit`` alias is a true alias."""

    def test_alias_enforces_limit(self, real_backend):
        """@ratelimit(...) enforces exactly like @rate_limit(...)."""

        @ratelimit(key="ip", rate="2/m")
        def view(_request):
            return HttpResponse("ok")

        codes = exhaust(view, 3, ip="203.0.113.180")
        assert codes == [200, 200, 429]

    def test_alias_passes_all_options(self, real_backend, caplog):
        """The alias forwards block/shadow/cost/lists faithfully.

        shadow+cost here serves 200 throughout and logs a shadow block once the
        weighted budget spills.
        """

        @ratelimit(key="ip", rate="4/m", cost=2, shadow=True)
        def view(_request):
            return HttpResponse("ok")

        with caplog.at_level(logging.INFO, logger=SHADOW_LOGGER):
            codes = exhaust(view, 4, ip="203.0.113.181")

        # cost=2, budget 4 -> 2 calls fit; shadow keeps the rest at 200.
        assert codes == [200] * 4
        assert any(
            "SHADOW_RATE_LIMIT_BLOCK" in rec.getMessage() for rec in caplog.records
        )


# ---------------------------------------------------------------------------
# DATABASE backend scenarios (real Django test DB).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDatabaseBackend:
    """The same decorator semantics hold against the real Django test DB."""

    def test_login_throttle_on_database(self):
        """Login endpoint on the DB backend: 3/m per IP blocks the 4th attempt.

        A second IP keeps its own independent bucket.
        """

        with use_backend("database"):

            @rate_limit(key="ip", rate="3/m")
            def login(_request):
                return HttpResponse("ok")

            attacker = exhaust(login, 4, ip="203.0.113.190")
            assert attacker == [200, 200, 200, 429]

            # Independent bucket for a different IP.
            other = exhaust(login, 3, ip="203.0.113.191")
            assert other == [200, 200, 200]

    def test_soft_limit_flag_on_database(self):
        """Block=False on the DB backend: requests are served 200.

        The request is flagged once the limit is exceeded.
        """

        with use_backend("database"):
            seen = []

            @rate_limit(key="ip", rate="2/m", block=False)
            def view(request):
                seen.append(getattr(request, "rate_limit_exceeded", False))
                return HttpResponse("ok")

            codes = exhaust(view, 4, ip="203.0.113.192")
            assert codes == [200, 200, 200, 200]
            assert seen[2] is True and seen[3] is True

    def test_headers_on_database_backend(self):
        """Allowed responses on the DB backend advertise X-RateLimit-* headers."""

        with use_backend("database"):

            @rate_limit(key="ip", rate="5/m")
            def view(_request):
                return HttpResponse("ok")

            resp = view(make_request(ip="203.0.113.193"))
            assert resp.status_code == 200
            assert resp.headers["X-RateLimit-Limit"] == "5"
            assert "X-RateLimit-Remaining" in resp.headers
