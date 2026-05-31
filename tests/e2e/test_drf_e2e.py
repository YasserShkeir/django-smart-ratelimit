"""Real-backend end-to-end tests for the DRF throttle adapter.

These tests stand up REAL Django REST Framework views (an ``APIView`` and a
``ViewSet``), wire them into a URLconf, and drive them with DRF's
``APIClient`` against REAL storage (live Redis / async Redis / live MongoDB /
in-memory). The rate-limit backend is NEVER mocked — every counter increment
hits the actual store via ``django_smart_ratelimit``'s DRF throttle classes.

Scope under test (``django_smart_ratelimit.integrations.drf``):

    - ``UserRateLimitThrottle``  -- per-user bucket, IP fallback for anon.
    - ``AnonRateLimitThrottle``  -- per-IP bucket.
    - ``ScopedRateLimitThrottle`` -- rate resolved from ``view.throttle_scope``.
    - ``SmartRateLimitThrottle`` subclasses with:
        * a ``rate`` attribute, a callable ``rate``, a callable ``cost`` /
          ``get_cost`` override (weighted throttling),
        * the v4 decorator-parity attributes ``allow_list`` / ``deny_list`` /
          ``shadow``.

Observable behavior asserted: HTTP 200 vs 429, the ``Retry-After`` header /
``throttle.wait()`` value on a 429, independent buckets per distinct key
(per-IP, per-user, per-scope), authed-vs-anon tiers, deny-list blocking,
allow-list bypass, and shadow-mode allow-but-log.

The module is skipped entirely when DRF is not installed.
"""

import logging

import pytest

from django.test import override_settings
from django.urls import path

# ``real_backend`` is a fixture auto-discovered from tests/e2e/conftest.py; only
# the request-building helpers need importing here.
from .conftest import AuthedUser

try:
    from rest_framework import status, viewsets
    from rest_framework.response import Response
    from rest_framework.test import APIClient
    from rest_framework.views import APIView

    DRF_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when DRF is absent
    DRF_AVAILABLE = False

    APIClient = APIView = Response = viewsets = status = None  # type: ignore

from django_smart_ratelimit.integrations.drf import (  # noqa: E402
    AnonRateLimitThrottle,
    ScopedRateLimitThrottle,
    SmartRateLimitThrottle,
    UserRateLimitThrottle,
)

pytestmark = pytest.mark.skipif(
    not DRF_AVAILABLE, reason="Django REST Framework not installed"
)


# ---------------------------------------------------------------------------
# Real throttle subclasses exercised through real views.
# ---------------------------------------------------------------------------
if DRF_AVAILABLE:

    class LoginAnonThrottle(AnonRateLimitThrottle):
        """A tight per-IP login limit: 5 requests/minute."""

        rate = "5/m"

    class TieredUserThrottle(UserRateLimitThrottle):
        """Authed-user tier: 10/minute, keyed by user id (IP for anon)."""

        rate = "10/m"

    def _tiered_rate(throttle, request):
        """Callable rate: staff users get a far higher tier than mortals."""
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_staff", False):
            return "100/m"
        return "3/m"

    class CallableRateThrottle(SmartRateLimitThrottle):
        """Dynamic rate resolved per-request from the user's privilege."""

        scope = "callable_tier"
        rate = _tiered_rate

    class SearchCostThrottle(SmartRateLimitThrottle):
        """Weighted throttle: a 'deep' search costs more tokens than a cheap one.

        Budget is 10 tokens/minute. A request carrying ``?deep=1`` spends 5
        tokens; a normal request spends 1. ``get_cost`` reads the request, so
        two deep searches (10 tokens) exhaust the budget and the third deep
        search is blocked, while many cheap searches are still permitted.
        """

        scope = "search_cost"
        rate = "10/m"

        def get_cost(self, request, view):
            return 5 if request.query_params.get("deep") == "1" else 1

    class DenyListThrottle(AnonRateLimitThrottle):
        """Per-IP 100/m, but a known-bad CIDR is hard-blocked regardless."""

        rate = "100/m"
        deny_list = ["198.51.100.0/24"]

    class AllowListThrottle(AnonRateLimitThrottle):
        """Per-IP 2/m, but an internal CIDR bypasses throttling entirely."""

        rate = "2/m"
        allow_list = ["10.0.0.0/8"]

    class ShadowDenyThrottle(AnonRateLimitThrottle):
        """Deny-list in SHADOW mode: would-be blocks are allowed but logged."""

        rate = "100/m"
        deny_list = ["198.51.100.0/24"]
        shadow = True

    class ShadowRateThrottle(AnonRateLimitThrottle):
        """A new 2/m limit run in shadow: never blocks, only logs over-limit."""

        rate = "2/m"
        shadow = True

    # --- Views -------------------------------------------------------------

    class LoginView(APIView):
        """Public login endpoint protected per-IP (anon throttle)."""

        permission_classes = []
        throttle_classes = [LoginAnonThrottle]

        def post(self, request):
            return Response({"detail": "ok"})

    class ProfileView(APIView):
        """Authed endpoint: each user gets their own 10/m bucket."""

        permission_classes = []
        throttle_classes = [TieredUserThrottle]

        def get(self, request):
            return Response({"detail": "profile"})

    class CallableRateView(APIView):
        """Tier resolved at request time via a callable rate."""

        permission_classes = []
        throttle_classes = [CallableRateThrottle]

        def get(self, request):
            return Response({"detail": "ok"})

    class SearchView(APIView):
        """Weighted search endpoint (deep searches cost more)."""

        permission_classes = []
        throttle_classes = [SearchCostThrottle]

        def get(self, request):
            return Response({"detail": "results"})

    class ReportsView(APIView):
        """Scoped endpoint: rate comes from ``view.throttle_scope``."""

        permission_classes = []
        throttle_classes = [ScopedRateLimitThrottle]
        throttle_scope = "reports"

        def get(self, request):
            return Response({"detail": "report"})

    class ExportsView(APIView):
        """A second scoped endpoint with its own scope/bucket."""

        permission_classes = []
        throttle_classes = [ScopedRateLimitThrottle]
        throttle_scope = "exports"

        def get(self, request):
            return Response({"detail": "export"})

    class DenyListView(APIView):
        permission_classes = []
        throttle_classes = [DenyListThrottle]

        def get(self, request):
            return Response({"detail": "ok"})

    class AllowListView(APIView):
        permission_classes = []
        throttle_classes = [AllowListThrottle]

        def get(self, request):
            return Response({"detail": "ok"})

    class ShadowDenyView(APIView):
        permission_classes = []
        throttle_classes = [ShadowDenyThrottle]

        def get(self, request):
            return Response({"detail": "ok"})

    class ShadowRateView(APIView):
        permission_classes = []
        throttle_classes = [ShadowRateThrottle]

        def get(self, request):
            return Response({"detail": "ok"})

    class ItemViewSet(viewsets.ViewSet):
        """A real ViewSet whose actions are throttled per-IP at 5/m."""

        permission_classes = []
        throttle_classes = [LoginAnonThrottle]

        def list(self, request):
            return Response([{"id": 1}])

        def create(self, request):
            return Response({"id": 2}, status=status.HTTP_201_CREATED)

    # --- URLconf (this module IS the ROOT_URLCONF for these tests) ---------

    urlpatterns = [
        path("login/", LoginView.as_view()),
        path("profile/", ProfileView.as_view()),
        path("tier/", CallableRateView.as_view()),
        path("search/", SearchView.as_view()),
        path("reports/", ReportsView.as_view()),
        path("exports/", ExportsView.as_view()),
        path("deny/", DenyListView.as_view()),
        path("allow/", AllowListView.as_view()),
        path("shadow-deny/", ShadowDenyView.as_view()),
        path("shadow-rate/", ShadowRateView.as_view()),
        path(
            "items/",
            ItemViewSet.as_view({"get": "list", "post": "create"}),
        ),
    ]


# Route every request in this module through the views defined above.
pytestmark = [
    pytestmark,
    pytest.mark.urls(__name__),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _codes(client, path_, n, ip="203.0.113.10", **kw):
    """Hit ``path_`` n times from one IP; return the list of status codes."""
    out = []
    for _ in range(n):
        resp = client.get(path_, REMOTE_ADDR=ip, **kw)
        out.append(resp.status_code)
    return out


# ===========================================================================
# AnonRateLimitThrottle: per-IP login limiter
# ===========================================================================
def test_login_anon_per_ip_blocks_attacker_not_legit_user(real_backend):
    """Login endpoint (5/min per IP): an attacker hammering from one IP gets
    blocked after 5 attempts while a legitimate user on another IP is
    unaffected, on every real backend.
    """
    client = APIClient()
    attacker = "198.51.100.5"
    victim = "203.0.113.77"

    # 5 allowed, then 429 for the attacker.
    codes = [client.post("/login/", REMOTE_ADDR=attacker).status_code for _ in range(6)]
    assert codes == [200, 200, 200, 200, 200, 429], codes

    # A legitimate user on a different IP has a completely independent bucket.
    assert client.post("/login/", REMOTE_ADDR=victim).status_code == 200


def test_login_429_sets_retry_after(real_backend):
    """When the per-IP login limit is exceeded the 429 carries a positive
    integer ``Retry-After`` header derived from the throttle's wait().
    """
    client = APIClient()
    ip = "198.51.100.40"
    for _ in range(5):
        assert client.post("/login/", REMOTE_ADDR=ip).status_code == 200

    blocked = client.post("/login/", REMOTE_ADDR=ip)
    assert blocked.status_code == 429
    retry_after = blocked.headers.get("Retry-After")
    assert retry_after is not None, blocked.headers
    # 5/m window -> wait should be > 0 and at most the 60s period.
    assert 0 < int(retry_after) <= 60


# ===========================================================================
# UserRateLimitThrottle: per-user buckets, authed vs anon tiers
# ===========================================================================
def test_user_throttle_independent_buckets_per_user(real_backend):
    """Two authenticated users each get their own 10/min bucket: exhausting
    user A's budget never affects user B.
    """
    client = APIClient()
    user_a = AuthedUser(uid=4001)
    user_b = AuthedUser(uid=4002)

    client.force_authenticate(user=user_a)
    codes_a = [client.get("/profile/").status_code for _ in range(11)]
    assert codes_a == [200] * 10 + [429], codes_a

    # User B, sharing the same client IP, is untouched -> keyed by user id.
    client.force_authenticate(user=user_b)
    assert client.get("/profile/").status_code == 200


def test_user_throttle_authed_tier_higher_than_anon(real_backend):
    """A public API where authed users get a higher tier than anon: the anon
    LoginView caps at 5/min per IP, while an authed user on ProfileView gets
    10/min — demonstrating the higher authed tier on a real backend.
    """
    client = APIClient()
    ip = "203.0.113.120"

    # Anonymous tier on the login endpoint: 5 then blocked.
    anon_codes = [client.post("/login/", REMOTE_ADDR=ip).status_code for _ in range(6)]
    assert anon_codes == [200] * 5 + [429], anon_codes

    # Authed tier on the profile endpoint: 10 allowed (independent bucket).
    client.force_authenticate(user=AuthedUser(uid=4100))
    authed_codes = [
        client.get("/profile/", REMOTE_ADDR=ip).status_code for _ in range(10)
    ]
    assert authed_codes == [200] * 10, authed_codes
    assert client.get("/profile/", REMOTE_ADDR=ip).status_code == 429


# ===========================================================================
# SmartRateLimitThrottle: callable rate
# ===========================================================================
def test_callable_rate_staff_get_higher_tier(real_backend):
    """A callable ``rate`` resolves the tier from the request: a staff user
    sails past the 3/min mortal limit because staff resolve to 100/min.
    """
    client = APIClient()

    # Non-staff authed user -> 3/m.
    mortal = AuthedUser(uid=5001)
    client.force_authenticate(user=mortal)
    mortal_codes = [client.get("/tier/").status_code for _ in range(4)]
    assert mortal_codes == [200, 200, 200, 429], mortal_codes

    # Staff user (distinct id => distinct bucket) -> 100/m, never blocked here.
    staff = AuthedUser(uid=5002)
    staff.is_staff = True
    client.force_authenticate(user=staff)
    staff_codes = [client.get("/tier/").status_code for _ in range(20)]
    assert staff_codes == [200] * 20, staff_codes


# ===========================================================================
# SmartRateLimitThrottle: get_cost (weighted throttling)
# ===========================================================================
def test_get_cost_weighted_throttling(real_backend):
    """Weighted throttling via ``get_cost``: with a 10-token/min budget, a
    'deep' search spends 5 tokens. Two deep searches drain the budget and the
    third is blocked — proving cost is honored against the real store.
    """
    client = APIClient()
    ip = "203.0.113.200"

    # Two deep searches (cost 5 each) = 10 tokens -> both allowed.
    assert client.get("/search/", {"deep": "1"}, REMOTE_ADDR=ip).status_code == 200
    assert client.get("/search/", {"deep": "1"}, REMOTE_ADDR=ip).status_code == 200
    # Third deep search would push to 15 tokens -> blocked.
    assert client.get("/search/", {"deep": "1"}, REMOTE_ADDR=ip).status_code == 429


def test_get_cost_cheap_requests_within_budget(real_backend):
    """The same 10-token budget allows up to 10 cheap (cost-1) requests; the
    11th is blocked.
    """
    client = APIClient()
    ip = "203.0.113.201"
    codes = _codes(client, "/search/", 11, ip=ip)
    assert codes == [200] * 10 + [429], codes


# ===========================================================================
# ScopedRateLimitThrottle: rate from view.throttle_scope
# ===========================================================================
@override_settings(
    REST_FRAMEWORK={"DEFAULT_THROTTLE_RATES": {"reports": "4/m", "exports": "2/m"}}
)
def test_scoped_throttle_uses_view_scope(real_backend):
    """Each scoped view resolves its own rate from DEFAULT_THROTTLE_RATES via
    ``view.throttle_scope``: /reports/ enforces 4/min and /exports/ enforces
    2/min. The scope selects the *rate*; the cache key is the client IP, so
    distinct IPs are used to keep the two scopes from sharing a per-IP bucket.
    """
    client = APIClient()
    reports_ip = "203.0.113.210"
    exports_ip = "203.0.113.211"

    reports = _codes(client, "/reports/", 5, ip=reports_ip)
    assert reports == [200, 200, 200, 200, 429], reports

    # The 'exports' scope resolves a smaller (2/m) limit.
    exports = _codes(client, "/exports/", 3, ip=exports_ip)
    assert exports == [200, 200, 429], exports


@override_settings(
    REST_FRAMEWORK={"DEFAULT_THROTTLE_RATES": {"reports": "4/m", "exports": "2/m"}}
)
def test_scoped_throttle_buckets_independent_per_ip(real_backend):
    """Distinct IPs hitting the same scoped endpoint keep independent buckets."""
    client = APIClient()
    a, b = "203.0.113.220", "203.0.113.221"

    assert _codes(client, "/exports/", 3, ip=a) == [200, 200, 429]
    # Second IP is unaffected by the first IP exhausting its bucket.
    assert _codes(client, "/exports/", 2, ip=b) == [200, 200]


# ===========================================================================
# v4 parity: deny_list / allow_list / shadow as throttle attributes
# ===========================================================================
def test_deny_list_blocks_client(real_backend):
    """A deny-listed client (CIDR 198.51.100.0/24) is blocked on the very first
    request — before any counting — while an off-list client is served.
    """
    client = APIClient()

    # Deny-listed IP: blocked immediately (429), even though the rate is 100/m.
    assert client.get("/deny/", REMOTE_ADDR="198.51.100.9").status_code == 429
    # An IP outside the deny CIDR is allowed.
    assert client.get("/deny/", REMOTE_ADDR="203.0.113.9").status_code == 200


def test_allow_list_bypasses_throttle(real_backend):
    """An allow-listed internal client (10.0.0.0/8) bypasses throttling
    entirely: it stays 200 well past the 2/min limit that blocks others.
    """
    client = APIClient()

    internal = "10.1.2.3"
    external = "203.0.113.30"

    # Allow-listed: 200 for many requests despite the 2/m cap.
    assert _codes(client, "/allow/", 8, ip=internal) == [200] * 8

    # A normal external client is still throttled at 2/m on the same view.
    assert _codes(client, "/allow/", 3, ip=external) == [200, 200, 429]


def test_shadow_deny_allows_but_logs(real_backend, caplog):
    """A deny-list run in SHADOW mode logs the would-be block but still serves
    the request (200) — the rollout-validation path.
    """
    client = APIClient()
    with caplog.at_level(logging.INFO, logger="django_smart_ratelimit.pipeline"):
        resp = client.get("/shadow-deny/", REMOTE_ADDR="198.51.100.50")

    assert resp.status_code == 200
    assert any("SHADOW" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_shadow_rate_allows_over_limit_but_logs(real_backend, caplog):
    """A new 2/min limit deployed in SHADOW mode never returns 429: requests
    past the limit are served (200) but each over-limit hit emits a SHADOW log
    line so operators can size the limit before enforcing it.
    """
    client = APIClient()
    ip = "203.0.113.40"
    with caplog.at_level(logging.INFO, logger="django_smart_ratelimit.pipeline"):
        codes = _codes(client, "/shadow-rate/", 5, ip=ip)

    # Shadow never blocks.
    assert codes == [200] * 5, codes
    # At least one over-limit request (#3..#5) produced a SHADOW log line.
    assert any("SHADOW" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


# ===========================================================================
# Real ViewSet routed through APIClient
# ===========================================================================
def test_viewset_actions_share_per_ip_bucket(real_backend):
    """A real ViewSet throttled per-IP at 5/min: list() and create() actions
    draw from the same per-IP bucket, so mixing them still blocks after 5.
    """
    client = APIClient()
    ip = "203.0.113.50"

    # 3 lists + 2 creates = 5 allowed, then the 6th (a list) is blocked.
    assert client.get("/items/", REMOTE_ADDR=ip).status_code == 200
    assert client.get("/items/", REMOTE_ADDR=ip).status_code == 200
    assert client.post("/items/", REMOTE_ADDR=ip).status_code == 201
    assert client.post("/items/", REMOTE_ADDR=ip).status_code == 201
    assert client.get("/items/", REMOTE_ADDR=ip).status_code == 200
    # Budget (5) now spent.
    assert client.get("/items/", REMOTE_ADDR=ip).status_code == 429


def test_viewset_independent_bucket_per_ip(real_backend):
    """Distinct IPs against the ViewSet keep independent per-IP buckets."""
    client = APIClient()
    a, b = "203.0.113.60", "203.0.113.61"

    for _ in range(5):
        assert client.get("/items/", REMOTE_ADDR=a).status_code == 200
    assert client.get("/items/", REMOTE_ADDR=a).status_code == 429

    # Second IP unaffected.
    assert client.get("/items/", REMOTE_ADDR=b).status_code == 200
