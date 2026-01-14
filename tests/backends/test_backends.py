"""
Tests for the rate limiting backends.

This module contains tests for all backend implementations.
"""

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

try:
    import redis as redis_module  # noqa: F401

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class BackendSelectionTests(TestCase):
    """Tests for backend selection logic."""

    @unittest.skipUnless(HAS_REDIS, "redis package not installed")
    def test_get_backend_redis_default(self):
        """Test getting Redis backend by default."""
        from django_smart_ratelimit import RedisBackend

        with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
            mock_redis_client = Mock()
            mock_redis.Redis.return_value = mock_redis_client
            mock_redis_client.ping.return_value = True
            mock_redis_client.script_load.return_value = "script_sha"

            backend = get_backend()
            self.assertIsInstance(backend, RedisBackend)

    @unittest.skipUnless(HAS_REDIS, "redis package not installed")
    def test_get_backend_redis_explicit(self):
        """Test getting Redis backend explicitly."""
        from django_smart_ratelimit import RedisBackend

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

    @unittest.skipUnless(HAS_REDIS, "redis package not installed")
    @override_settings(RATELIMIT_BACKEND="redis")
    def test_get_backend_from_settings(self):
        """Test getting backend from Django settings."""
        from django_smart_ratelimit import RedisBackend

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
