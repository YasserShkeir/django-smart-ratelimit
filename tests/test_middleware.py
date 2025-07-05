"""
Tests for the rate limiting middleware.

This module contains tests for the RateLimitMiddleware functionality.
"""

from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

# Compatibility for Django < 4.2
try:
    from django.http import HttpResponseTooManyRequests
except ImportError:

    class HttpResponseTooManyRequests(HttpResponse):
        status_code = 429


from django_smart_ratelimit.middleware import (
    RateLimitMiddleware,
    default_key_function,
    user_key_function,
)


class RateLimitMiddlewareTests(TestCase):
    """Tests for the rate limiting middleware."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

    def test_default_key_function(self):
        """Test the default key function uses IP address."""
        request = self.factory.get("/")
        key = default_key_function(request)
        self.assertEqual(key, "middleware:127.0.0.1")

    def test_default_key_function_with_forwarded_for(self):
        """Test default key function with X-Forwarded-For header."""
        request = self.factory.get("/", HTTP_X_FORWARDED_FOR="192.168.1.1, 10.0.0.1")
        key = default_key_function(request)
        self.assertEqual(key, "middleware:192.168.1.1")

    def test_user_key_function_authenticated(self):
        """Test user key function with authenticated user."""
        request = self.factory.get("/")
        request.user = self.user
        key = user_key_function(request)
        self.assertEqual(key, f"middleware:user:{self.user.id}")

    def test_user_key_function_anonymous(self):
        """Test user key function with anonymous user."""
        request = self.factory.get("/")
        request.user = Mock()
        request.user.is_authenticated = False
        key = user_key_function(request)
        self.assertEqual(key, "middleware:127.0.0.1")

    @override_settings(
        RATELIMIT_MIDDLEWARE={
            "DEFAULT_RATE": "10/m",
            "BACKEND": "redis",
            "BLOCK": True,
            "SKIP_PATHS": ["/admin/", "/health/"],
            "RATE_LIMITS": {
                "/api/": "100/h",
                "/auth/": "5/m",
            },
        }
    )
    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_middleware_initialization(self, mock_get_backend):
        """Test middleware initialization with configuration."""
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend

        def get_response(request):
            return HttpResponse("OK")

        middleware = RateLimitMiddleware(get_response)

        self.assertEqual(middleware.default_rate, "10/m")
        self.assertEqual(middleware.backend_name, "redis")
        self.assertTrue(middleware.block)
        self.assertEqual(middleware.skip_paths, ["/admin/", "/health/"])
        self.assertEqual(middleware.rate_limits["/api/"], "100/h")
        self.assertEqual(middleware.rate_limits["/auth/"], "5/m")

    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_middleware_skips_configured_paths(self, mock_get_backend):
        """Test middleware skips paths configured in SKIP_PATHS."""
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend

        def get_response(request):
            return HttpResponse("OK")

        with override_settings(
            RATELIMIT_MIDDLEWARE={"SKIP_PATHS": ["/admin/", "/health/"]}
        ):
            middleware = RateLimitMiddleware(get_response)

            # Test admin path is skipped
            request = self.factory.get("/admin/users/")
            response = middleware(request)

            self.assertEqual(response.status_code, 200)
            mock_backend.incr.assert_not_called()

            # Test health path is skipped
            request = self.factory.get("/health/check")
            response = middleware(request)

            self.assertEqual(response.status_code, 200)
            mock_backend.incr.assert_not_called()

    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_middleware_applies_path_specific_rates(self, mock_get_backend):
        """Test middleware applies different rates for different paths."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        def get_response(request):
            return HttpResponse("OK")

        with override_settings(
            RATELIMIT_MIDDLEWARE={
                "DEFAULT_RATE": "10/m",
                "RATE_LIMITS": {
                    "/api/": "100/h",
                    "/auth/": "5/m",
                },
            }
        ):
            middleware = RateLimitMiddleware(get_response)

            # Test API path gets higher rate
            request = self.factory.get("/api/users/")
            response = middleware(request)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-RateLimit-Limit"], "100")

            # Test auth path gets lower rate
            request = self.factory.get("/auth/login/")
            response = middleware(request)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-RateLimit-Limit"], "5")

    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_middleware_blocks_when_limit_exceeded(self, mock_get_backend):
        """Test middleware blocks requests when limit is exceeded."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 11  # Exceeds limit of 10
        mock_get_backend.return_value = mock_backend

        def get_response(request):
            return HttpResponse("OK")

        with override_settings(
            RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "10/m", "BLOCK": True}
        ):
            middleware = RateLimitMiddleware(get_response)

            request = self.factory.get("/")
            response = middleware(request)

            self.assertEqual(response.status_code, 429)
            self.assertIn("X-RateLimit-Limit", response.headers)
            self.assertEqual(response.headers["X-RateLimit-Remaining"], "0")

    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_middleware_allows_when_within_limit(self, mock_get_backend):
        """Test middleware allows requests when within limit."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 5  # Within limit of 10
        mock_get_backend.return_value = mock_backend

        def get_response(request):
            return HttpResponse("OK")

        with override_settings(
            RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "10/m", "BLOCK": True}
        ):
            middleware = RateLimitMiddleware(get_response)

            request = self.factory.get("/")
            response = middleware(request)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-RateLimit-Limit"], "10")
            self.assertEqual(response.headers["X-RateLimit-Remaining"], "5")

    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_middleware_with_custom_key_function(self, mock_get_backend):
        """Test middleware with custom key function."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        def get_response(request):
            return HttpResponse("OK")

        with override_settings(
            RATELIMIT_MIDDLEWARE={
                "DEFAULT_RATE": "10/m",
                "KEY_FUNCTION": ("django_smart_ratelimit.middleware.user_key_function"),
            }
        ):
            middleware = RateLimitMiddleware(get_response)

            request = self.factory.get("/")
            request.user = self.user
            response = middleware(request)

            self.assertEqual(response.status_code, 200)
            # Verify the correct key was used
            mock_backend.incr.assert_called_once()
            call_args = mock_backend.incr.call_args[0]
            self.assertEqual(call_args[0], f"middleware:user:{self.user.id}")

    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_middleware_parse_rate_error(self, mock_get_backend):
        """Test middleware handles invalid rate format during request."""
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend

        def get_response(request):
            return HttpResponse("OK")

        with override_settings(RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "invalid_rate"}):
            middleware = RateLimitMiddleware(get_response)
            request = self.factory.get("/")

            # The error should happen during request processing
            with self.assertRaises(Exception):
                middleware(request)

    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_middleware_load_invalid_key_function(self, mock_get_backend):
        """Test middleware handles invalid key function."""
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend

        def get_response(request):
            return HttpResponse("OK")

        with override_settings(
            RATELIMIT_MIDDLEWARE={"KEY_FUNCTION": "invalid.module.function"}
        ):
            with self.assertRaises(Exception):
                RateLimitMiddleware(get_response)


class RateLimitMiddlewareIntegrationTests(TestCase):
    """Integration tests for the rate limiting middleware."""

    def setUp(self):
        self.factory = RequestFactory()

    @patch("django_smart_ratelimit.backends.redis_backend.redis")
    def test_middleware_with_redis_backend(self, mock_redis_module):
        """Test middleware with Redis backend integration."""
        # Mock Redis client
        mock_redis_client = Mock()
        mock_redis_module.Redis.return_value = mock_redis_client
        mock_redis_client.ping.return_value = True
        mock_redis_client.script_load.return_value = "script_sha"
        mock_redis_client.evalsha.return_value = 1

        def get_response(request):
            return HttpResponse("OK")

        with override_settings(
            RATELIMIT_MIDDLEWARE={"DEFAULT_RATE": "5/s", "BACKEND": "redis"}
        ):
            middleware = RateLimitMiddleware(get_response)

            request = self.factory.get("/")
            response = middleware(request)

            self.assertEqual(response.status_code, 200)
            self.assertIn("X-RateLimit-Limit", response.headers)
            self.assertEqual(response.headers["X-RateLimit-Limit"], "5")
