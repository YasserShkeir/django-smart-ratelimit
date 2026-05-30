"""Tests for proxy-trust-aware client IP extraction (v3.1.0)."""

import logging
from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

import django_smart_ratelimit.policy.lists as policy_lists
from django_smart_ratelimit.key_functions import get_ip_key
from django_smart_ratelimit.middleware import RateLimitMiddleware
from django_smart_ratelimit.policy import get_client_ip
from django_smart_ratelimit.policy.lists import IPList, check_lists


def _req(remote, xff=None, cf=None, real=None):
    req = RequestFactory().get("/")
    req.META["REMOTE_ADDR"] = remote
    if xff is not None:
        req.META["HTTP_X_FORWARDED_FOR"] = xff
    if cf is not None:
        req.META["HTTP_CF_CONNECTING_IP"] = cf
    if real is not None:
        req.META["HTTP_X_REAL_IP"] = real
    return req


class DefaultBehaviorTests(TestCase):
    """No proxy config: forwarded headers are trusted (backward compatible)."""

    def test_xff_leftmost_is_trusted(self):
        assert get_client_ip(_req("10.0.0.1", xff="1.2.3.4, 10.0.0.1")) == "1.2.3.4"

    def test_cf_header_takes_precedence(self):
        assert get_client_ip(_req("10.0.0.1", xff="1.2.3.4", cf="9.9.9.9")) == "9.9.9.9"

    def test_falls_back_to_remote_addr(self):
        assert get_client_ip(_req("203.0.113.7")) == "203.0.113.7"

    def test_get_ip_key_uses_extractor(self):
        assert get_ip_key(_req("10.0.0.1", xff="1.2.3.4")) == "ip:1.2.3.4"


@override_settings(RATELIMIT_TRUST_FORWARDED_HEADERS=False)
class TrustDisabledTests(TestCase):
    """Forwarded headers ignored entirely."""

    def test_remote_addr_only(self):
        assert get_client_ip(_req("203.0.113.7", xff="1.2.3.4")) == "203.0.113.7"

    def test_get_ip_key_remote_addr_only(self):
        assert get_ip_key(_req("203.0.113.7", xff="1.2.3.4")) == "ip:203.0.113.7"


@override_settings(RATELIMIT_TRUSTED_PROXIES=["10.0.0.0/8"])
class TrustedProxyTests(TestCase):
    """Secure mode: forwarded headers honored only from trusted proxies."""

    def test_real_client_from_chain(self):
        # Request arrives from a trusted proxy (10.0.0.5); the real client is
        # the right-most non-trusted entry of the chain.
        assert get_client_ip(_req("10.0.0.5", xff="1.2.3.4, 10.0.0.9")) == "1.2.3.4"

    def test_spoofed_prepended_entry_is_ignored(self):
        # A client prepending a fake entry cannot move the result: the
        # right-most non-trusted hop is still the real client.
        assert (
            get_client_ip(_req("10.0.0.5", xff="6.6.6.6, 1.2.3.4, 10.0.0.9"))
            == "1.2.3.4"
        )

    def test_direct_client_cannot_spoof(self):
        # Request did NOT come from a trusted proxy: forwarded headers are
        # ignored and REMOTE_ADDR is authoritative.
        assert get_client_ip(_req("203.0.113.7", xff="1.2.3.4")) == "203.0.113.7"

    def test_all_hops_trusted_returns_leftmost(self):
        assert get_client_ip(_req("10.0.0.5", xff="10.0.0.1, 10.0.0.9")) == "10.0.0.1"

    def test_allow_list_bypass_is_prevented(self):
        # The motivating security case: a deny-listed direct client tries to
        # spoof an allow-listed IP via X-Forwarded-For. With trusted proxies
        # configured, the spoof is ignored and the deny list still applies.
        allow = IPList(["192.168.1.0/24"])
        deny = IPList(["203.0.113.7"])
        request = _req("203.0.113.7", xff="192.168.1.50")
        should_skip, reason = check_lists(request, allow_list=allow, deny_list=deny)
        assert reason == "deny_list"
        assert should_skip is False


class TrustedProxyHeaderOnlyTests(TestCase):
    """Trusted-proxy requests that carry CF-Connecting-IP / X-Real-IP, no XFF."""

    @override_settings(RATELIMIT_TRUSTED_PROXIES=["10.0.0.0/8"])
    def test_cf_connecting_ip_used_when_no_xff(self):
        # No X-Forwarded-For present; the CF-Connecting-IP set by the trusted
        # proxy identifies the real client.
        assert get_client_ip(_req("10.0.0.5", cf="9.9.9.9")) == "9.9.9.9"

    @override_settings(RATELIMIT_TRUSTED_PROXIES=["10.0.0.0/8"])
    def test_x_real_ip_used_when_no_xff(self):
        assert get_client_ip(_req("10.0.0.5", real="8.8.8.8")) == "8.8.8.8"

    @override_settings(RATELIMIT_TRUSTED_PROXIES=["10.0.0.0/8"])
    def test_cf_header_ignored_from_untrusted_remote(self):
        # The CF header is only honored when REMOTE_ADDR is a trusted proxy.
        # A direct (untrusted) client cannot spoof it.
        assert get_client_ip(_req("203.0.113.7", cf="9.9.9.9")) == "203.0.113.7"


class IPv6ForwardingChainTests(TestCase):
    """Proxy trust works for IPv6 REMOTE_ADDRs and IPv6 forwarding chains."""

    @override_settings(RATELIMIT_TRUSTED_PROXIES=["2001:db8::/32"])
    def test_real_client_from_ipv6_chain(self):
        # Trusted IPv6 proxy (2001:db8::1); real client is the right-most
        # non-trusted hop of the IPv6 X-Forwarded-For chain.
        req = _req(
            "2001:db8::1",
            xff="2606:4700:4700::1111, 2001:db8::abcd",
        )
        assert get_client_ip(req) == "2606:4700:4700::1111"

    @override_settings(RATELIMIT_TRUSTED_PROXIES=["2001:db8::/32"])
    def test_ipv6_direct_client_cannot_spoof(self):
        # IPv6 client arriving directly (not via a trusted proxy): forwarded
        # header is ignored and REMOTE_ADDR is authoritative.
        req = _req("2606:4700:4700::1111", xff="dead::beef")
        assert get_client_ip(req) == "2606:4700:4700::1111"

    @override_settings(RATELIMIT_TRUSTED_PROXIES=["2001:db8::/32"])
    def test_get_ip_key_ipv6(self):
        req = _req("2001:db8::1", xff="2606:4700:4700::1111, 2001:db8::abcd")
        assert get_ip_key(req) == "ip:2606:4700:4700::1111"


class InvalidTrustedProxiesTests(TestCase):
    """A malformed RATELIMIT_TRUSTED_PROXIES is logged and safely ignored."""

    def setUp(self):
        # The parsed-proxy cache is keyed by the raw setting value; clear it so a
        # value cached by another test cannot mask the invalid-config path here.
        policy_lists._TRUSTED_PROXY_CACHE.clear()

    @override_settings(RATELIMIT_TRUSTED_PROXIES=["not-an-ip"])
    def test_invalid_config_logs_warning(self):
        with self.assertLogs(policy_lists.logger, level="WARNING") as cm:
            get_client_ip(_req("203.0.113.7", xff="1.2.3.4"))
        assert any(
            "Invalid RATELIMIT_TRUSTED_PROXIES" in msg for msg in cm.output
        ), cm.output

    @override_settings(RATELIMIT_TRUSTED_PROXIES=["not-an-ip"])
    def test_invalid_config_fails_secure(self):
        # SECURITY: setting RATELIMIT_TRUSTED_PROXIES signals intent to run in
        # trusted-proxy mode. If the value cannot be parsed, the extractor stays
        # in that mode and uses REMOTE_ADDR (fails SECURE) rather than silently
        # reverting to trusting the client-supplied X-Forwarded-For header. The
        # misconfiguration is surfaced via the warning asserted above.
        with self.assertLogs(policy_lists.logger, level="WARNING"):
            ip = get_client_ip(_req("203.0.113.7", xff="1.2.3.4"))
        assert ip == "203.0.113.7"


@override_settings(RATELIMIT_TRUSTED_PROXIES=["10.0.0.0/8"])
class MiddlewareTrustedProxyTests(TestCase):
    """The middleware key honors RATELIMIT_TRUSTED_PROXIES.

    The backend is mocked so the test asserts on the rate-limit key the
    middleware computes, independent of any live backend.
    """

    def setUp(self):
        policy_lists._TRUSTED_PROXY_CACHE.clear()

    def _run(self, remote_addr, xff):
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        with (
            patch(
                "django_smart_ratelimit.middleware.get_backend",
                return_value=mock_backend,
            ),
            override_settings(RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "10/m"}),
        ):
            middleware = RateLimitMiddleware(lambda request: HttpResponse("OK"))
            request = RequestFactory().get("/")
            request.META["REMOTE_ADDR"] = remote_addr
            request.META["HTTP_X_FORWARDED_FOR"] = xff
            middleware(request)
        assert mock_backend.incr.call_count == 1
        return mock_backend.incr.call_args[0][0]

    def test_spoofed_xff_from_untrusted_remote_is_ignored(self):
        # Direct (untrusted) client tries to spoof a different IP via XFF. The
        # middleware key must be based on the real REMOTE_ADDR, not the spoof.
        key = self._run("203.0.113.7", xff="1.2.3.4")
        assert key == "middleware:203.0.113.7"

    def test_real_client_used_when_remote_is_trusted_proxy(self):
        # Request arrives via a trusted proxy: the real client from the chain is
        # used as the middleware key.
        key = self._run("10.0.0.5", xff="1.2.3.4, 10.0.0.9")
        assert key == "middleware:1.2.3.4"


# Silence noisy logger output from the intentionally-invalid-config tests.
logging.getLogger("django_smart_ratelimit.policy.lists").propagate = True
