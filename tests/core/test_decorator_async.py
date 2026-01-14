from unittest.mock import AsyncMock, Mock, patch

import pytest

from django.http import HttpResponse
from django.test import RequestFactory

from django_smart_ratelimit.decorator import rate_limit
from django_smart_ratelimit.exceptions import BackendError


# Helpers
@rate_limit(key="ip", rate="5/m", block=True)
async def decorated_async_view(request):
    return HttpResponse("Decorated Async Response")


@rate_limit(key="ip", rate="5/m", block=False)
async def decorated_async_view_fail_open(request):
    return HttpResponse("Decorated Async Fail Open")


@pytest.mark.asyncio
class TestAsyncDecorator:

    async def test_async_decorator_basic_flow(self, settings):
        """Test that @rate_limit works on async views."""
        settings.RATELIMIT_BACKEND = (
            "django_smart_ratelimit.backends.memory.MemoryBackend"
        )
        factory = RequestFactory()
        request = factory.get("/async/")

        response = await decorated_async_view(request)

        assert response.status_code == 200
        assert response.content == b"Decorated Async Response"

        # Check headers
        assert "X-RateLimit-Limit" in response.headers
        assert response.headers["X-RateLimit-Limit"] == "5"

    async def test_async_decorator_blocking(self):
        """Test blocking behavior for async views."""
        factory = RequestFactory()
        request = factory.get("/async-block/")

        # Patch get_backend to return a mock backend with high count
        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get_backend:
            mock_backend = Mock()
            # Configure aincr to return value > limit (5)
            mock_backend.aincr = AsyncMock(return_value=10)
            mock_backend.fail_open = False
            mock_get_backend.return_value = mock_backend

            response = await decorated_async_view(request)

            assert response.status_code == 429
            assert "X-RateLimit-Limit" in response.headers

    async def test_async_decorator_skip_if(self):
        """Test skip_if on async view."""
        factory = RequestFactory()
        request = factory.get("/async-skip/")

        async def skip_logic(r):
            return True

        @rate_limit(key="ip", rate="1/m", skip_if=skip_logic)
        async def skipped_view(req):
            return HttpResponse("Skipped")

        response = await skipped_view(request)
        assert response.status_code == 200
        # Should not have rate limit headers if skipped (depending on implementation,
        # usually skip returns early without headers)
        # Checking implementation: returns func result directly.
        # But wait, implementation of wrapper usually adds headers at end?
        # Let's check decorator.py implementation.
        # If skip_if returns True, it returns func(*args) directly.
        # Since func doesn't add headers, response won't have headers.
        assert "X-RateLimit-Limit" not in response.headers

    async def test_async_decorator_backend_error_fail_closed(self, settings):
        """Test that backend error raises exception/returns error response when fail_open=False."""
        settings.RATELIMIT_FAIL_OPEN = False
        factory = RequestFactory()
        request = factory.get("/async-error/")

        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get_backend:
            mock_backend = Mock()
            # aincr raises BackendError
            mock_backend.aincr = AsyncMock(
                side_effect=BackendError("Connection failed")
            )
            mock_backend.fail_open = False
            mock_get_backend.return_value = mock_backend

            response = await decorated_async_view(request)

            # Should return 429 or configured error response (fail closed blocks access by returning error response usually?)
            # In code: if not fail_open: return _create_rate_limit_response(str(e))
            # So status should be 429 (default) or whatever _create_rate_limit_response returns.
            # Usually strict mode means "Block on error".

            # Wait, default _create_rate_limit_response returns 429. NOT 200.
            # But the content might indicate error.

            assert response.status_code == 429
            assert b"Connection failed" in response.content

    async def test_async_decorator_backend_error_fail_open(self, settings):
        """Test that backend error allows request when fail_open=True."""
        settings.RATELIMIT_FAIL_OPEN = True
        factory = RequestFactory()
        request = factory.get("/async-error-open/")

        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get_backend:
            mock_backend = Mock()
            mock_backend.aincr = AsyncMock(
                side_effect=BackendError("Connection failed")
            )
            # Backend instance fail_open usually takes precedence or is inherited
            mock_backend.fail_open = True
            mock_get_backend.return_value = mock_backend

            # Using the view that usually blocks (block=True).
            # But error happens.
            response = await decorated_async_view(request)

            # Should allow access (200)
            assert response.status_code == 200
            assert response.content == b"Decorated Async Response"
