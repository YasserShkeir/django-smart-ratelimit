from unittest.mock import Mock, patch

import pytest

from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from django_smart_ratelimit.config import reset_settings
from django_smart_ratelimit.middleware import RateLimitMiddleware


# Async view/get_response simulation
async def async_get_response(request):
    return HttpResponse("Async Response")


@pytest.fixture(autouse=True)
def cleanup_settings():
    reset_settings()
    yield
    reset_settings()


@pytest.mark.asyncio
class TestAsyncMiddleware:

    @override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "100/m",
            "BACKEND": "memory",
            "BLOCK": True,
            "KEY_FUNCTION": "django_smart_ratelimit.middleware.default_key_function",
            # Empty list/dict to ensure no defaults interfere
            "SKIP_PATHS": [],
            "RATE_LIMITS": {},
        }
    )
    async def test_async_middleware_basic_flow(self):
        """Test that middleware handles async requests correctly."""
        # Ensure settings are loaded fresh
        reset_settings()

        factory = RequestFactory()
        request = factory.get("/test-async/", HTTP_USER_AGENT="Mozilla/5.0")

        # Initialize with async get_response
        middleware = RateLimitMiddleware(async_get_response)

        # Check if async mode detected
        assert middleware.async_mode

        # Execute
        response = await middleware(request)

        assert response.status_code == 200
        assert response.content == b"Async Response"
        assert getattr(request, "_ratelimit_middleware_processed", True)

    @override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "100/m",
            "BACKEND": "memory",
            "BLOCK": True,
            "KEY_FUNCTION": "django_smart_ratelimit.middleware.default_key_function",
            "SKIP_PATHS": [],
            "RATE_LIMITS": {},
        }
    )
    async def test_async_middleware_blocking(self):
        """Test that middleware blocks requests when limit exceeded in async mode."""
        # Ensure settings are loaded fresh
        reset_settings()

        factory = RequestFactory()
        request = factory.get("/test-limit/")

        middleware = RateLimitMiddleware(async_get_response)

        # 100/m -> Limit is 100. return_value=101 causes block.
        # Since using MemoryBackend, we mock 'incr' (sync)
        mock_incr = Mock(return_value=101)

        # We patch the method 'incr' on the backend object
        with patch.object(middleware.backend, "incr", side_effect=mock_incr):
            # Check what happens inside
            response = await middleware(request)

            # verify call
            mock_incr.assert_called_once()

            assert (
                response.status_code == 429
            ), f"Should return 429 but got {response.status_code}"
            # Check headers
            assert "Retry-After" in response.headers
