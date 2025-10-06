"""
Tests for the rate limiting backends.

This module contains tests for all backend implementations.
"""

import time
import unittest
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from django_smart_ratelimit import BaseBackend, MemoryBackend, get_backend

# Check for optional dependencies
try:
    import pymongo  # noqa: F401

    HAS_PYMONGO = True
except ImportError:
    HAS_PYMONGO = False
from django_smart_ratelimit import RedisBackend


class BackendSelectionTests(TestCase):
    """Tests for backend selection logic."""

    def test_get_backend_redis_default(self):
        """Test getting Redis backend by default."""
        with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
            mock_redis_client = Mock()
            mock_redis.Redis.return_value = mock_redis_client
            mock_redis_client.ping.return_value = True
            mock_redis_client.script_load.return_value = "script_sha"

            backend = get_backend()
            self.assertIsInstance(backend, RedisBackend)

    def test_get_backend_redis_explicit(self):
        """Test getting Redis backend explicitly."""
        with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
            mock_redis_client = Mock()
            mock_redis.Redis.return_value = mock_redis_client
            mock_redis_client.ping.return_value = True
            mock_redis_client.script_load.return_value = "script_sha"

            backend = get_backend("redis")
            self.assertIsInstance(backend, RedisBackend)

    def test_get_backend_memory(self):
        """Test getting Memory backend explicitly."""
        backend = get_backend("memory")
        self.assertIsInstance(backend, MemoryBackend)

    @override_settings(RATELIMIT_BACKEND="memory")
    def test_get_backend_memory_from_settings(self):
        """Test getting memory backend from Django settings."""
        backend = get_backend()
        self.assertIsInstance(backend, MemoryBackend)

    def test_get_backend_unknown(self):
        """Test getting unknown backend raises error."""
        with self.assertRaises(ImproperlyConfigured):
            get_backend("unknown_backend")

    @override_settings(RATELIMIT_BACKEND="redis")
    def test_get_backend_from_settings(self):
        """Test getting backend from Django settings."""
        with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
            mock_redis_client = Mock()
            mock_redis.Redis.return_value = mock_redis_client
            mock_redis_client.ping.return_value = True
            mock_redis_client.script_load.return_value = "script_sha"

            backend = get_backend()
            self.assertIsInstance(backend, RedisBackend)

    @unittest.skipIf(not HAS_PYMONGO, "pymongo not installed")
    def test_get_backend_mongodb(self):
        """Test getting MongoDB backend explicitly."""
        with patch("django_smart_ratelimit.backends.mongodb.pymongo") as mock_pymongo:
            mock_client = Mock()
            mock_pymongo.MongoClient.return_value = mock_client
            mock_client.admin.command.return_value = True

            # Mock the pymongo constants
            mock_pymongo.ASCENDING = 1
            mock_pymongo.DESCENDING = -1

            backend = get_backend("mongodb")
            self.assertEqual(backend.__class__.__name__, "MongoDBBackend")

    @override_settings(RATELIMIT_BACKEND="mongodb")
    @unittest.skipIf(not HAS_PYMONGO, "pymongo not installed")
    def test_get_backend_mongodb_from_settings(self):
        """Test getting MongoDB backend from Django settings."""
        with patch("django_smart_ratelimit.backends.mongodb.pymongo") as mock_pymongo:
            mock_client = Mock()
            mock_pymongo.MongoClient.return_value = mock_client
            mock_client.admin.command.return_value = True

            # Mock the pymongo constants
            mock_pymongo.ASCENDING = 1
            mock_pymongo.DESCENDING = -1

            backend = get_backend()
            self.assertEqual(backend.__class__.__name__, "MongoDBBackend")

    @unittest.skipIf(HAS_PYMONGO, "pymongo is installed")
    def test_get_backend_mongodb_without_pymongo(self):
        """Test that MongoDB backend fails gracefully without pymongo."""
        with self.assertRaises(ImproperlyConfigured) as cm:
            get_backend("mongodb")

        self.assertIn("pymongo package", str(cm.exception))


class BaseBackendTests(TestCase):
    """Tests for the base backend class."""

    def test_base_backend_is_abstract(self):
        """Test that BaseBackend cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            BaseBackend()

    def test_base_backend_methods_are_abstract(self):
        """Test that BaseBackend methods are abstract."""

        class TestBackend(BaseBackend):
            """TestBackend implementation."""

        with self.assertRaises(TypeError):
            TestBackend()


class RedisBackendTests(TestCase):
    """Tests for the Redis backend implementation."""

    def setUp(self):
        """Set up test environment."""
        self.redis_patcher = patch(
            "django_smart_ratelimit.backends.redis_backend.redis"
        )
        self.mock_redis_module = self.redis_patcher.start()

        # Create mock Redis client
        self.mock_redis_client = Mock()
        self.mock_redis_module.Redis.return_value = self.mock_redis_client
        self.mock_redis_client.ping.return_value = True
        self.mock_redis_client.script_load.return_value = "script_sha"

        self.addCleanup(self.redis_patcher.stop)

    def test_redis_backend_initialization_success(self):
        """Test successful Redis backend initialization."""
        backend = RedisBackend()

        self.assertIsInstance(backend, RedisBackend)
        self.mock_redis_module.Redis.assert_called_once()
        self.mock_redis_client.ping.assert_called_once()
        self.assertEqual(self.mock_redis_client.script_load.call_count, 4)

    def test_redis_backend_initialization_no_redis_module(self):
        """Test Redis backend initialization when redis module is not available."""
        with patch("django_smart_ratelimit.backends.redis_backend.redis", None):
            with self.assertRaises(ImproperlyConfigured):
                RedisBackend()

    def test_redis_backend_initialization_connection_error(self):
        """Test Redis backend initialization when connection fails."""
        self.mock_redis_client.ping.side_effect = Exception("Connection failed")

        with self.assertRaises(ImproperlyConfigured):
            RedisBackend()

    @override_settings(
        RATELIMIT_REDIS={
            "host": "custom-host",
            "port": 6380,
            "db": 1,
            "password": "secret",
        }
    )
    def test_redis_backend_custom_configuration(self):
        """Test Redis backend with custom configuration."""
        RedisBackend()  # Just test initialization

        self.mock_redis_module.Redis.assert_called_once_with(
            host="custom-host",
            port=6380,
            db=1,
            password="secret",
            socket_timeout=5,
            socket_connect_timeout=5,
            decode_responses=True,
        )

    @override_settings(RATELIMIT_ALGORITHM="sliding_window")
    def test_redis_backend_incr_sliding_window(self):
        """Test Redis backend incr with sliding window."""
        self.mock_redis_client.evalsha.return_value = 5

        backend = RedisBackend()
        result = backend.incr("test_key", 60)

        self.assertEqual(result, 5)
        # Should use sliding window script
        self.mock_redis_client.evalsha.assert_called_once()

    @override_settings(
        RATELIMIT_ALGORITHM="sliding_window"
    )  # Test backward compatibility
    def test_redis_backend_backward_compatibility_sliding(self):
        """Test Redis backend backward compatibility with old setting."""
        self.mock_redis_client.evalsha.return_value = 3

        backend = RedisBackend()
        result = backend.incr("test_key", 60)

        self.assertEqual(result, 3)
        # Should use sliding window script for backward compatibility
        self.mock_redis_client.evalsha.assert_called_once()

    @override_settings(RATELIMIT_ALGORITHM="fixed_window")
    def test_redis_backend_incr_fixed_window(self):
        """Test Redis backend incr with fixed window."""
        self.mock_redis_client.evalsha.return_value = 3

        backend = RedisBackend()
        result = backend.incr("test_key", 60)

        self.assertEqual(result, 3)
        # Should use fixed window script
        self.mock_redis_client.evalsha.assert_called_once()

    @override_settings(RATELIMIT_ALGORITHM="fixed_window")
    def test_redis_backend_fixed_window_algorithm(self):
        """Test Redis backend with fixed window algorithm."""
        self.mock_redis_client.evalsha.return_value = 2

        backend = RedisBackend()
        result = backend.incr("test_key", 60)

        self.assertEqual(result, 2)
        self.mock_redis_client.evalsha.assert_called_once()
        args = self.mock_redis_client.evalsha.call_args[0]
        self.assertEqual(args[0], "script_sha")  # fixed window script
        self.assertEqual(args[1], 1)  # number of keys
        self.assertEqual(args[2], "test:ratelimit:test_key")  # key with prefix

    def test_redis_backend_reset(self):
        """Test Redis backend reset method."""
        backend = RedisBackend()
        backend.reset("test_key")

        self.mock_redis_client.delete.assert_called_once_with("test:ratelimit:test_key")

    @override_settings(RATELIMIT_ALGORITHM="sliding_window")
    def test_redis_backend_get_count_sliding_window(self):
        """Test Redis backend get_count with sliding window."""
        self.mock_redis_client.zcard.return_value = 7

        backend = RedisBackend()
        result = backend.get_count("test_key")

        self.assertEqual(result, 7)
        self.mock_redis_client.zcard.assert_called_once_with("test:ratelimit:test_key")

    @override_settings(RATELIMIT_ALGORITHM="fixed_window")
    def test_redis_backend_get_count_fixed_window(self):
        """Test Redis backend get_count with fixed window."""
        self.mock_redis_client.get.return_value = "4"

        backend = RedisBackend()
        result = backend.get_count("test_key")

        self.assertEqual(result, 4)
        self.mock_redis_client.get.assert_called_once_with("test:ratelimit:test_key")

    @override_settings(RATELIMIT_ALGORITHM="fixed_window")
    def test_redis_backend_get_count_fixed_window_no_key(self):
        """Test Redis backend get_count with fixed window when key doesn't exist."""
        self.mock_redis_client.get.return_value = None

        backend = RedisBackend()
        result = backend.get_count("test_key")

        self.assertEqual(result, 0)

    def test_redis_backend_get_reset_time(self):
        """Test Redis backend get_reset_time method."""
        self.mock_redis_client.ttl.return_value = 30

        backend = RedisBackend()
        result = backend.get_reset_time("test_key")

        self.assertIsInstance(result, int)
        self.assertGreater(result, time.time())
        self.mock_redis_client.ttl.assert_called_once_with("test:ratelimit:test_key")

    def test_redis_backend_get_reset_time_no_ttl(self):
        """Test Redis backend get_reset_time when key has no TTL."""
        self.mock_redis_client.ttl.return_value = -1

        backend = RedisBackend()
        result = backend.get_reset_time("test_key")

        self.assertIsNone(result)

    @override_settings(RATELIMIT_KEY_PREFIX="custom:")
    def test_redis_backend_custom_key_prefix(self):
        """Test Redis backend with custom key prefix."""
        backend = RedisBackend()
        key = backend._make_key("test_key")

        self.assertEqual(key, "custom:test_key")

    def test_redis_backend_health_check_healthy(self):
        """Test Redis backend health check when healthy."""
        self.mock_redis_client.ping.return_value = True
        self.mock_redis_client.info.return_value = {
            "redis_version": "6.2.0",
            "connected_clients": 5,
            "used_memory": 1024000,
            "used_memory_human": "1.0M",
        }

        backend = RedisBackend()
        health = backend.health_check()

        self.assertEqual(health["status"], "healthy")
        self.assertIn("response_time", health)
        self.assertEqual(health["redis_version"], "6.2.0")
        self.assertEqual(health["connected_clients"], 5)

    def test_redis_backend_health_check_unhealthy(self):
        """Test Redis backend health check when unhealthy."""
        # First allow initialization to succeed
        self.mock_redis_client.ping.return_value = True
        backend = RedisBackend()

        # Then make ping fail for health check
        self.mock_redis_client.ping.side_effect = Exception("Connection failed")
        health = backend.health_check()

        self.assertEqual(health["status"], "unhealthy")
        self.assertIn("error", health)
        self.assertEqual(health["error"], "Connection failed")

    def test_token_bucket_check_allows_consumption(self):
        """Redis token_bucket_check should allow and return proper metadata."""
        # [allowed, tokens_remaining, bucket_size, refill_rate, time_to_refill]
        self.mock_redis_client.evalsha.return_value = [1, 8.0, 10, 1.0, 2.0]

        backend = RedisBackend()
        allowed, meta = backend.token_bucket_check(
            key="tb_key",
            bucket_size=10,
            refill_rate=1.0,
            initial_tokens=10,
            tokens_requested=2,
        )

        self.assertTrue(allowed)
        self.assertEqual(meta.get("tokens_remaining"), 8.0)
        self.assertEqual(meta.get("bucket_size"), 10)
        self.assertEqual(meta.get("refill_rate"), 1.0)
        self.assertEqual(meta.get("tokens_requested"), 2)
        self.assertIn("time_to_refill", meta)

    def test_token_bucket_check_rejects_when_insufficient(self):
        """token_bucket_check should reject when not enough tokens."""
        self.mock_redis_client.evalsha.return_value = [0, 1.0, 10, 1.0, 9.0]

        backend = RedisBackend()
        allowed, meta = backend.token_bucket_check(
            key="tb_key",
            bucket_size=10,
            refill_rate=1.0,
            initial_tokens=1,
            tokens_requested=3,
        )

        self.assertFalse(allowed)
        self.assertEqual(meta.get("tokens_remaining"), 1.0)
        self.assertEqual(meta.get("bucket_size"), 10)
        self.assertEqual(meta.get("refill_rate"), 1.0)
        self.assertEqual(meta.get("tokens_requested"), 3)
        self.assertIsInstance(meta.get("time_to_refill"), float)

    def test_token_bucket_check_error_raises_runtimeerror(self):
        """Redis token_bucket_check should raise RuntimeError on script failure."""
        self.mock_redis_client.evalsha.side_effect = Exception("Boom")

        backend = RedisBackend()
        with self.assertRaises(RuntimeError):
            backend.token_bucket_check("tb_key", 10, 1.0, 10, 2)

    def test_token_bucket_info_success(self):
        """token_bucket_info should return metadata from script."""
        # [tokens_remaining, bucket_size, refill_rate, time_to_refill, last_refill]
        self.mock_redis_client.evalsha.return_value = [5.0, 10, 1.0, 5.0, 123456.0]

        backend = RedisBackend()
        info = backend.token_bucket_info("tb_key", 10, 1.0)

        self.assertEqual(info.get("tokens_remaining"), 5.0)
        self.assertEqual(info.get("bucket_size"), 10)
        self.assertEqual(info.get("refill_rate"), 1.0)
        self.assertIn("time_to_refill", info)
        self.assertIn("last_refill", info)

    def test_token_bucket_info_error_returns_fallback(self):
        """On script error, token_bucket_info should return fallback state."""
        self.mock_redis_client.evalsha.side_effect = Exception("Script error")

        backend = RedisBackend()
        info = backend.token_bucket_info("tb_key", 10, 1.0)

        self.assertEqual(info.get("tokens_remaining"), 10)
        self.assertEqual(info.get("bucket_size"), 10)
        self.assertEqual(info.get("refill_rate"), 1.0)
        self.assertEqual(info.get("time_to_refill"), 0.0)
        self.assertIn("last_refill", info)


class RedisBackendScriptTests(TestCase):
    """Tests for Redis Lua scripts."""

    def setUp(self):
        """Set up test environment."""
        self.redis_patcher = patch(
            "django_smart_ratelimit.backends.redis_backend.redis"
        )
        self.mock_redis_module = self.redis_patcher.start()

        # Create mock Redis client
        self.mock_redis_client = Mock()
        self.mock_redis_module.Redis.return_value = self.mock_redis_client
        self.mock_redis_client.ping.return_value = True
        self.mock_redis_client.script_load.return_value = "script_sha"

        self.addCleanup(self.redis_patcher.stop)

    def test_sliding_window_script_loading(self):
        """Test that sliding window script is loaded correctly."""
        RedisBackend()  # Just test script loading

        # Verify script_load was called 4 times
        # (sliding + fixed window + token bucket + token bucket info)
        self.assertEqual(self.mock_redis_client.script_load.call_count, 4)

        # Verify sliding window script is not empty
        calls = self.mock_redis_client.script_load.call_args_list
        sliding_script = calls[0][0][0]
        self.assertIn("ZREMRANGEBYSCORE", sliding_script)
        self.assertIn("ZCARD", sliding_script)
        self.assertIn("ZADD", sliding_script)

    def test_fixed_window_script_loading(self):
        """Test that fixed window script is loaded correctly."""
        RedisBackend()  # Just test script loading

        # Verify script_load was called 4 times
        # (sliding + fixed window + token bucket + token bucket info)
        self.assertEqual(self.mock_redis_client.script_load.call_count, 4)

        # Verify fixed window script is not empty
        calls = self.mock_redis_client.script_load.call_args_list
        fixed_script = calls[1][0][0]
        self.assertIn("INCR", fixed_script)
        self.assertIn("EXPIRE", fixed_script)

    def test_redis_backend_auth_failure(self):
        """Test Redis backend with authentication failure."""
        import os

        # Skip if no Redis auth env var set (avoid breaking CI)
        if not os.environ.get("TEST_REDIS_AUTH_FAILURE"):
            self.skipTest("Set TEST_REDIS_AUTH_FAILURE=1 to test auth failures")

        with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
            mock_redis_client = Mock()
            # Simulate auth failure
            mock_redis_client.ping.side_effect = Exception(
                "NOAUTH Authentication required"
            )
            mock_redis.Redis.return_value = mock_redis_client

            with self.assertRaises(ImproperlyConfigured) as cm:
                RedisBackend()
            self.assertIn("NOAUTH", str(cm.exception))

    def test_redis_backend_dns_failure(self):
        """Test Redis backend with DNS resolution failure."""
        import os

        if not os.environ.get("TEST_REDIS_DNS_FAILURE"):
            self.skipTest("Set TEST_REDIS_DNS_FAILURE=1 to test DNS failures")

        with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
            mock_redis_client = Mock()
            # Simulate DNS failure
            mock_redis_client.ping.side_effect = Exception("Name or service not known")
            mock_redis.Redis.return_value = mock_redis_client

            with self.assertRaises(ImproperlyConfigured) as cm:
                RedisBackend()
            self.assertIn("service not known", str(cm.exception))

    def test_redis_backend_utf8_key_value_handling(self):
        """Test Redis backend handles UTF-8 keys and values correctly."""
        with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
            mock_redis_client = Mock()
            mock_redis_client.ping.return_value = True
            mock_redis_client.script_load.return_value = "script_sha"
            mock_redis_client.setex.return_value = (
                True  # RedisBackend uses setex for expiring keys
            )
            mock_redis.Redis.return_value = mock_redis_client

            backend = RedisBackend()

            # Test UTF-8 key normalization
            utf8_key = "test:user:åäö_ñ"
            backend.set(utf8_key, "value", 60)

            # Verify the key was properly encoded/normalized when passed to Redis
            mock_redis_client.setex.assert_called()
            call_args = mock_redis_client.setex.call_args[0]
            stored_key = call_args[0]

            # Should handle UTF-8 gracefully (either as bytes or normalized string)
            self.assertIsInstance(stored_key, (str, bytes))

            # Test UTF-8 value handling
            utf8_value = "värde_测试"
            backend.set("test:utf8_value", utf8_value, 60)

            call_args = mock_redis_client.setex.call_args[0]
            stored_value = call_args[2]  # setex(key, expiration, value)
            self.assertIsInstance(stored_value, (str, bytes))

    def test_redis_backend_health_check_surfaces_error_metadata(self):
        """Test that health check error includes useful metadata."""
        with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
            mock_redis_client = Mock()
            mock_redis_client.ping.return_value = True
            mock_redis_client.script_load.return_value = "script_sha"
            mock_redis.Redis.return_value = mock_redis_client

            backend = RedisBackend()

            # Make health check fail with specific error
            mock_redis_client.ping.side_effect = Exception(
                "Connection timeout after 5s"
            )
            mock_redis_client.info.side_effect = Exception("Connection lost")

            health = backend.health_check()

            self.assertEqual(health["status"], "unhealthy")
            self.assertIn("error", health)

            # Error should contain useful debugging info
            error_msg = health["error"]
            self.assertIsInstance(error_msg, str)
            self.assertTrue(len(error_msg) > 0)

            # Should include connection details or timeout info
            self.assertTrue(
                any(
                    keyword in error_msg.lower()
                    for keyword in ["timeout", "connection", "lost", "failed"]
                ),
                f"Error message should contain connection details: {error_msg}",
            )

    def test_redis_backend_bytes_str_normalization(self):
        """Test Redis backend normalizes between bytes and str consistently."""
        with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
            mock_redis_client = Mock()
            mock_redis_client.ping.return_value = True
            mock_redis_client.script_load.return_value = "script_sha"
            mock_redis_client.get.return_value = b"42"  # Redis returns bytes
            mock_redis_client.setex.return_value = True
            mock_redis.Redis.return_value = mock_redis_client

            backend = RedisBackend()

            # Test get returns consistent type regardless of Redis bytes
            value = backend.get("test:key")

            # Should be normalized to expected type (likely string for counts)
            if value is not None:
                self.assertIsInstance(value, (str, int))

            # Test set handles both str and bytes input
            backend.set("test:str_key", "string_value", 60)
            backend.set("test:bytes_key", b"bytes_value", 60)

            # Both should succeed without type errors
            self.assertEqual(mock_redis_client.setex.call_count, 2)
