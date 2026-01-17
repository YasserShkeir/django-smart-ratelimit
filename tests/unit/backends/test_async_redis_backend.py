import unittest
from unittest.mock import AsyncMock, patch

import pytest

from django.test import SimpleTestCase

# Check if redis is available
try:
    import redis as redis_module  # noqa: F401

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


@pytest.mark.asyncio
@unittest.skipUnless(HAS_REDIS, "redis package not installed")
class AsyncRedisBackendTest(SimpleTestCase):
    @patch("redis.asyncio.Redis")
    @patch("redis.asyncio.from_url")
    async def test_initialization(self, mock_from_url, mock_redis_cls):
        """Test that AsyncRedisBackend initializes correctly."""
        from django_smart_ratelimit.backends.redis_backend import AsyncRedisBackend

        # Mock client behavior
        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_redis_cls.return_value = mock_client
        mock_client.script_load.return_value = "mock_sha"
        mock_client.evalsha.return_value = 1

        backend = AsyncRedisBackend(url="redis://localhost:6379/0")

        # Test client creation
        client = await backend._get_client()
        self.assertEqual(client, mock_client)

        # Test aincr
        # config = {"key": "test_key", "period": 60}
        count = await backend.aincr("test_key", 60)
        self.assertEqual(count, 1)
        mock_client.evalsha.assert_called_once()
