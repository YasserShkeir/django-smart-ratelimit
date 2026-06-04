"""Memcached backend for rate limiting.

A lightweight, dependency-light backend built on Memcached's atomic ``incr`` and
``add`` operations. It implements clock-aligned **fixed-window** counting, which
is Memcached's natural fit (there is no server-side scripting, so sliding-window
and bucket algorithms fall back to window counting via ``incr``).

Enable it with::

    RATELIMIT_BACKEND = "memcached"   # or the dotted path to MemcachedBackend
    RATELIMIT_MEMCACHED = {
        "HOST": "127.0.0.1",
        "PORT": 11211,
        # ...or several nodes (consistent-hashed via pymemcache.HashClient):
        # "SERVERS": ["10.0.0.1:11211", "10.0.0.2:11211"],
        "CONNECT_TIMEOUT": 1,
        "TIMEOUT": 1,
    }

Requires the optional ``pymemcache`` dependency
(``pip install django-smart-ratelimit[memcached]``).
"""

import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseBackend
from .utils import (
    get_current_timestamp,
    get_time_bucket_key_suffix,
    log_backend_operation,
    normalize_key,
)

try:
    from pymemcache.client.base import Client as _MemcacheClient
    from pymemcache.client.hash import HashClient as _MemcacheHashClient
except ImportError:  # pragma: no cover - optional dependency
    _MemcacheClient = None
    _MemcacheHashClient = None


def _safe_memcached_key(key: str) -> str:
    """Return a Memcached-safe key (no spaces/control chars, <=250 bytes).

    Rate-limit keys are normally short and safe; this guards the rare long or
    whitespace-containing key by replacing spaces and hashing anything that
    would exceed Memcached's 250-byte key limit.
    """
    key = key.replace(" ", "_")
    if len(key.encode("utf-8")) > 250 or any(ord(c) < 33 for c in key):
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"rl:{digest}"
    return key


class MemcachedBackend(BaseBackend):
    """Memcached fixed-window rate-limit backend (optional ``pymemcache``)."""

    name = "memcached"

    def __init__(
        self,
        algorithm: str = "fixed_window",
        fail_open: bool = False,
        enable_circuit_breaker: bool = True,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Build the Memcached client from ``RATELIMIT_MEMCACHED`` settings."""
        if _MemcacheClient is None:
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured(
                "The Memcached backend requires the 'pymemcache' package "
                "(pip install django-smart-ratelimit[memcached])."
            )

        from django_smart_ratelimit.config import get_settings

        settings = get_settings()
        super().__init__(
            enable_circuit_breaker=enable_circuit_breaker,
            circuit_breaker_config=circuit_breaker_config,
            fail_open=fail_open if fail_open else settings.fail_open,
            **kwargs,
        )

        self._algorithm = algorithm or settings.default_algorithm
        self._key_prefix = settings.key_prefix

        from django.conf import settings as django_settings

        config = getattr(django_settings, "RATELIMIT_MEMCACHED", {})
        self._client = self._build_client(config)

    @staticmethod
    def _parse_server(server: Any) -> Any:
        """Normalize a ``"host:port"`` string to a ``(host, port)`` tuple."""
        if isinstance(server, (tuple, list)):
            return (server[0], int(server[1]))
        if isinstance(server, str) and ":" in server:
            host, port = server.rsplit(":", 1)
            return (host, int(port))
        return server

    def _build_client(self, config: Dict[str, Any]) -> Any:
        """Create a single-server ``Client`` or a multi-node ``HashClient``."""
        connect_timeout = config.get("CONNECT_TIMEOUT", 1)
        timeout = config.get("TIMEOUT", 1)
        servers = config.get("SERVERS")
        # default_noreply=False is REQUIRED: rate limiting relies on add()
        # returning whether the key was actually created (with the pymemcache
        # default of True, storage commands are fire-and-forget and add() always
        # reports success, which would pin every window's counter at 1).
        if servers:
            return _MemcacheHashClient(
                [self._parse_server(s) for s in servers],
                connect_timeout=connect_timeout,
                timeout=timeout,
                ignore_exc=False,
                default_noreply=False,
            )
        host = config.get("HOST", "127.0.0.1")
        port = int(config.get("PORT", 11211))
        return _MemcacheClient(
            (host, port),
            connect_timeout=connect_timeout,
            timeout=timeout,
            default_noreply=False,
        )

    def _window_key(self, key: str, period: int) -> str:
        """Build the clock-aligned, Memcached-safe key for ``key``'s window."""
        normalized = normalize_key(key, self._key_prefix)
        normalized += get_time_bucket_key_suffix(period)
        return _safe_memcached_key(normalized)

    def incr(self, key: str, period: int) -> int:
        """Increment and return the counter for ``key`` within ``period``."""
        mkey = self._window_key(key, period)
        try:
            # add() is atomic and only succeeds when the key does not yet exist,
            # which makes the first request in a window deterministically 1; all
            # others go through the atomic incr().
            if self._client.add(mkey, b"1", expire=period):
                return 1
            result = self._client.incr(mkey, 1)
            if result is None:
                # The key expired between add() and incr() (rare). Re-seed it.
                self._client.add(mkey, b"1", expire=period)
                return 1
            return int(result)
        except Exception as e:
            log_backend_operation(
                "incr",
                f"memcached backend increment failed for key {key}: {e}",
                level="error",
            )
            allowed, _ = self._handle_backend_error("incr", key, e)
            return 0 if allowed else 9999

    def get_count(self, key: str, period: int = 60) -> int:
        """Return the current counter for ``key`` (0 if absent)."""
        mkey = self._window_key(key, period)
        try:
            raw = self._client.get(mkey)
            return int(raw) if raw is not None else 0
        except Exception as e:
            log_backend_operation(
                "get_count",
                f"memcached backend get_count failed for key {key}: {e}",
                level="error",
            )
            return 0

    def reset(self, key: str) -> None:
        """Clear ``key``'s counter for the current window."""
        # Reset both the clock-aligned current window and the unaligned key, so a
        # reset works regardless of the align-window-to-clock setting.
        normalized = normalize_key(key, self._key_prefix)
        candidates = {
            _safe_memcached_key(normalized),
            self._window_key(key, 60),
        }
        try:
            for mkey in candidates:
                self._client.delete(mkey)
        except Exception as e:
            log_backend_operation(
                "reset",
                f"memcached backend reset failed for key {key}: {e}",
                level="error",
            )

    def get_reset_time(self, key: str) -> Optional[int]:
        """Return ``None``: Memcached does not expose a queryable TTL.

        The decorator/middleware compute ``Retry-After`` / ``X-RateLimit-Reset``
        from the configured rate when this is ``None``.
        """
        return None

    def health_check(self) -> Dict[str, Any]:
        """Ping Memcached and report reachability."""
        info: Dict[str, Any] = {"backend": "memcached", "algorithm": self._algorithm}
        try:
            probe = _safe_memcached_key(
                normalize_key("__healthcheck__", self._key_prefix)
            )
            self._client.set(probe, b"1", expire=5)
            ok = self._client.get(probe) == b"1"
            self._client.delete(probe)
            info["healthy"] = bool(ok)
            info["timestamp"] = time.time()
        except Exception as e:  # pragma: no cover - depends on a live server
            info["healthy"] = False
            info["error"] = str(e)
        return info

    def check_batch(
        self, checks: List[Dict[str, Any]]
    ) -> List[Tuple[bool, Dict[str, Any]]]:
        """Evaluate several limits sequentially (no server-side batching)."""
        results: List[Tuple[bool, Dict[str, Any]]] = []
        for check in checks:
            key = check["key"]
            limit = int(check["limit"])
            period = int(check.get("period", 60))
            count = self.incr(key, period)
            results.append(
                (
                    count <= limit,
                    {
                        "count": count,
                        "limit": limit,
                        "remaining": max(0, limit - count),
                    },
                )
            )
        return results

    def get_current_timestamp(self) -> float:
        """Expose the shared timestamp helper (used by some algorithms)."""
        return get_current_timestamp()
