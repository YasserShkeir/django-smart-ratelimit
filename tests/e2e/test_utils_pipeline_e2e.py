"""Real-backend end-to-end scenarios for public utilities, the shared
evaluation pipeline primitives, and the type-safe enums.

This file covers the "plumbing" that advanced users compose directly rather
than through the decorator:

    * :func:`is_ratelimited` — the programmatic check used inside custom views;
      its count must reflect real increments on the live backend.
    * :func:`generate_key` — the single dispatch point for every built-in key
      pattern (``ip``/``user``/``user_or_ip``/``header:``/``get:``/``param:`` and
      callables); the bucketing contract everything else relies on.
    * :func:`parse_rate` / :func:`validate_rate_config` — rate-string parsing and
      config validation, valid inputs and the errors raised on bad ones.
    * :class:`RateLimitConfigManager` — named-config register/retrieve, then
      *applying* a retrieved config to a real decorated view.
    * The header/debug helpers (:func:`add_rate_limit_headers`,
      :func:`add_token_bucket_headers`, :func:`format_rate_headers`,
      :func:`debug_ratelimit_status`, :func:`format_debug_info`) producing the
      exact ``X-RateLimit-*`` output operators see.
    * :func:`load_function_from_string` round-tripping a dotted path.
    * The v3 pipeline primitives :func:`resolve_effective_rate`,
      :func:`apply_policy_lists` and :func:`handle_shadow_decision` exercised
      with real :class:`IPList` inputs and a real backend.
    * The :class:`Algorithm` and :class:`RateLimitKey` enums: full membership and
      that each value works in a real decorator call.

Each scenario is self-contained: the ``real_backend`` fixture flushes the real
store before/after, and every test uses DISTINCT IPs / keys so tests never leak
into one another.
"""

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse

from django_smart_ratelimit import (
    POLICY_ALLOW,
    POLICY_CONTINUE,
    POLICY_DENY,
    RateLimitConfigManager,
    ResolvedLimit,
    ShadowDecision,
    add_rate_limit_headers,
    add_token_bucket_headers,
    apply_policy_lists,
    debug_ratelimit_status,
    format_debug_info,
    format_rate_headers,
    generate_key,
    handle_shadow_decision,
    is_ratelimited,
    load_function_from_string,
    parse_rate,
    rate_limit,
    resolve_effective_rate,
    validate_rate_config,
)
from django_smart_ratelimit.enums import Algorithm, RateLimitKey
from django_smart_ratelimit.exceptions import KeyGenerationError
from django_smart_ratelimit.policy import IPList

from .conftest import AnonUser, AuthedUser, make_request

OK = 200
TOO_MANY = 429


def _ok_view(_request):
    """A trivial 200 view body to wrap with the rate-limit decorator."""
    return HttpResponse("ok")


def _codes(view, requests):
    """Drive a view across a sequence of pre-built requests; return codes."""
    return [view(req).status_code for req in requests]


# ===========================================================================
# is_ratelimited — programmatic check against the real backend
# ===========================================================================


def test_is_ratelimited_reflects_real_increments(real_backend):
    """A custom view using ``is_ratelimited`` to gate access: keyed by IP at
    3/min, the same client is reported limited only after the real backend
    counter passes the limit, and a different IP is never limited.
    """
    ip = "198.51.100.10"
    req = make_request(ip=ip)

    # 3 allowed (count 1,2,3 are all <= 3), the 4th increment (count 4 > 3) trips.
    results = [is_ratelimited(req, key="ip", rate="3/m") for _ in range(4)]
    assert results == [False, False, False, True]

    # A different IP has its own real bucket and is unaffected.
    other = make_request(ip="198.51.100.11")
    assert is_ratelimited(other, key="ip", rate="3/m") is False


def test_is_ratelimited_increment_false_only_reads(real_backend):
    """``increment=False`` is a non-consuming probe: it reports the live count
    without advancing it, so a peek never pushes the caller over the limit.
    """
    ip = "198.51.100.20"
    req = make_request(ip=ip)

    # Peeking many times never increments -> never limited (count stays 0).
    for _ in range(5):
        assert is_ratelimited(req, key="ip", rate="2/m", increment=False) is False

    # Now actually consume the quota: 2 allowed, 3rd trips.
    assert is_ratelimited(req, key="ip", rate="2/m") is False
    assert is_ratelimited(req, key="ip", rate="2/m") is False
    assert is_ratelimited(req, key="ip", rate="2/m") is True

    # A read-only probe now observes the over-limit state without changing it.
    assert is_ratelimited(req, key="ip", rate="2/m", increment=False) is True


def test_is_ratelimited_group_namespaces_buckets(real_backend):
    """A ``group`` prefix gives the same client independent buckets per
    business action (e.g. "login" vs "signup"), so exhausting one group's
    quota does not limit the other.
    """
    req = make_request(ip="198.51.100.30")

    # Exhaust the "login" group (1/min).
    assert is_ratelimited(req, group="login", key="ip", rate="1/m") is False
    assert is_ratelimited(req, group="login", key="ip", rate="1/m") is True

    # The "signup" group for the same IP is a separate bucket -> still allowed.
    assert is_ratelimited(req, group="signup", key="ip", rate="1/m") is False


def test_is_ratelimited_user_key_independent_per_user(real_backend):
    """``is_ratelimited`` keyed by "user": two authenticated users have
    separate real buckets; exhausting user A never limits user B.
    """
    a = make_request(ip="198.51.100.40", user=AuthedUser(uid=7001))
    b = make_request(ip="198.51.100.40", user=AuthedUser(uid=7002))

    assert is_ratelimited(a, key="user", rate="1/m") is False
    assert is_ratelimited(a, key="user", rate="1/m") is True

    # Different user id -> own bucket, unaffected.
    assert is_ratelimited(b, key="user", rate="1/m") is False


# ===========================================================================
# generate_key — every built-in pattern
# ===========================================================================


def test_generate_key_ip_and_user_patterns():
    """``generate_key`` resolves the core identity patterns to stable strings."""
    anon = make_request(ip="192.0.2.20", user=AnonUser())
    assert generate_key("ip", anon) == "ip:192.0.2.20"
    # Anonymous user / user_or_ip fall back to the IP key.
    assert generate_key("user", anon) == "ip:192.0.2.20"
    assert generate_key("user_or_ip", anon) == "ip:192.0.2.20"

    authed = make_request(ip="192.0.2.21", user=AuthedUser(uid=55))
    assert generate_key("user", authed) == "user:55"
    assert generate_key("user_or_ip", authed) == "user:55"
    # "ip:" prefixed templates always key on the IP.
    assert generate_key("ip:whatever", authed) == "ip:192.0.2.21"
    # "user:" template for an authenticated user resolves to the user id.
    assert generate_key("user:{id}", authed) == "user:55"


def test_generate_key_header_and_param_patterns():
    """``generate_key`` resolves ``header:``, ``get:`` and the ``param:`` alias
    by embedding the request's header/query value into the key.
    """
    req = make_request(
        ip="192.0.2.22",
        headers={"X-Api-Key": "abc123"},
        params={"tenant": "acme"},
    )
    assert generate_key("header:X-Api-Key", req) == "header:X-Api-Key:abc123"
    assert generate_key("get:tenant", req) == "get:tenant:acme"
    # "param:" is an alias of "get:" so RateLimitKey.PARAM composes correctly.
    assert generate_key("param:tenant", req) == "param:tenant:acme"

    # A missing header/param yields a stable empty-value key (all such callers
    # share one bucket, which is the documented behavior).
    bare = make_request(ip="192.0.2.23")
    assert generate_key("header:X-Api-Key", bare) == "header:X-Api-Key:"
    assert generate_key("get:tenant", bare) == "get:tenant:"


def test_generate_key_callable_and_passthrough():
    """A callable key is invoked with the request (and forwarded args); an
    unknown literal string is returned verbatim as a static bucket.
    """
    req = make_request(ip="192.0.2.24")

    def custom(request, *args, **kwargs):
        return f"custom:{request.META['REMOTE_ADDR']}"

    assert generate_key(custom, req) == "custom:192.0.2.24"
    # An arbitrary literal is used as-is (a single shared global bucket).
    assert generate_key("global-bucket", req) == "global-bucket"


def test_generate_key_invalid_type_raises():
    """A non-str / non-callable key is a configuration error."""
    req = make_request()
    with pytest.raises(ImproperlyConfigured):
        generate_key(12345, req)


def test_generate_key_drives_real_bucketing(real_backend):
    """End-to-end: feeding ``generate_key`` output straight into the backend
    enforces the limit. Two distinct generated keys are independent buckets;
    the same key accumulates on the live store.
    """
    from django_smart_ratelimit.backends import get_backend

    backend = get_backend()
    limit, period = parse_rate("2/m")

    req_a = make_request(ip="198.51.100.50", headers={"X-Api-Key": "tenant-A"})
    req_b = make_request(ip="198.51.100.50", headers={"X-Api-Key": "tenant-B"})
    key_a = generate_key("header:X-Api-Key", req_a)
    key_b = generate_key("header:X-Api-Key", req_b)
    assert key_a != key_b

    # key_a: 2 allowed, 3rd over limit.
    assert [backend.incr(key_a, period) <= limit for _ in range(3)] == [
        True,
        True,
        False,
    ]
    # key_b is its own bucket — still under limit.
    assert backend.incr(key_b, period) <= limit


# ===========================================================================
# parse_rate / validate_rate_config — valid + raising
# ===========================================================================


@pytest.mark.parametrize(
    "rate,expected",
    [
        ("10/s", (10, 1)),
        ("5/m", (5, 60)),
        ("100/h", (100, 3600)),
        ("1000/d", (1000, 86400)),
        # Long-form aliases (DRF / API-gateway compatibility).
        ("7/sec", (7, 1)),
        ("7/second", (7, 1)),
        ("9/min", (9, 60)),
        ("9/minute", (9, 60)),
        ("3/hr", (3, 3600)),
        ("3/hour", (3, 3600)),
        ("2/day", (2, 86400)),
        # Custom multiplier windows.
        ("10/30s", (10, 30)),
        ("100/5m", (100, 300)),
        ("500/2h", (500, 7200)),
        ("10000/7d", (10000, 604800)),
    ],
)
def test_parse_rate_valid_formats(rate, expected):
    """``parse_rate`` handles simple, long-form, and custom-window rates."""
    assert parse_rate(rate) == expected


@pytest.mark.parametrize(
    "bad_rate",
    [
        "abc",  # no slash
        "10/x",  # unknown unit
        "10/0s",  # non-positive multiplier
        "ten/m",  # non-integer limit
        "5//m",  # malformed
        "100/",  # empty period
    ],
)
def test_parse_rate_invalid_raises(bad_rate):
    """Invalid rate strings raise ImproperlyConfigured rather than misparse."""
    with pytest.raises(ImproperlyConfigured):
        parse_rate(bad_rate)


def test_validate_rate_config_accepts_valid():
    """``validate_rate_config`` is silent for a valid rate + algorithm + token
    bucket config (the happy path for startup validation).
    """
    # No exception == valid.
    validate_rate_config("100/h")
    validate_rate_config("10/m", algorithm="sliding_window")
    validate_rate_config(
        "10/m",
        algorithm="token_bucket",
        algorithm_config={"bucket_size": 20, "refill_rate": 2.5},
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rate": "not-a-rate"},  # bad rate
        {"rate": "10/m", "algorithm": "made_up"},  # bad algorithm
        {
            "rate": "10/m",
            "algorithm": "token_bucket",
            "algorithm_config": {"bucket_size": -1},
        },  # negative bucket_size
        {
            "rate": "10/m",
            "algorithm": "token_bucket",
            "algorithm_config": {"refill_rate": -0.5},
        },  # negative refill_rate
    ],
)
def test_validate_rate_config_invalid_raises(kwargs):
    """``validate_rate_config`` raises ImproperlyConfigured on bad rate,
    unknown algorithm, or invalid token-bucket parameters.
    """
    with pytest.raises(ImproperlyConfigured):
        validate_rate_config(**kwargs)


def test_parsed_rate_enforced_on_real_backend(real_backend):
    """End-to-end: a ``parse_rate``-derived (limit, period) enforces exactly N
    allowed requests against the live store.
    """
    from django_smart_ratelimit.backends import get_backend

    limit, period = parse_rate("3/m")
    assert (limit, period) == (3, 60)

    backend = get_backend()
    key = "ip:198.51.100.60"
    over = [backend.incr(key, period) > limit for _ in range(4)]
    assert over == [False, False, False, True]


# ===========================================================================
# RateLimitConfigManager — register + retrieve + apply
# ===========================================================================


def test_config_manager_has_builtin_defaults():
    """The manager ships with sensible named defaults (e.g. "authentication"
    at 5/min keyed by ip).
    """
    mgr = RateLimitConfigManager()
    auth = mgr.get_config("authentication")
    assert auth["rate"] == "5/m"
    assert auth["key"] == "ip"
    assert auth["algorithm"] == "fixed_window"


def test_config_manager_register_retrieve_and_override():
    """A custom named config can be registered, retrieved, and retrieved again
    with per-call overrides applied on top.
    """
    mgr = RateLimitConfigManager()
    mgr.register_config(
        "partner_api",
        {"rate": "100/h", "key": "user", "algorithm": "sliding_window"},
    )

    cfg = mgr.get_config("partner_api")
    assert cfg["rate"] == "100/h"
    assert cfg["key"] == "user"

    # Overrides are layered on retrieval.
    overridden = mgr.get_config("partner_api", rate="200/h")
    assert overridden["rate"] == "200/h"


def test_config_manager_rejects_invalid_config():
    """Registering a config with a bad rate is rejected at registration time."""
    mgr = RateLimitConfigManager()
    with pytest.raises(ImproperlyConfigured):
        mgr.register_config("broken", {"rate": "nonsense"})
    # A config missing the required 'rate' field is also rejected.
    with pytest.raises(ImproperlyConfigured):
        mgr.register_config("missing_rate", {"key": "ip"})


def test_config_manager_applied_config_enforces_real_limit(real_backend):
    """Realistic flow: register a named "sms_send" config, retrieve it, and
    apply its rate+key to a real decorated view — the live backend enforces it.
    """
    mgr = RateLimitConfigManager()
    mgr.register_config(
        "sms_send", {"rate": "2/m", "key": "ip", "algorithm": "fixed_window"}
    )
    cfg = mgr.get_config("sms_send")

    @rate_limit(key=cfg["key"], rate=cfg["rate"])
    def send_sms(_request):
        return _ok_view(_request)

    codes = _codes(send_sms, [make_request(ip="198.51.100.70") for _ in range(3)])
    assert codes == [OK, OK, TOO_MANY]


# ===========================================================================
# Header / debug helpers — exact output operators rely on
# ===========================================================================


def test_format_rate_headers_basic_and_token_bucket():
    """``format_rate_headers`` maps backend metadata to the standard
    ``X-RateLimit-*`` header dict, including token-bucket extras when present.
    """
    basic = format_rate_headers({"remaining": 7, "reset_time": 1700000000}, 10, 60)
    assert basic["X-RateLimit-Limit"] == "10"
    assert basic["X-RateLimit-Remaining"] == "7"
    assert basic["X-RateLimit-Reset"] == "1700000000"

    # Negative remaining is clamped to 0.
    clamped = format_rate_headers({"remaining": -3}, 5, 60)
    assert clamped["X-RateLimit-Remaining"] == "0"

    bucket = format_rate_headers(
        {
            "remaining": 0,
            "bucket_size": 20,
            "tokens_remaining": 4,
            "refill_rate": 2.5,
        },
        20,
        60,
    )
    assert bucket["X-RateLimit-Bucket-Size"] == "20"
    assert bucket["X-RateLimit-Bucket-Remaining"] == "4"
    assert bucket["X-RateLimit-Refill-Rate"] == "2.50"


def test_add_rate_limit_headers_sets_standard_and_retry_after():
    """``add_rate_limit_headers`` writes Limit/Remaining/Reset onto a response;
    a 429 with no remaining also gets a Retry-After header.
    """
    ok = HttpResponse("ok")
    add_rate_limit_headers(ok, limit=10, remaining=4, period=60)
    assert ok.headers["X-RateLimit-Limit"] == "10"
    assert ok.headers["X-RateLimit-Remaining"] == "4"
    assert "X-RateLimit-Reset" in ok.headers
    # Not rate limited -> no Retry-After.
    assert "Retry-After" not in ok.headers

    blocked = HttpResponse("blocked", status=429)
    add_rate_limit_headers(blocked, limit=10, remaining=0, period=30)
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert blocked.headers["Retry-After"] == "30"


def test_add_token_bucket_headers_emits_bucket_fields():
    """``add_token_bucket_headers`` writes the bucket-specific headers and a
    stable, period-aligned reset time.
    """
    resp = HttpResponse("ok")
    metadata = {
        "tokens_remaining": 6,
        "bucket_size": 20,
        "refill_rate": 2.0,
    }
    add_token_bucket_headers(resp, metadata, limit=20, period=60)
    assert resp.headers["X-RateLimit-Limit"] == "20"
    assert resp.headers["X-RateLimit-Remaining"] == "6"
    assert resp.headers["X-RateLimit-Bucket-Size"] == "20"
    assert resp.headers["X-RateLimit-Bucket-Remaining"] == "6"
    assert resp.headers["X-RateLimit-Refill-Rate"] == "2.00"
    # Reset time is a positive integer string.
    assert int(resp.headers["X-RateLimit-Reset"]) > 0


def test_add_token_bucket_headers_retry_after_when_empty():
    """A 429 token-bucket response with no tokens left also gets Retry-After."""
    resp = HttpResponse("blocked", status=429)
    add_token_bucket_headers(
        resp,
        {"tokens_remaining": 0, "bucket_size": 5, "refill_rate": 1.0},
        limit=5,
        period=60,
    )
    assert resp.headers["X-RateLimit-Bucket-Remaining"] == "0"
    assert int(resp.headers["Retry-After"]) >= 0


def test_debug_ratelimit_status_reads_real_backend(real_backend):
    """``debug_ratelimit_status`` reports request context plus live backend
    counts. After hammering an IP-keyed view, the IP key's real count shows up
    in the debug snapshot, and ``format_debug_info`` renders it readably.
    """

    @rate_limit(key="ip", rate="5/m")
    def view(_request):
        return _ok_view(_request)

    ip = "198.51.100.80"
    for _ in range(3):
        view(make_request(ip=ip))

    probe = make_request(ip=ip, user=AuthedUser(uid=8080))
    info = debug_ratelimit_status(probe)

    assert info["request_path"] == "/"
    assert info["request_method"] == "GET"
    assert info["remote_addr"] == ip
    assert info["user_authenticated"] is True
    assert info["user_id"] == 8080
    assert "backend_type" in info
    assert "backend_counts" in info
    # The IP key the view used should be present in the snapshot.
    assert info["backend_counts"]["ip"]["key"] == f"ip:{ip}"

    rendered = format_debug_info(info)
    assert "Rate Limiting Debug Information" in rendered
    assert f"Remote IP: {ip}" in rendered
    assert "User ID: 8080" in rendered


def test_format_debug_info_anonymous_request():
    """``format_debug_info`` renders an anonymous, un-middleware-processed
    snapshot without leaking a user id.
    """
    info = {
        "request_path": "/api/ping",
        "request_method": "POST",
        "user_authenticated": False,
        "user_id": None,
        "remote_addr": "192.0.2.99",
        "middleware_processed": False,
    }
    rendered = format_debug_info(info)
    assert "Path: /api/ping" in rendered
    assert "Method: POST" in rendered
    assert "User: Anonymous" in rendered
    assert "Processed: False" in rendered
    assert "User ID:" not in rendered


# ===========================================================================
# load_function_from_string — dotted-path round-trip
# ===========================================================================


def test_load_function_from_string_round_trips():
    """A dotted path round-trips to the live callable, which then behaves
    identically when invoked.
    """
    fn = load_function_from_string("django_smart_ratelimit.utils.parse_rate")
    assert fn is parse_rate
    assert fn("10/m") == (10, 60)

    # A public key function loaded the same way produces the expected key.
    get_ip = load_function_from_string(
        "django_smart_ratelimit.key_functions.get_ip_key"
    )
    assert get_ip(make_request(ip="192.0.2.30")) == "ip:192.0.2.30"


@pytest.mark.parametrize(
    "bad_path",
    [
        "django_smart_ratelimit.utils.does_not_exist",  # missing attribute
        "nonexistent_module_xyz.func",  # missing module
        "noseparator",  # no dot to split on
    ],
)
def test_load_function_from_string_invalid_raises(bad_path):
    """An unresolvable dotted path is surfaced as ImproperlyConfigured."""
    with pytest.raises(ImproperlyConfigured):
        load_function_from_string(bad_path)


# ===========================================================================
# Pipeline: resolve_effective_rate
# ===========================================================================


def test_resolve_effective_rate_returns_resolved_limit():
    """``resolve_effective_rate`` turns a (key, rate) config into a concrete
    :class:`ResolvedLimit` with parsed limit/period and the generated key.
    """
    req = make_request(ip="192.0.2.40")
    resolved = resolve_effective_rate(key="ip", rate="15/m", request=req)
    assert isinstance(resolved, ResolvedLimit)
    assert resolved.key == "ip:192.0.2.40"
    assert resolved.limit == 15
    assert resolved.period == 60
    assert resolved.cost == 1
    assert resolved.rate_string == "15/m"


def test_resolve_effective_rate_callable_rate_and_cost():
    """A callable rate and a callable cost are both resolved per-request; a
    cost below 1 is clamped to 1 so a request can never be free.
    """
    req = make_request(ip="192.0.2.41")

    resolved = resolve_effective_rate(
        key="ip",
        rate=lambda request: "7/h",
        request=req,
        cost=lambda request: 3,
    )
    assert resolved.limit == 7
    assert resolved.period == 3600
    assert resolved.cost == 3
    assert resolved.rate_string == "7/h"

    # cost <= 0 clamps to 1.
    clamped = resolve_effective_rate(
        key="ip", rate="5/m", request=req, cost=lambda request: 0
    )
    assert clamped.cost == 1


def test_resolve_effective_rate_empty_key_raises():
    """An empty generated key would collapse every request onto one shared
    bucket; v3 upgrades that footgun to a loud :class:`KeyGenerationError`.
    """
    req = make_request(ip="192.0.2.42")

    with pytest.raises(KeyGenerationError):
        resolve_effective_rate(key=lambda request: "", rate="5/m", request=req)

    # ...but validate_key=False keeps the old silent behavior for callers who
    # opt out explicitly.
    permissive = resolve_effective_rate(
        key=lambda request: "", rate="5/m", request=req, validate_key=False
    )
    assert permissive.key == ""


def test_resolve_effective_rate_feeds_real_backend(real_backend):
    """The resolved (key, limit, period) drives the live backend exactly: N
    increments under the limit, then over.
    """
    from django_smart_ratelimit.backends import get_backend

    req = make_request(ip="198.51.100.90")
    resolved = resolve_effective_rate(key="ip", rate="2/m", request=req)

    backend = get_backend()
    over = [
        backend.incr(resolved.key, resolved.period) > resolved.limit for _ in range(3)
    ]
    assert over == [False, False, True]


# ===========================================================================
# Pipeline: apply_policy_lists with real IPList inputs
# ===========================================================================


def test_apply_policy_lists_continue_when_no_lists():
    """With neither list configured, the pipeline says CONTINUE (apply normal
    rate limiting).
    """
    req = make_request(ip="203.0.113.10")
    assert apply_policy_lists(req) == POLICY_CONTINUE


def test_apply_policy_lists_allow_for_listed_ip():
    """An IP inside a real allow-list IPList yields POLICY_ALLOW (bypass)."""
    req = make_request(ip="10.0.0.5")
    allow = IPList(["10.0.0.0/8"])
    assert apply_policy_lists(req, allow_list=allow) == POLICY_ALLOW

    # An IP outside the allow list just continues to normal limiting.
    outside = make_request(ip="203.0.113.11")
    assert apply_policy_lists(outside, allow_list=allow) == POLICY_CONTINUE


def test_apply_policy_lists_deny_takes_precedence():
    """An IP in the deny-list yields POLICY_DENY, and deny wins even when the
    same IP also matches the allow-list (fail-closed for explicit blocks).
    """
    req = make_request(ip="192.168.1.50")
    deny = IPList(["192.168.1.0/24"])
    assert apply_policy_lists(req, deny_list=deny) == POLICY_DENY

    # Same IP in both lists -> deny precedence.
    allow = IPList(["192.168.1.0/24"])
    assert apply_policy_lists(req, allow_list=allow, deny_list=deny) == POLICY_DENY


def test_apply_policy_lists_accepts_cidr_string_and_list_inputs():
    """``apply_policy_lists`` accepts raw CIDR strings / lists (not just IPList
    objects) since it routes through ``parse_ip_list``.
    """
    req = make_request(ip="198.51.100.5")
    # Single-CIDR string form.
    assert apply_policy_lists(req, deny_list="198.51.100.0/24") == POLICY_DENY
    # List-of-CIDR form on the allow side.
    assert apply_policy_lists(req, allow_list=["198.51.100.5"]) == POLICY_ALLOW


def test_policy_constants_are_distinct():
    """The three policy outcomes are distinct sentinel strings."""
    assert {POLICY_ALLOW, POLICY_DENY, POLICY_CONTINUE} == {
        "allow",
        "deny",
        "continue",
    }


# ===========================================================================
# Pipeline: handle_shadow_decision
# ===========================================================================


def test_handle_shadow_decision_passes_allowed_through():
    """An allowed decision is returned unchanged and not shadowed."""
    req = make_request(ip="203.0.113.20")
    decision = handle_shadow_decision(
        allowed=True,
        shadow=False,
        request=req,
        key="ip:203.0.113.20",
        limit=10,
        remaining=5,
        algorithm="sliding_window",
        backend="MemoryBackend",
    )
    assert isinstance(decision, ShadowDecision)
    assert decision.allow is True
    assert decision.shadowed is False


def test_handle_shadow_decision_enforces_block_without_shadow():
    """Without shadow mode, a blocked decision stays blocked."""
    req = make_request(ip="203.0.113.21")
    decision = handle_shadow_decision(
        allowed=False,
        shadow=False,
        request=req,
        key="ip:203.0.113.21",
        limit=10,
        remaining=0,
        algorithm="sliding_window",
        backend="MemoryBackend",
    )
    assert decision.allow is False
    assert decision.shadowed is False


def test_handle_shadow_decision_flips_block_under_shadow():
    """Shadow mode flips a would-be block into an allow (allow-with-log), the
    standard "run the new limit in shadow for a day" rollout strategy.
    """
    req = make_request(ip="203.0.113.22", path="/api/risky")
    decision = handle_shadow_decision(
        allowed=False,
        shadow=True,
        request=req,
        key="ip:203.0.113.22",
        limit=10,
        remaining=0,
        algorithm="sliding_window",
        backend="MemoryBackend",
    )
    assert decision.allow is True
    assert decision.shadowed is True
    assert decision.extra.get("shadow") is True


def test_shadow_decorator_allows_but_records_over_limit(real_backend):
    """End-to-end via the decorator: a ``shadow=True`` view at 2/min never
    returns 429 even far past the limit (it would have blocked, but shadow
    downgrades to allow-with-log), while an identical non-shadow view blocks.
    """

    @rate_limit(key="ip", rate="2/m", shadow=True)
    def shadow_view(_request):
        return _ok_view(_request)

    @rate_limit(key="ip", rate="2/m")
    def real_view(_request):
        return _ok_view(_request)

    # Shadow: distinct IP, hammered well past the limit -> all 200.
    shadow_codes = _codes(
        shadow_view, [make_request(ip="198.51.100.100") for _ in range(5)]
    )
    assert shadow_codes == [OK, OK, OK, OK, OK]

    # Enforcing: a different IP is actually blocked after 2.
    real_codes = _codes(
        real_view, [make_request(ip="198.51.100.101") for _ in range(4)]
    )
    assert real_codes == [OK, OK, TOO_MANY, TOO_MANY]


# ===========================================================================
# Enums: Algorithm and RateLimitKey membership + real decorator calls
# ===========================================================================


def test_algorithm_enum_full_membership():
    """``Algorithm`` exposes exactly the four supported algorithms, each a
    StrEnum equal to its lowercase string value.
    """
    assert {a.value for a in Algorithm} == {
        "sliding_window",
        "fixed_window",
        "token_bucket",
        "leaky_bucket",
    }
    # StrEnum: each member compares equal to and formats as its string value.
    assert Algorithm.SLIDING_WINDOW == "sliding_window"
    assert f"{Algorithm.TOKEN_BUCKET}" == "token_bucket"
    # Every value is accepted by config validation.
    for algo in Algorithm:
        validate_rate_config("10/m", algorithm=algo.value)


def test_ratelimit_key_enum_full_membership():
    """``RateLimitKey`` exposes the five built-in key types as StrEnum values."""
    assert {k.value for k in RateLimitKey} == {
        "ip",
        "user",
        "user_or_ip",
        "header",
        "param",
    }
    assert RateLimitKey.IP == "ip"
    assert RateLimitKey.USER_OR_IP == "user_or_ip"
    # HEADER / PARAM are prefixes that compose with a sub-value.
    assert f"{RateLimitKey.HEADER}:X-Api-Key" == "header:X-Api-Key"
    assert f"{RateLimitKey.PARAM}:tenant" == "param:tenant"


@pytest.mark.parametrize(
    "algorithm",
    [
        Algorithm.SLIDING_WINDOW,
        Algorithm.FIXED_WINDOW,
        Algorithm.TOKEN_BUCKET,
        Algorithm.LEAKY_BUCKET,
    ],
)
def test_every_algorithm_enum_value_works_in_decorator(real_backend, algorithm):
    """Each ``Algorithm`` enum value is accepted by the decorator and enforces a
    real limit on the live backend: a small allowance of 200s then a 429.

    Distinct IP per algorithm so the parametrized runs never collide.
    """

    @rate_limit(key="ip", rate="2/m", algorithm=algorithm)
    def view(_request):
        return _ok_view(_request)

    ip = f"198.51.100.1{list(Algorithm).index(algorithm)}"
    codes = _codes(view, [make_request(ip=ip) for _ in range(5)])
    # First two allowed; the limiter blocks once the allowance is consumed.
    assert codes[0] == OK
    assert codes[1] == OK
    assert TOO_MANY in codes[2:]


def test_ip_and_user_enum_keys_work_in_decorator(real_backend):
    """The complete ``RateLimitKey`` values (IP, USER, USER_OR_IP) work directly
    as the decorator ``key=`` and bucket on the live backend.
    """

    @rate_limit(key=RateLimitKey.IP, rate="2/m")
    def ip_view(_request):
        return _ok_view(_request)

    assert _codes(ip_view, [make_request(ip="198.51.100.120") for _ in range(3)]) == [
        OK,
        OK,
        TOO_MANY,
    ]

    @rate_limit(key=RateLimitKey.USER, rate="2/m")
    def user_view(_request):
        return _ok_view(_request)

    user = AuthedUser(uid=12121)
    assert _codes(
        user_view,
        [make_request(ip="198.51.100.121", user=user) for _ in range(3)],
    ) == [OK, OK, TOO_MANY]

    @rate_limit(key=RateLimitKey.USER_OR_IP, rate="2/m")
    def uoi_view(_request):
        return _ok_view(_request)

    assert _codes(uoi_view, [make_request(ip="198.51.100.122") for _ in range(3)]) == [
        OK,
        OK,
        TOO_MANY,
    ]


def test_header_and_param_enum_prefixes_work_in_decorator(real_backend):
    """The ``HEADER`` and ``PARAM`` enum prefixes, composed with a sub-value,
    work as decorator keys and bucket per header/param value on the live store.
    """
    header_key = f"{RateLimitKey.HEADER}:X-Api-Key"

    @rate_limit(key=header_key, rate="2/m")
    def header_view(_request):
        return _ok_view(_request)

    alpha = [
        make_request(ip="198.51.100.130", headers={"X-Api-Key": "alpha"})
        for _ in range(3)
    ]
    assert _codes(header_view, alpha) == [OK, OK, TOO_MANY]
    # A different header value is an independent bucket.
    bravo = [make_request(ip="198.51.100.130", headers={"X-Api-Key": "bravo"})]
    assert _codes(header_view, bravo) == [OK]

    param_key = f"{RateLimitKey.PARAM}:tenant"

    @rate_limit(key=param_key, rate="2/m")
    def param_view(_request):
        return _ok_view(_request)

    acme = [
        make_request(ip="198.51.100.131", params={"tenant": "acme"}) for _ in range(3)
    ]
    assert _codes(param_view, acme) == [OK, OK, TOO_MANY]
    globex = [make_request(ip="198.51.100.131", params={"tenant": "globex"})]
    assert _codes(param_view, globex) == [OK]
