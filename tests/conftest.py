"""
Pytest configuration for django-smart-ratelimit tests.

This file contains pytest fixtures and configuration.
"""

import os

import pytest

from django.conf import settings


def pytest_configure(config):
    """Configure Django settings for pytest."""
    if not settings.configured:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
        import django

        django.setup()


@pytest.fixture
def django_user_model():
    """Return the Django user model."""
    from django.contrib.auth import get_user_model

    return get_user_model()


@pytest.fixture
def django_user(django_user_model):
    """Create a Django user for testing."""
    return django_user_model.objects.create_user(
        username="testuser", email="test@example.com", password="testpass123"
    )


@pytest.fixture
def redis_backend():
    """Return a Redis backend instance for testing."""
    from unittest.mock import Mock, patch

    with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
        mock_redis_client = Mock()
        mock_redis.Redis.return_value = mock_redis_client
        mock_redis_client.ping.return_value = True
        mock_redis_client.script_load.return_value = "script_sha"

        from django_smart_ratelimit.backends.redis_backend import RedisBackend

        yield RedisBackend()


@pytest.fixture
def mock_redis_client():
    """Return a mock Redis client for testing."""
    from unittest.mock import Mock

    mock_client = Mock()
    mock_client.ping.return_value = True
    mock_client.script_load.return_value = "script_sha"
    mock_client.evalsha.return_value = 1
    mock_client.get.return_value = "1"
    mock_client.zcard.return_value = 1
    mock_client.ttl.return_value = 60

    return mock_client
