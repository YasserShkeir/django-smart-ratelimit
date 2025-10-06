"""
Test circuit breaker integration with backend implementations.

Focus on verifying that non-memory backends and multi-backend wiring support
circuit breaker, avoiding duplication with memory-specific tests elsewhere.
"""

from unittest.mock import Mock, patch

import pytest

from django_smart_ratelimit import MultiBackend, circuit_breaker_registry
from django_smart_ratelimit.backends.database import DatabaseBackend


@pytest.fixture(autouse=True)
def cleanup_circuit_breaker_registry():
    """Clean up circuit breaker registry before and after each test."""
    circuit_breaker_registry.reset_all()
    circuit_breaker_registry._breakers.clear()
    yield
    circuit_breaker_registry.reset_all()
    circuit_breaker_registry._breakers.clear()


class TestAllBackendsCircuitBreakerIntegration:
    """Test that backends support circuit breaker integration."""

    def test_database_backend_circuit_breaker_integration(self):
        """Database backend with circuit breaker support."""
        backend = DatabaseBackend(enable_circuit_breaker=True)

        status = backend.get_backend_health_status()
        assert status["circuit_breaker_enabled"] is True
        assert status["circuit_breaker_available"] is True
        assert "circuit_breaker" in status
        assert status["circuit_breaker"]["state"] == "closed"

    def test_multi_backend_circuit_breaker_integration(self):
        """Multi backend with circuit breaker support (child is Memory via dotted path)."""
        config = {
            "backends": [
                {
                    "type": "django_smart_ratelimit.backends.memory.MemoryBackend",
                    "name": "memory_backend",
                    "options": {
                        "enable_circuit_breaker": True,
                        "circuit_breaker_config": None,
                    },
                }
            ]
        }

        backend = MultiBackend(enable_circuit_breaker=True, **config)

        status = backend.get_backend_health_status()
        assert status["circuit_breaker_enabled"] is True
        assert status["circuit_breaker_available"] is True
        assert "circuit_breaker" in status
        assert status["circuit_breaker"]["state"] == "closed"

    def test_redis_backend_circuit_breaker_integration(self):
        """Redis backend with circuit breaker support (mocked client)."""
        with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
            mock_redis_client = Mock()
            mock_redis.Redis.return_value = mock_redis_client
            mock_redis_client.ping.return_value = True
            mock_redis_client.script_load.return_value = "script_sha"

            from django_smart_ratelimit import RedisBackend

            backend = RedisBackend(enable_circuit_breaker=True)

            status = backend.get_backend_health_status()
            assert status["circuit_breaker_enabled"] is True
            assert status["circuit_breaker_available"] is True
            assert "circuit_breaker" in status
            assert status["circuit_breaker"]["state"] == "closed"

    def test_mongodb_backend_circuit_breaker_integration(self):
        """Test MongoDB backend with circuit breaker support using mocked client."""
        with patch("django_smart_ratelimit.backends.mongodb.pymongo") as mock_pymongo:
            mock_pymongo.ASCENDING = 1
            mock_pymongo.DESCENDING = -1

            mock_client = Mock()
            mock_db = Mock()
            mock_collection = Mock()

            mock_pymongo.MongoClient.return_value = mock_client
            mock_client.get_database.return_value = mock_db
            mock_db.get_collection.return_value = mock_collection
            mock_collection.create_index.return_value = None

            from django_smart_ratelimit import MongoDBBackend

            backend = MongoDBBackend(enable_circuit_breaker=True)

            status = backend.get_backend_health_status()
            assert status["circuit_breaker_enabled"] is True
            assert status["circuit_breaker_available"] is True
            assert "circuit_breaker" in status
            assert status["circuit_breaker"]["state"] == "closed"

    def test_database_backend_with_custom_circuit_breaker_config(self):
        """Database backend accepts custom circuit breaker configuration."""
        custom_config = {"failure_threshold": 3, "recovery_timeout": 30}

        db_backend = DatabaseBackend(
            enable_circuit_breaker=True, circuit_breaker_config=custom_config
        )
        db_status = db_backend.get_circuit_breaker_status()
        assert db_status["failure_threshold"] == 3
        assert db_status is not None

    def test_database_backend_without_circuit_breaker(self):
        """Database backend can be instantiated without circuit breaker."""
        db_backend = DatabaseBackend(enable_circuit_breaker=False)
        db_health = db_backend.get_backend_health_status()
        assert db_health["circuit_breaker_enabled"] is False
