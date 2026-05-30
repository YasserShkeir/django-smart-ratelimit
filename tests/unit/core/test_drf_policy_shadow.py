"""v4: DRF throttle parity with the decorator — CIDR policy lists + shadow mode."""

import logging
from unittest.mock import Mock

import pytest

from django.test import RequestFactory, override_settings

try:
    import rest_framework  # noqa: F401

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DRF_AVAILABLE, reason="DRF not installed")

MEMORY = "django_smart_ratelimit.backends.memory.MemoryBackend"


def _req(ip):
    req = RequestFactory().get("/api/")
    req.META["REMOTE_ADDR"] = ip
    req.user = Mock(is_authenticated=False)
    return req


def _throttle(**attrs):
    from django_smart_ratelimit.backends import clear_backend_cache
    from django_smart_ratelimit.integrations.drf import AnonRateLimitThrottle

    clear_backend_cache()
    cls = type("T", (AnonRateLimitThrottle,), {"rate": "5/m", **attrs})
    return cls()


@override_settings(RATELIMIT_BACKEND=MEMORY)
def test_deny_list_blocks():
    throttle = _throttle(deny_list=["203.0.113.0/24"])
    assert throttle.allow_request(_req("203.0.113.7"), Mock()) is False


@override_settings(RATELIMIT_BACKEND=MEMORY)
def test_allow_list_bypasses():
    # Allow-listed IP skips throttling entirely (always True, even past rate).
    throttle = _throttle(allow_list=["10.0.0.0/8"])
    view = Mock()
    for _ in range(20):
        assert throttle.allow_request(_req("10.0.0.5"), view) is True


@override_settings(RATELIMIT_BACKEND=MEMORY)
def test_deny_list_shadow_allows_but_logs(caplog):
    throttle = _throttle(deny_list=["203.0.113.0/24"], shadow=True)
    with caplog.at_level(logging.INFO):
        assert throttle.allow_request(_req("203.0.113.7"), Mock()) is True
    assert any("SHADOW" in r.message for r in caplog.records)


@override_settings(RATELIMIT_BACKEND=MEMORY)
def test_no_policy_configured_is_unaffected():
    throttle = _throttle()
    assert throttle.allow_request(_req("198.51.100.1"), Mock()) is True
