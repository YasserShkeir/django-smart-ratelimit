"""
Pytest configuration for DRF integration tests.

This file contains pytest fixtures and configuration specifically for
testing DRF integration with Django Smart Ratelimit.
"""

from unittest.mock import Mock, patch

import pytest

try:
    import rest_framework  # noqa: F401

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False


@pytest.fixture
def drf_available():
    """Check if DRF is available."""
    return DRF_AVAILABLE


@pytest.fixture
def api_client():
    """Return a DRF APIClient for testing."""
    if DRF_AVAILABLE:
        from rest_framework.test import APIClient

        return APIClient()
    return None


@pytest.fixture
def authenticated_api_client(api_client, django_user):
    """Return an authenticated DRF APIClient."""
    if api_client and django_user:
        api_client.force_authenticate(user=django_user)
        return api_client
    return None


@pytest.fixture
def staff_user(django_user_model):
    """Create a staff user for testing."""
    return django_user_model.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password="staffpass123",
        is_staff=True,
    )


@pytest.fixture
def superuser(django_user_model):
    """Create a superuser for testing."""
    return django_user_model.objects.create_user(
        username="superuser",
        email="super@example.com",
        password="superpass123",
        is_superuser=True,
    )


@pytest.fixture
def mock_rate_limit_backend():
    """Mock rate limit backend for testing."""
    with patch("django_smart_ratelimit.backends.get_backend") as mock_backend:
        mock_backend.return_value.is_rate_limited.return_value = False
        yield mock_backend


@pytest.fixture
def mock_rate_limit_backend_exceeded():
    """Mock rate limit backend with exceeded condition."""
    with patch("django_smart_ratelimit.backends.get_backend") as mock_backend:
        mock_backend.return_value.is_rate_limited.return_value = True
        yield mock_backend


@pytest.fixture
def sample_viewset():
    """Create a sample ViewSet for testing."""
    if not DRF_AVAILABLE:
        return None

    from rest_framework import viewsets
    from rest_framework.response import Response

    from django_smart_ratelimit.decorator import rate_limit

    class SampleViewSet(viewsets.ViewSet):
        @rate_limit(key="user", rate="10/m")
        def list(self, request):
            return Response({"message": "list success"})

        @rate_limit(key="user", rate="5/m")
        def create(self, request):
            return Response({"message": "create success"}, status=201)

    return SampleViewSet


@pytest.fixture
def sample_apiview():
    """Create a sample APIView for testing."""
    if not DRF_AVAILABLE:
        return None

    from rest_framework.response import Response
    from rest_framework.views import APIView

    from django_smart_ratelimit.decorator import rate_limit

    class SampleAPIView(APIView):
        @rate_limit(key="ip", rate="10/m")
        def get(self, request):
            return Response({"message": "get success"})

        @rate_limit(key="user", rate="5/m")
        def post(self, request):
            return Response({"message": "post success"}, status=201)

    return SampleAPIView


@pytest.fixture
def sample_serializer():
    """Create a sample serializer for testing."""
    if not DRF_AVAILABLE:
        return None

    from rest_framework import serializers

    class SampleSerializer(serializers.Serializer):
        title = serializers.CharField(max_length=100)
        content = serializers.CharField(max_length=1000)

        def validate_title(self, value):
            if len(value) < 3:
                raise serializers.ValidationError("Title too short")
            return value

    return SampleSerializer


@pytest.fixture
def sample_permission():
    """Create a sample permission class for testing."""
    if not DRF_AVAILABLE:
        return None

    from rest_framework.permissions import BasePermission

    from django.core.cache import cache

    class SamplePermission(BasePermission):
        def has_permission(self, request, view):
            # Simple rate limiting in permission
            user_id = request.user.id if request.user.is_authenticated else "anon"
            user_key = f"permission:{user_id}"
            current_count = cache.get(user_key, 0)

            if current_count >= 10:
                return False

            cache.set(user_key, current_count + 1, 60)
            return True

    return SamplePermission


@pytest.fixture
def clear_cache():
    """Clear Django cache before and after tests."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def mock_request_factory():
    """Create a mock request factory."""
    from django.test import RequestFactory

    return RequestFactory()


@pytest.fixture
def mock_request(mock_request_factory, django_user):
    """Create a mock request with authenticated user."""
    request = mock_request_factory.get("/api/test/")
    request.user = django_user
    return request


@pytest.fixture
def mock_anonymous_request(mock_request_factory):
    """Create a mock request with anonymous user."""
    request = mock_request_factory.get("/api/test/")
    request.user = Mock()
    request.user.is_authenticated = False
    request.META = {"REMOTE_ADDR": "127.0.0.1"}
    return request


@pytest.fixture
def rate_limited_view():
    """Create a view that can be rate limited."""
    if not DRF_AVAILABLE:
        return None

    from rest_framework.response import Response
    from rest_framework.views import APIView

    from django_smart_ratelimit.decorator import rate_limit

    class RateLimitedView(APIView):
        @rate_limit(key="user", rate="3/m")
        def get(self, request):
            return Response({"message": "success"})

    return RateLimitedView


@pytest.fixture
def memory_backend():
    """Create a memory backend for testing."""
    from django_smart_ratelimit.backends.memory import MemoryBackend

    return MemoryBackend(max_entries=100)


@pytest.fixture
def mock_backend():
    """Create a mock backend for testing."""
    mock_backend = Mock()
    mock_backend.increment.return_value = (1, 60)  # count, ttl
    mock_backend.is_rate_limited.return_value = False
    mock_backend.get_usage.return_value = {"count": 1, "limit": 10, "remaining": 9}
    return mock_backend
