"""Unit tests for the Memcached backend.

Live tests run against a real Memcached when one is reachable (localhost:11211
by default, or MEMCACHED_HOST/PORT); they skip cleanly otherwise. Error / fail
behavior is exercised with a mocked client so it always runs.
"""

import os
import time
from unittest import mock

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from django_smart_ratelimit.backends import memcached as mc_module
from django_smart_ratelimit.backends.factory import BackendFactory
from django_smart_ratelimit.backends.memcached import (
    MemcachedBackend,
    _safe_memcached_key,
)

MEMCACHED_HOST = os.environ.get("MEMCACHED_HOST", "localhost")
MEMCACHED_PORT = int(os.environ.get("MEMCACHED_PORT", "11211"))


def _memcached_available():
    if mc_module._MemcacheClient is None:
        return False
    try:
        c = mc_module._MemcacheClient(
            (MEMCACHED_HOST, MEMCACHED_PORT), connect_timeout=1, timeout=1
        )
        c.set(b"__probe__", b"1", expire=2)
        return c.get(b"__probe__") == b"1"
    except Exception:
        return False


MEMCACHED_UP = _memcached_available()
skip_without_memcached = pytest.mark.skipif(
    not MEMCACHED_UP, reason="live Memcached unavailable"
)


def _backend(**kwargs):
    return MemcachedBackend(**kwargs)


def _unique(prefix="mc"):
    return f"{prefix}:{time.time_ns()}"


# ---------------------------------------------------------------------------
# Pure helpers (no server needed)
# ---------------------------------------------------------------------------


def test_safe_key_passthrough_for_normal_keys():
    assert _safe_memcached_key("ip:203.0.113.7") == "ip:203.0.113.7"


def test_safe_key_replaces_spaces():
    assert " " not in _safe_memcached_key("user name:bob")


def test_safe_key_hashes_long_or_control_keys():
    long_key = "x" * 300
    safe = _safe_memcached_key(long_key)
    assert safe.startswith("rl:") and len(safe.encode()) <= 250
    assert _safe_memcached_key("a\nb").startswith("rl:")


def test_parse_server_forms():
    assert MemcachedBackend._parse_server("10.0.0.1:11211") == ("10.0.0.1", 11211)
    assert MemcachedBackend._parse_server(["h", 5]) == ("h", 5)


def test_missing_pymemcache_raises_improperly_configured():
    with mock.patch.object(mc_module, "_MemcacheClient", None):
        with pytest.raises(ImproperlyConfigured):
            MemcachedBackend()


# ---------------------------------------------------------------------------
# Error / fail-open behavior (mocked client)
# ---------------------------------------------------------------------------


@skip_without_memcached
def test_incr_fail_open_returns_zero_on_client_error():
    backend = _backend(fail_open=True)
    backend._client = mock.Mock()
    backend._client.add.side_effect = OSError("down")
    # fail_open -> treated as allowed -> count 0 (under any limit)
    assert backend.incr("k", 60) == 0


@skip_without_memcached
def test_incr_fail_closed_raises_on_client_error():
    from django_smart_ratelimit.exceptions import BackendError

    backend = _backend(fail_open=False)
    backend._client = mock.Mock()
    backend._client.add.side_effect = OSError("down")
    # fail_closed -> the shared error handler raises BackendError, which the
    # decorator/middleware translate into a blocked (429) response.
    with pytest.raises(BackendError):
        backend.incr("k", 60)


@skip_without_memcached
def test_get_count_and_reset_swallow_client_errors():
    backend = _backend()
    backend._client = mock.Mock()
    backend._client.get.side_effect = OSError("down")
    backend._client.delete.side_effect = OSError("down")
    assert backend.get_count("k", 60) == 0
    backend.reset("k")  # must not raise


@skip_without_memcached
def test_incr_reseeds_when_key_expires_between_add_and_incr():
    backend = _backend()
    backend._client = mock.Mock()
    backend._client.add.return_value = False  # key "exists"
    backend._client.incr.return_value = None  # ...but expired before incr
    assert backend.incr("k", 60) == 1  # re-seeded to 1
    backend._client.add.assert_called()


# ---------------------------------------------------------------------------
# Live behavior
# ---------------------------------------------------------------------------


@skip_without_memcached
def test_incr_counts_up_within_window():
    backend = _backend(algorithm="fixed_window")
    key = _unique()
    assert [backend.incr(key, 60) for _ in range(5)] == [1, 2, 3, 4, 5]
    assert backend.get_count(key, 60) == 5
    backend.reset(key)
    assert backend.get_count(key, 60) == 0


@skip_without_memcached
def test_distinct_keys_are_isolated():
    backend = _backend()
    k1, k2 = _unique("a"), _unique("b")
    backend.incr(k1, 60)
    backend.incr(k1, 60)
    backend.incr(k2, 60)
    assert backend.get_count(k1, 60) == 2
    assert backend.get_count(k2, 60) == 1


@skip_without_memcached
def test_window_expiry_resets_count():
    backend = _backend()
    key = _unique()
    # A 1-second window; after it lapses the counter is gone.
    backend.incr(key, 1)
    backend.incr(key, 1)
    assert backend.get_count(key, 1) == 2
    time.sleep(1.2)
    # New window (clock-aligned bucket rolled over) starts fresh.
    assert backend.incr(key, 1) == 1


@skip_without_memcached
def test_health_check_reports_healthy():
    backend = _backend()
    health = backend.health_check()
    assert health["backend"] == "memcached"
    assert health["healthy"] is True


@skip_without_memcached
def test_check_batch():
    backend = _backend()
    key = _unique()
    backend.incr(key, 60)
    results = backend.check_batch(
        [{"key": key, "limit": 3, "period": 60}, {"key": _unique(), "limit": 1}]
    )
    assert results[0][0] is True and results[0][1]["count"] == 2
    assert results[1][0] is True and results[1][1]["count"] == 1


@skip_without_memcached
def test_factory_resolves_memcached_alias():
    backend = BackendFactory.create_backend("memcached")
    assert backend.name == "memcached"
    assert isinstance(backend, MemcachedBackend)


@skip_without_memcached
@override_settings(RATELIMIT_MEMCACHED={"HOST": MEMCACHED_HOST, "PORT": MEMCACHED_PORT})
def test_respects_ratelimit_memcached_setting():
    backend = _backend()
    key = _unique()
    assert backend.incr(key, 60) == 1
