"""Real-backend end-to-end scenarios for rate-limit KEY functions.

Every public key function (used either as the decorator ``key=`` or called
directly) is exercised against a REAL store via the shared harness. The
controlling assertion throughout is the bucketing contract:

    * DISTINCT key values get INDEPENDENT buckets (one identity being blocked
      never bleeds into another), and
    * the SAME key value SHARES one bucket (so a single identity is actually
      limited).

Each scenario uses its own DISTINCT IPs / users / headers so tests never depend
on one another, and the ``real_backend`` fixture flushes the real store before
and after each test. The proxy-trust and path/bypass helpers are validated as
real request scenarios via :func:`get_client_ip` and the public utility
functions.
"""

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import override_settings

from django_smart_ratelimit import (
    api_key_aware_key,
    composite_key,
    device_fingerprint_key,
    geographic_key,
    get_ip_key,
    get_rate_for_path,
    get_user_key,
    is_exempt_request,
    is_internal_request,
    rate_limit,
    should_skip_path,
    tenant_aware_key,
    time_aware_key,
    user_or_ip_key,
    user_role_key,
)
from django_smart_ratelimit.enums import RateLimitKey
from django_smart_ratelimit.policy import get_client_ip

from .conftest import AnonUser, AuthedUser, make_request

OK = 200
TOO_MANY = 429


def _ok_view(_request):
    """A trivial 200 view body to wrap with the rate-limit decorator."""
    return HttpResponse("ok")


def _codes(view, requests):
    """Drive a view across a sequence of pre-built requests; return codes."""
    return [view(req).status_code for req in requests]


def _key(fn, **opts):
    """Adapt a single-argument key function for use as a decorator ``key=``.

    The decorator calls a callable key as ``key(request, *view_args,
    **view_kwargs)``, so a bare ``fn(request)`` helper must be wrapped to
    ignore the forwarded view positional/keyword args. This is the realistic
    public pattern for using the library's key helpers (and lets us pass
    per-call options such as ``header_name`` / ``time_window``).
    """

    def _adapter(request, *args, **kwargs):
        return fn(request, **opts)

    return _adapter


# ---------------------------------------------------------------------------
# Built-in string / enum keys via the decorator
# ---------------------------------------------------------------------------


def test_ip_key_blocks_attacker_not_legit_user(real_backend):
    """Public login endpoint keyed by "ip" at 3/min.

    An attacker hammering from one IP is blocked after 3 requests while a
    legitimate user on a different IP is completely unaffected — proving each
    distinct IP gets an independent bucket on the real backend.
    """

    @rate_limit(key="ip", rate="3/m")
    def login(_request):
        return _ok_view(_request)

    attacker = [make_request(ip="198.51.100.7") for _ in range(5)]
    assert _codes(login, attacker) == [OK, OK, OK, TOO_MANY, TOO_MANY]

    # A legitimate user from a totally different IP is untouched.
    legit = [make_request(ip="198.51.100.200") for _ in range(3)]
    assert _codes(login, legit) == [OK, OK, OK]


def test_ip_enum_key_matches_string(real_backend):
    """``RateLimitKey.IP`` enum behaves identically to the literal "ip"."""

    @rate_limit(key=RateLimitKey.IP, rate="2/m")
    def view(_request):
        return _ok_view(_request)

    codes = _codes(view, [make_request(ip="198.51.100.21") for _ in range(4)])
    assert codes == [OK, OK, TOO_MANY, TOO_MANY]


def test_user_key_independent_per_user(real_backend):
    """API keyed by "user" at 2/min: two authenticated users have separate
    quotas; exhausting user A's bucket never blocks user B.
    """

    @rate_limit(key="user", rate="2/m")
    def view(_request):
        return _ok_view(_request)

    user_a = AuthedUser(uid=901)
    user_b = AuthedUser(uid=902)

    a = [make_request(ip="203.0.113.31", user=user_a) for _ in range(3)]
    assert _codes(view, a) == [OK, OK, TOO_MANY]

    b = [make_request(ip="203.0.113.31", user=user_b) for _ in range(2)]
    assert _codes(view, b) == [OK, OK]


def test_user_key_anonymous_falls_back_to_ip(real_backend):
    """Anonymous traffic on a "user"-keyed view falls back to the client IP,
    so two anonymous clients on different IPs are bucketed separately.
    """

    @rate_limit(key="user", rate="2/m")
    def view(_request):
        return _ok_view(_request)

    anon_one = [make_request(ip="203.0.113.41", user=AnonUser()) for _ in range(3)]
    assert _codes(view, anon_one) == [OK, OK, TOO_MANY]

    anon_two = [make_request(ip="203.0.113.42", user=AnonUser()) for _ in range(2)]
    assert _codes(view, anon_two) == [OK, OK]


def test_user_or_ip_key_authenticated_shares_bucket_across_ips(real_backend):
    """``RateLimitKey.USER_OR_IP``: an authenticated user roaming across two
    IPs shares ONE bucket (keyed on the user id), while anonymous users are
    keyed by IP. Regression guard for the v3 fix that stopped this collapsing
    onto a single global bucket.
    """

    @rate_limit(key=RateLimitKey.USER_OR_IP, rate="3/m")
    def view(_request):
        return _ok_view(_request)

    user = AuthedUser(uid=950)
    # Same user, two different IPs -> still one shared bucket of 3.
    roaming = [
        make_request(ip="203.0.113.51", user=user),
        make_request(ip="203.0.113.52", user=user),
        make_request(ip="203.0.113.51", user=user),
        make_request(ip="203.0.113.52", user=user),
    ]
    assert _codes(view, roaming) == [OK, OK, OK, TOO_MANY]

    # An anonymous client (keyed by its own IP) is unaffected.
    anon = [make_request(ip="203.0.113.60", user=AnonUser()) for _ in range(3)]
    assert _codes(view, anon) == [OK, OK, OK]


def test_user_or_ip_key_not_a_shared_global_bucket(real_backend):
    """Two distinct anonymous IPs on a ``user_or_ip`` view must NOT share a
    bucket (the literal must not fall through to a single global key).
    """

    @rate_limit(key="user_or_ip", rate="1/m")
    def view(_request):
        return _ok_view(_request)

    assert make_request(ip="203.0.113.71").path  # sanity: request builds
    first = [make_request(ip="203.0.113.71") for _ in range(2)]
    assert _codes(view, first) == [OK, TOO_MANY]
    # Different IP still gets its own first hit.
    assert _codes(view, [make_request(ip="203.0.113.72")]) == [OK]


# ---------------------------------------------------------------------------
# Header- and param-prefixed keys
# ---------------------------------------------------------------------------


def test_header_key_per_api_key(real_backend):
    """Partner API keyed by ``f"{RateLimitKey.HEADER}:X-Api-Key"`` at 2/min.

    Each distinct X-Api-Key header value gets its own bucket; a missing header
    collapses all header-less callers onto one (empty-value) bucket.
    """
    key = f"{RateLimitKey.HEADER}:X-Api-Key"

    @rate_limit(key=key, rate="2/m")
    def view(_request):
        return _ok_view(_request)

    # Same IP, two different API keys -> independent buckets.
    a = [
        make_request(ip="203.0.113.81", headers={"X-Api-Key": "alpha"})
        for _ in range(3)
    ]
    assert _codes(view, a) == [OK, OK, TOO_MANY]

    b = [
        make_request(ip="203.0.113.81", headers={"X-Api-Key": "bravo"})
        for _ in range(2)
    ]
    assert _codes(view, b) == [OK, OK]


def test_get_param_key_independent_per_value(real_backend):
    """A search endpoint keyed by ``get:tenant``: each ?tenant= value gets its
    own bucket; the same value shares one.
    """

    @rate_limit(key="get:tenant", rate="2/m")
    def view(_request):
        return _ok_view(_request)

    acme = [
        make_request(ip="203.0.113.91", params={"tenant": "acme"}) for _ in range(3)
    ]
    assert _codes(view, acme) == [OK, OK, TOO_MANY]

    globex = [
        make_request(ip="203.0.113.91", params={"tenant": "globex"}) for _ in range(2)
    ]
    assert _codes(view, globex) == [OK, OK]


def test_param_alias_key_matches_get(real_backend):
    """``f"{RateLimitKey.PARAM}:page"`` is an alias of ``get:`` and buckets per
    query-parameter value independently.
    """
    key = f"{RateLimitKey.PARAM}:page"

    @rate_limit(key=key, rate="1/m")
    def view(_request):
        return _ok_view(_request)

    p1 = [make_request(ip="203.0.113.101", params={"page": "1"}) for _ in range(2)]
    assert _codes(view, p1) == [OK, TOO_MANY]

    p2 = [make_request(ip="203.0.113.101", params={"page": "2"})]
    assert _codes(view, p2) == [OK]


# ---------------------------------------------------------------------------
# Key functions passed directly as the decorator callable
# ---------------------------------------------------------------------------


def test_geographic_key_per_country(real_backend):
    """``geographic_key`` (Cloudflare CF-IPCOUNTRY): same user from two
    countries gets two buckets; same country shares one.
    """

    @rate_limit(key=_key(geographic_key), rate="2/m")
    def view(_request):
        return _ok_view(_request)

    de = [
        make_request(ip="203.0.113.111", headers={"CF-IPCOUNTRY": "DE"})
        for _ in range(3)
    ]
    assert _codes(view, de) == [OK, OK, TOO_MANY]

    fr = [
        make_request(ip="203.0.113.111", headers={"CF-IPCOUNTRY": "FR"})
        for _ in range(2)
    ]
    assert _codes(view, fr) == [OK, OK]


def test_composite_key_prefers_user_over_ip(real_backend):
    """``composite_key`` (default ["user", "ip"]): an authenticated user is
    keyed by id regardless of IP, while anonymous callers fall back to IP.
    """

    @rate_limit(key=_key(composite_key), rate="2/m")
    def view(_request):
        return _ok_view(_request)

    user = AuthedUser(uid=1201)
    auth_reqs = [
        make_request(ip="203.0.113.121", user=user),
        make_request(ip="203.0.113.122", user=user),
        make_request(ip="203.0.113.121", user=user),
    ]
    assert _codes(view, auth_reqs) == [OK, OK, TOO_MANY]

    # Anonymous on a fresh IP gets its own bucket.
    anon = [make_request(ip="203.0.113.130", user=AnonUser()) for _ in range(2)]
    assert _codes(view, anon) == [OK, OK]


def test_api_key_aware_key_uses_key_then_falls_back(real_backend):
    """``api_key_aware_key``: keyed on X-API-Key when present, otherwise falls
    back to user/IP. Two API keys are independent; the fallback path buckets
    by IP.
    """

    @rate_limit(key=_key(api_key_aware_key), rate="2/m")
    def view(_request):
        return _ok_view(_request)

    k1 = [
        make_request(ip="203.0.113.141", headers={"X-API-Key": "key-1"})
        for _ in range(3)
    ]
    assert _codes(view, k1) == [OK, OK, TOO_MANY]

    k2 = [
        make_request(ip="203.0.113.141", headers={"X-API-Key": "key-2"})
        for _ in range(2)
    ]
    assert _codes(view, k2) == [OK, OK]

    # No API key -> falls back to IP; distinct IP is its own bucket.
    no_key = [make_request(ip="203.0.113.150") for _ in range(2)]
    assert _codes(view, no_key) == [OK, OK]


def test_time_aware_key_window_in_key(real_backend):
    """``time_aware_key`` embeds the time window in the key. Within a single
    window calls accumulate against the same bucket, so the limit is enforced
    normally for one identity.
    """

    @rate_limit(key=_key(time_aware_key, time_window="hour"), rate="2/m")
    def view(_request):
        return _ok_view(_request)

    same = [make_request(ip="203.0.113.161") for _ in range(3)]
    assert _codes(view, same) == [OK, OK, TOO_MANY]

    # A different IP within the same window is a separate bucket.
    other = [make_request(ip="203.0.113.162") for _ in range(2)]
    assert _codes(view, other) == [OK, OK]


def test_tenant_aware_key_per_tenant(real_backend):
    """``tenant_aware_key`` (get_tenant_key) buckets per tenant id read from a
    ?tenant_id= param: each tenant gets an independent quota.
    """

    @rate_limit(key=_key(tenant_aware_key), rate="2/m")
    def view(_request):
        return _ok_view(_request)

    t1 = [
        make_request(ip="203.0.113.171", params={"tenant_id": "t1"}) for _ in range(3)
    ]
    assert _codes(view, t1) == [OK, OK, TOO_MANY]

    t2 = [
        make_request(ip="203.0.113.171", params={"tenant_id": "t2"}) for _ in range(2)
    ]
    assert _codes(view, t2) == [OK, OK]


def test_device_fingerprint_key_per_device(real_backend):
    """``device_fingerprint_key`` hashes UA + Accept-* + DNT headers: two
    distinct browser fingerprints from the same IP get separate buckets, while
    identical headers share one.
    """

    @rate_limit(key=_key(device_fingerprint_key), rate="2/m")
    def view(_request):
        return _ok_view(_request)

    chrome_headers = {
        "User-Agent": "Mozilla/5.0 (Chrome)",
        "Accept-Language": "en-US",
        "Accept-Encoding": "gzip",
    }
    firefox_headers = {
        "User-Agent": "Mozilla/5.0 (Firefox)",
        "Accept-Language": "en-US",
        "Accept-Encoding": "gzip",
    }

    chrome = [
        make_request(ip="203.0.113.181", headers=chrome_headers) for _ in range(3)
    ]
    assert _codes(view, chrome) == [OK, OK, TOO_MANY]

    firefox = [
        make_request(ip="203.0.113.181", headers=firefox_headers) for _ in range(2)
    ]
    assert _codes(view, firefox) == [OK, OK]


def test_user_role_key_per_role(real_backend):
    """``user_role_key`` includes the user's role in the key, so a staff user
    and a regular user with the SAME id land in different buckets.
    """

    @rate_limit(key=_key(user_role_key), rate="2/m")
    def view(_request):
        return _ok_view(_request)

    regular = AuthedUser(uid=1900)
    staff = AuthedUser(uid=1900)
    staff.is_staff = True

    reg = [make_request(ip="203.0.113.191", user=regular) for _ in range(3)]
    assert _codes(view, reg) == [OK, OK, TOO_MANY]

    # Same id but staff role -> distinct bucket, unaffected by the above.
    stf = [make_request(ip="203.0.113.191", user=staff) for _ in range(2)]
    assert _codes(view, stf) == [OK, OK]


# ---------------------------------------------------------------------------
# Direct key-function output (the contract the buckets rely on)
# ---------------------------------------------------------------------------


def test_key_functions_produce_expected_strings():
    """Sanity-check the raw key strings each function emits — the bucketing
    behavior above depends on these being distinct/stable.
    """
    req = make_request(ip="192.0.2.5")
    assert get_ip_key(req) == "ip:192.0.2.5"

    anon = make_request(ip="192.0.2.6", user=AnonUser())
    assert get_user_key(anon) == "ip:192.0.2.6"
    assert user_or_ip_key(anon) == "ip:192.0.2.6"

    authed = make_request(ip="192.0.2.7", user=AuthedUser(uid=42))
    assert get_user_key(authed) == "user:42"
    assert user_or_ip_key(authed) == "user:42"

    geo = make_request(ip="192.0.2.8", headers={"CF-IPCOUNTRY": "JP"})
    assert geographic_key(geo) == "geo:JP:ip:192.0.2.8"

    api = make_request(ip="192.0.2.9", headers={"X-API-Key": "secret"})
    assert api_key_aware_key(api) == "api_key:secret"

    staff_user = AuthedUser(uid=7)
    staff_user.is_staff = True
    role_req = make_request(ip="192.0.2.10", user=staff_user)
    assert user_role_key(role_req) == "7:staff"

    composite_anon = make_request(ip="192.0.2.11", user=AnonUser())
    assert composite_key(composite_anon) == "ip:192.0.2.11"

    tenant_req = make_request(ip="192.0.2.12", params={"tenant_id": "acme"})
    assert tenant_aware_key(tenant_req).startswith("tenant:acme:")

    device = make_request(ip="192.0.2.13", headers={"User-Agent": "x"})
    assert device_fingerprint_key(device).startswith("device:")

    time_req = make_request(ip="192.0.2.14")
    assert time_aware_key(time_req, "day").startswith("time:day:")


# ---------------------------------------------------------------------------
# Trusted-proxy scenarios via policy.get_client_ip
# ---------------------------------------------------------------------------


def test_trusted_proxy_returns_real_client_from_xff_chain():
    """RATELIMIT_TRUSTED_PROXIES set: a request arriving from a trusted proxy
    yields the REAL client (right-most non-trusted entry of the XFF chain),
    not the proxy address.
    """
    with override_settings(RATELIMIT_TRUSTED_PROXIES=["10.0.0.0/8"]):
        req = make_request(
            ip="10.0.0.1",  # the trusted proxy (REMOTE_ADDR)
            headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.2"},
        )
        assert get_client_ip(req) == "203.0.113.5"


def test_trusted_proxy_resists_spoof_prepend():
    """A client cannot evade limits by PREPENDING a fake hop: walking the XFF
    chain from the right past trusted proxies still returns the real edge
    client, ignoring the spoofed left-most value.
    """
    with override_settings(RATELIMIT_TRUSTED_PROXIES=["10.0.0.0/8"]):
        req = make_request(
            ip="10.0.0.1",
            headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.9, 10.0.0.2"},
        )
        # 1.2.3.4 is the attacker-injected value; the genuine client added by
        # the trusted edge is 203.0.113.9.
        assert get_client_ip(req) == "203.0.113.9"


def test_direct_client_cannot_spoof_when_not_trusted():
    """A request that did NOT arrive via a trusted proxy cannot spoof its IP:
    forwarded headers are ignored and REMOTE_ADDR is used.
    """
    with override_settings(RATELIMIT_TRUSTED_PROXIES=["10.0.0.0/8"]):
        req = make_request(
            ip="198.51.100.77",  # NOT a trusted proxy
            headers={"X-Forwarded-For": "127.0.0.1"},  # spoof attempt
        )
        assert get_client_ip(req) == "198.51.100.77"


def test_trust_forwarded_headers_disabled_uses_remote_addr():
    """With RATELIMIT_TRUST_FORWARDED_HEADERS=False, forwarded headers are
    ignored entirely and REMOTE_ADDR is authoritative.
    """
    with override_settings(RATELIMIT_TRUST_FORWARDED_HEADERS=False):
        req = make_request(
            ip="198.51.100.88",
            headers={"X-Forwarded-For": "203.0.113.1", "X-Real-IP": "203.0.113.2"},
        )
        assert get_client_ip(req) == "198.51.100.88"


def test_default_legacy_trusts_first_forwarded_header():
    """Default (no trusted-proxy config, trust enabled): the left-most
    X-Forwarded-For entry is honored — the documented backward-compatible
    behavior.
    """
    with override_settings(
        RATELIMIT_TRUSTED_PROXIES=None, RATELIMIT_TRUST_FORWARDED_HEADERS=True
    ):
        req = make_request(
            ip="198.51.100.99",
            headers={"X-Forwarded-For": "203.0.113.44, 10.0.0.2"},
        )
        assert get_client_ip(req) == "203.0.113.44"


def test_invalid_trusted_proxy_config_fails_secure():
    """An invalid RATELIMIT_TRUSTED_PROXIES value must FAIL SECURE: the request
    stays in trusted-proxy mode and falls back to REMOTE_ADDR rather than
    reverting to trusting spoofable client headers.
    """
    # Clear any cached parse of a prior (valid) config under the same value.
    from django_smart_ratelimit.policy import lists as _lists

    _lists._TRUSTED_PROXY_CACHE.clear()
    with override_settings(RATELIMIT_TRUSTED_PROXIES=["not-a-cidr"]):
        req = make_request(
            ip="198.51.100.111",
            headers={"X-Forwarded-For": "127.0.0.1"},  # would-be spoof
        )
        # Misconfig -> REMOTE_ADDR, NOT the spoofed forwarded header.
        assert get_client_ip(req) == "198.51.100.111"


def test_trusted_proxy_bucketing_keys_on_real_client(real_backend):
    """End-to-end: with a trusted proxy, an "ip"-keyed view buckets on the REAL
    client behind the proxy. Two real clients sharing the same proxy
    REMOTE_ADDR get INDEPENDENT buckets; one real client spamming through the
    proxy is blocked.
    """
    with override_settings(RATELIMIT_TRUSTED_PROXIES=["10.0.0.0/8"]):

        @rate_limit(key="ip", rate="2/m")
        def view(_request):
            return _ok_view(_request)

        client_a = [
            make_request(
                ip="10.0.0.5", headers={"X-Forwarded-For": "203.0.113.201, 10.0.0.5"}
            )
            for _ in range(3)
        ]
        assert _codes(view, client_a) == [OK, OK, TOO_MANY]

        # Different real client, same proxy -> its own bucket.
        client_b = [
            make_request(
                ip="10.0.0.5", headers={"X-Forwarded-For": "203.0.113.202, 10.0.0.5"}
            )
            for _ in range(2)
        ]
        assert _codes(view, client_b) == [OK, OK]


# ---------------------------------------------------------------------------
# Bypass / path helpers: is_internal_request, is_exempt_request,
# should_skip_path, get_rate_for_path
# ---------------------------------------------------------------------------


def test_is_internal_request_defaults():
    """``is_internal_request`` recognizes RFC-1918 / loopback by default and
    rejects public addresses.
    """
    assert is_internal_request(make_request(ip="127.0.0.1")) is True
    assert is_internal_request(make_request(ip="10.1.2.3")) is True
    assert is_internal_request(make_request(ip="192.168.0.5")) is True
    assert is_internal_request(make_request(ip="172.16.5.5")) is True
    assert is_internal_request(make_request(ip="203.0.113.10")) is False


def test_is_internal_request_custom_cidrs_and_proxy_trust():
    """``is_internal_request`` honors a custom CIDR list and resolves the
    client IP proxy-trust-aware, so an internal client behind a trusted proxy
    is still recognized as internal.
    """
    assert (
        is_internal_request(
            make_request(ip="100.64.0.9"), internal_ips=["100.64.0.0/10"]
        )
        is True
    )
    assert (
        is_internal_request(
            make_request(ip="203.0.113.9"), internal_ips=["100.64.0.0/10"]
        )
        is False
    )
    with override_settings(RATELIMIT_TRUSTED_PROXIES=["10.0.0.0/8"]):
        req = make_request(
            ip="10.0.0.1", headers={"X-Forwarded-For": "192.168.1.50, 10.0.0.2"}
        )
        assert is_internal_request(req) is True


def test_is_internal_request_skip_if_bypass(real_backend):
    """Real scenario: ``skip_if=is_internal_request`` lets internal traffic
    bypass the limiter entirely while external traffic is still capped.
    """

    @rate_limit(key="ip", rate="1/m", skip_if=is_internal_request)
    def view(_request):
        return _ok_view(_request)

    # Internal IP: never blocked, even far beyond the limit.
    internal = [make_request(ip="10.10.10.10") for _ in range(5)]
    assert _codes(view, internal) == [OK, OK, OK, OK, OK]

    # External IP: capped at 1/m.
    external = [make_request(ip="203.0.113.210") for _ in range(2)]
    assert _codes(view, external) == [OK, TOO_MANY]


def test_is_exempt_request_paths_and_ips():
    """``is_exempt_request`` exempts requests by path regex and by IP/CIDR."""
    exempt_paths = [r"^/health", r"^/static/"]
    assert is_exempt_request(make_request(path="/health"), exempt_paths) is True
    assert is_exempt_request(make_request(path="/static/app.js"), exempt_paths) is True
    assert is_exempt_request(make_request(path="/api/users"), exempt_paths) is False

    assert (
        is_exempt_request(make_request(ip="10.0.0.4"), exempt_ips=["10.0.0.0/8"])
        is True
    )
    assert (
        is_exempt_request(make_request(ip="203.0.113.4"), exempt_ips=["10.0.0.0/8"])
        is False
    )
    # Exact-match IP (no CIDR).
    assert (
        is_exempt_request(make_request(ip="198.51.100.4"), exempt_ips=["198.51.100.4"])
        is True
    )


def test_is_exempt_request_skip_if_bypass(real_backend):
    """Real scenario: ``skip_if`` built on ``is_exempt_request`` lets a
    health-check path bypass the limiter while ordinary paths are capped.
    """

    def skip(request):
        return is_exempt_request(request, exempt_paths=[r"^/health"])

    @rate_limit(key="ip", rate="1/m", skip_if=skip)
    def view(_request):
        return _ok_view(_request)

    health = [make_request(ip="203.0.113.220", path="/health") for _ in range(4)]
    assert _codes(view, health) == [OK, OK, OK, OK]

    api = [make_request(ip="203.0.113.220", path="/api") for _ in range(2)]
    assert _codes(view, api) == [OK, TOO_MANY]


def test_should_skip_path():
    """``should_skip_path`` matches by path prefix."""
    patterns = ["/admin/", "/health/"]
    assert should_skip_path("/admin/users", patterns) is True
    assert should_skip_path("/health/live", patterns) is True
    assert should_skip_path("/api/users", patterns) is False
    assert should_skip_path("/", patterns) is False


def test_get_rate_for_path():
    """``get_rate_for_path`` picks the configured rate by path prefix, falling
    back to the default when nothing matches.
    """
    rate_limits = {"/api/": "1000/h", "/auth/": "5/m"}
    default = "100/m"
    assert get_rate_for_path("/api/users", rate_limits, default) == "1000/h"
    assert get_rate_for_path("/auth/login", rate_limits, default) == "5/m"
    assert get_rate_for_path("/public/page", rate_limits, default) == default


def test_get_rate_for_path_drives_real_limit(real_backend):
    """Real scenario: a view whose rate is chosen via ``get_rate_for_path``
    enforces the matched per-path rate against the live backend.
    """
    rate_limits = {"/auth/": "2/m"}

    auth_rate = get_rate_for_path("/auth/login", rate_limits, "50/m")

    @rate_limit(key="ip", rate=auth_rate)
    def auth_view(_request):
        return _ok_view(_request)

    codes = _codes(auth_view, [make_request(ip="203.0.113.230") for _ in range(3)])
    assert codes == [OK, OK, TOO_MANY]


def test_invalid_identifier_type_raises():
    """A bad client-identifier type is a configuration error, surfaced as
    ImproperlyConfigured rather than silently mis-keying.
    """
    from django_smart_ratelimit.key_functions import get_client_identifier

    with pytest.raises(ImproperlyConfigured):
        get_client_identifier(make_request(), identifier_type="bogus")
