"""
Tests for NoScriptError handling in Redis backends.

After a Redis restart, cached Lua scripts are evicted. The backends must
detect NoScriptError, reload the script, and retry — rather than wrapping
the error in BackendError (which prevents recovery and keeps the circuit
breaker stuck open indefinitely).
"""

import unittest
from unittest.mock import AsyncMock, Mock, patch

import pytest

from django.test import SimpleTestCase, TestCase

try:
    import redis as redis_module

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


@unittest.skipUnless(REDIS_AVAILABLE, "redis package not installed")
class RedisBackendNoScriptErrorTests(TestCase):
    """Test that sync RedisBackend recovers from NoScriptError."""

    def setUp(self):
        from django_smart_ratelimit.backends.redis_backend import RedisBackend

        self.RedisBackend = RedisBackend

        self.redis_patcher = patch(
            "django_smart_ratelimit.backends.redis_backend.redis"
        )
        self.mock_redis_module = self.redis_patcher.start()

        self.mock_redis_client = Mock()
        self.mock_redis_module.Redis.return_value = self.mock_redis_client
        self.mock_redis_module.RedisError = redis_module.RedisError
        self.mock_redis_module.ConnectionError = redis_module.ConnectionError
        self.mock_redis_module.TimeoutError = redis_module.TimeoutError
        self.mock_redis_module.exceptions = redis_module.exceptions
        self.mock_redis_client.ping.return_value = True
        self.mock_redis_client.script_load.return_value = "initial_sha"

        self.addCleanup(self.redis_patcher.stop)

    def test_execute_with_retry_propagates_noscript_error(self):
        """_execute_with_retry must not wrap NoScriptError in BackendError.

        Bug: redis.RedisError catch clause was swallowing NoScriptError
        (a subclass of RedisError), wrapping it in BackendError. This
        prevented _eval_lua from catching NoScriptError and reloading
        the script.
        """
        backend = self.RedisBackend()

        def raise_noscript():
            raise redis_module.exceptions.NoScriptError("No matching script")

        with self.assertRaises(redis_module.exceptions.NoScriptError):
            backend._execute_with_retry(raise_noscript)

    def test_eval_lua_reloads_script_on_noscript_error(self):
        """_eval_lua should reload the script and retry on NoScriptError.

        Simulates Redis restart: first evalsha fails with NoScriptError,
        script_load returns a new SHA, second evalsha succeeds.
        """
        backend = self.RedisBackend()

        # First call: NoScriptError (stale SHA after Redis restart)
        # Second call (after reload): success
        self.mock_redis_client.evalsha.side_effect = [
            redis_module.exceptions.NoScriptError("No matching script"),
            42,
        ]
        self.mock_redis_client.script_load.return_value = "new_sha"

        result = backend._eval_lua(
            "sliding_window_sha",
            backend.SLIDING_WINDOW_SCRIPT,
            1,
            "test_key",
            60,
            100,
            1234567890,
        )

        self.assertEqual(result, 42)
        # Script should have been reloaded
        self.assertEqual(backend.sliding_window_sha, "new_sha")
        # evalsha called twice: once with old SHA, once with new
        self.assertEqual(self.mock_redis_client.evalsha.call_count, 2)

    def test_incr_recovers_from_noscript_error(self):
        """Full incr() call should recover from NoScriptError transparently.

        This is the end-to-end test: a rate limit check should succeed
        even after Redis has restarted and evicted cached scripts.
        """
        backend = self.RedisBackend()

        self.mock_redis_client.evalsha.side_effect = [
            redis_module.exceptions.NoScriptError("No matching script"),
            5,
        ]
        self.mock_redis_client.script_load.return_value = "reloaded_sha"

        result = backend.incr("test_key", 60)

        self.assertEqual(result, 5)


@pytest.mark.asyncio
@unittest.skipUnless(REDIS_AVAILABLE, "redis package not installed")
class AsyncRedisBackendNoScriptErrorTests(SimpleTestCase):
    """Test that async AsyncRedisBackend recovers from NoScriptError."""

    @patch("redis.asyncio.Redis")
    @patch("redis.asyncio.from_url")
    async def test_aincr_reloads_script_on_noscript_error(
        self, mock_from_url, mock_redis_cls
    ):
        """Aincr should reload the script and retry on NoScriptError.

        Bug: aincr had no NoScriptError handling at all — any Redis
        restart would cause permanent failure until process restart.
        """
        from django_smart_ratelimit.backends.redis_backend import AsyncRedisBackend

        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_redis_cls.return_value = mock_client

        # script_load returns SHAs during init and reload
        mock_client.script_load.return_value = "initial_sha"

        backend = AsyncRedisBackend(url="redis://localhost:6379/0")

        # Ensure client is initialized
        await backend._get_client()

        # First evalsha: NoScriptError (stale SHA)
        # Second evalsha (after reload): success
        mock_client.evalsha.side_effect = [
            redis_module.exceptions.NoScriptError("No matching script"),
            7,
        ]
        mock_client.script_load.return_value = "reloaded_sha"

        result = await backend.aincr("test_key", 60)

        self.assertEqual(result, 7)
        # evalsha called twice: stale SHA, then reloaded SHA
        self.assertEqual(mock_client.evalsha.call_count, 2)

    @patch("redis.asyncio.Redis")
    @patch("redis.asyncio.from_url")
    async def test_aincr_noscript_updates_cached_sha(
        self, mock_from_url, mock_redis_cls
    ):
        """After NoScriptError recovery, the new SHA should be cached.

        Subsequent calls should use the reloaded SHA directly without
        triggering another reload.
        """
        from django_smart_ratelimit.backends.redis_backend import AsyncRedisBackend

        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_redis_cls.return_value = mock_client
        mock_client.script_load.return_value = "initial_sha"

        backend = AsyncRedisBackend(url="redis://localhost:6379/0")
        await backend._get_client()

        # First call: NoScriptError then success after reload
        mock_client.evalsha.side_effect = [
            redis_module.exceptions.NoScriptError("No matching script"),
            3,
        ]
        mock_client.script_load.return_value = "reloaded_sha"

        await backend.aincr("test_key", 60)

        # SHA should now be updated
        sha_attr = (
            "sliding_window_sha"
            if backend.algorithm == "sliding_window"
            else "fixed_window_sha"
        )
        self.assertEqual(getattr(backend, sha_attr), "reloaded_sha")

        # Second call: should work directly with cached SHA
        mock_client.evalsha.side_effect = None
        mock_client.evalsha.return_value = 4

        result = await backend.aincr("test_key", 60)

        self.assertEqual(result, 4)

    @patch("redis.asyncio.Redis")
    @patch("redis.asyncio.from_url")
    async def test_aincr_fixed_window_reloads_script_on_noscript_error(
        self, mock_from_url, mock_redis_cls
    ):
        """Fixed-window algorithm should also recover from NoScriptError."""
        from django_smart_ratelimit.backends.redis_backend import AsyncRedisBackend

        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_redis_cls.return_value = mock_client
        mock_client.script_load.return_value = "initial_sha"

        backend = AsyncRedisBackend(
            url="redis://localhost:6379/0", algorithm="fixed_window"
        )
        await backend._get_client()

        mock_client.evalsha.side_effect = [
            redis_module.exceptions.NoScriptError("No matching script"),
            5,
        ]
        mock_client.script_load.return_value = "reloaded_sha"

        result = await backend.aincr("test_key", 60)

        self.assertEqual(result, 5)
        self.assertEqual(backend.fixed_window_sha, "reloaded_sha")
        self.assertEqual(mock_client.evalsha.call_count, 2)
