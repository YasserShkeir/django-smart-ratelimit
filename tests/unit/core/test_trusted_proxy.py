"""Tests for proxy-trust-aware client IP extraction (v3.1.0)."""

from django.test import RequestFactory, TestCase, override_settings

from django_smart_ratelimit.key_functions import get_ip_key
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
