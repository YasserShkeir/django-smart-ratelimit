"""
Pytest configuration for django-smart-ratelimit tests.

This file contains pytest fixtures and configuration.
"""

import os

import pytest

from django.conf import settings


def pytest_configure(config):  # noqa: U100
    """Configure Django settings for pytest."""
    if not settings.configured:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
        import django

        django.setup()


def pytest_collection_modifyitems(config, items):  # noqa: U100
    """Auto-apply location-based markers so ``-m`` selection works.

    The ``slow``, ``integration`` and ``unit`` markers are declared in
    ``pyproject.toml`` but were never applied to anything, which made
    ``pytest -m integration`` (or ``-m "not slow"``) silently select nothing.

    This hook tags every collected item by its location:

    - tests under ``tests/integration/`` -> ``integration``
    - tests under ``tests/performance/`` -> ``slow`` (these are sleep-heavy /
      benchmark style and should be deselectable in fast runs)
    - tests under ``tests/unit/`` -> ``unit``

    Markers already present on an item (e.g. an explicit ``@pytest.mark.slow``)
    are preserved; this only adds the location marker when it is missing.
    """
    location_markers = (
        (os.path.join("tests", "integration") + os.sep, "integration"),
        (os.path.join("tests", "performance") + os.sep, "slow"),
        (os.path.join("tests", "unit") + os.sep, "unit"),
    )
    for item in items:
        path = str(item.fspath)
        for fragment, marker in location_markers:
            if fragment in path and marker not in {m.name for m in item.iter_markers()}:
                item.add_marker(getattr(pytest.mark, marker))


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
def staff_user(django_user_model):
    """Create a staff user for testing."""
    return django_user_model.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def superuser(django_user_model):
    """Create a superuser for testing."""
    return django_user_model.objects.create_user(
        username="superuser",
        email="super@example.com",
        password="testpass123",
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def request_factory():
    """Return a Django RequestFactory."""
    from django.test import RequestFactory

    return RequestFactory()


@pytest.fixture
def redis_backend():
    """Return a Redis backend instance for testing."""
    from unittest.mock import Mock, patch

    with patch("django_smart_ratelimit.backends.redis_backend.redis") as mock_redis:
        mock_redis_client = Mock()
        mock_redis.Redis.return_value = mock_redis_client
        mock_redis_client.ping.return_value = True
        mock_redis_client.script_load.return_value = "script_sha"

        from django_smart_ratelimit import RedisBackend

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
