"""
Tests for the rate limiting decorator.

This module contains tests for the @rate_limit decorator functionality.
"""

from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

# Compatibility for Django < 4.2
try:
    from django.http import HttpResponseTooManyRequests
except ImportError:

    class HttpResponseTooManyRequests(HttpResponse):
        status_code = 429


from django_smart_ratelimit.decorator import _generate_key, _parse_rate, rate_limit


class RateLimitDecoratorTests(TestCase):
    """Tests for the rate limiting decorator."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

    def test_parse_rate_valid_formats(self):
        """Test parsing of valid rate limit formats."""
        test_cases = [
            ("10/s", (10, 1)),
            ("100/m", (100, 60)),
            ("1000/h", (1000, 3600)),
            ("10000/d", (10000, 86400)),
        ]

        for rate_str, expected in test_cases:
            with self.subTest(rate=rate_str):
                result = _parse_rate(rate_str)
                self.assertEqual(result, expected)

    def test_parse_rate_invalid_formats(self):
        """Test parsing of invalid rate limit formats."""
        invalid_rates = [
            "10",  # Missing period
            "10/x",  # Invalid period
            "abc/m",  # Invalid number
            "10/m/s",  # Too many parts
            "",  # Empty string
        ]

        for rate_str in invalid_rates:
            with self.subTest(rate=rate_str):
                with self.assertRaises(Exception):
                    _parse_rate(rate_str)

    def test_generate_key_string(self):
        """Test key generation with string keys."""
        request = self.factory.get("/")
        key = _generate_key("test_key", request)
        self.assertEqual(key, "test_key")

    def test_generate_key_callable(self):
        """Test key generation with callable keys."""
        request = self.factory.get("/")

        def key_func(req):
            return f"user:{req.user.id if req.user.is_authenticated else 'anon'}"

        request.user = self.user
        key = _generate_key(key_func, request)
        self.assertEqual(key, f"user:{self.user.id}")

        request.user = AnonymousUser()
        key = _generate_key(key_func, request)
        self.assertEqual(key, "user:anon")

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_rate_limit_decorator_within_limit(self, mock_get_backend):
        """Test decorator when requests are within the limit."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m")
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "Success")
        self.assertIn("X-RateLimit-Limit", response.headers)
        self.assertIn("X-RateLimit-Remaining", response.headers)
        self.assertIn("X-RateLimit-Reset", response.headers)

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_rate_limit_decorator_exceeds_limit_blocked(self, mock_get_backend):
        """
        Test decorator when requests exceed the limit and blocking is enabled.
        """
        mock_backend = Mock()
        mock_backend.incr.return_value = 11  # Exceeds limit of 10
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m", block=True)
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        self.assertEqual(response.status_code, 429)

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_rate_limit_decorator_exceeds_limit_not_blocked(self, mock_get_backend):
        """
        Test decorator when requests exceed the limit but blocking is disabled.
        """
        mock_backend = Mock()
        mock_backend.incr.return_value = 11  # Exceeds limit of 10
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m", block=False)
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "Success")
        self.assertEqual(response.headers["X-RateLimit-Remaining"], "0")

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_rate_limit_decorator_no_request(self, mock_get_backend):
        """Test decorator when no request object is found."""
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m")
        def test_function(data):
            return f"Processed: {data}"

        result = test_function("test_data")

        self.assertEqual(result, "Processed: test_data")
        mock_backend.incr.assert_not_called()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_rate_limit_decorator_with_custom_backend(self, mock_get_backend):
        """Test decorator with custom backend specification."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m", backend="custom_backend")
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        mock_get_backend.assert_called_with("custom_backend")
        self.assertEqual(response.status_code, 200)


class RateLimitIntegrationTests(TestCase):
    """Integration tests for the rate limiting decorator."""

    def setUp(self):
        self.factory = RequestFactory()

    @patch("django_smart_ratelimit.backends.redis_backend.redis")
    def test_rate_limit_with_redis_backend(self, mock_redis_module):
        """Test rate limiting with Redis backend integration."""
        from django_smart_ratelimit.backends import clear_backend_cache

        # Clear backend cache to ensure fresh instance
        clear_backend_cache()

        # Mock Redis client
        mock_redis_client = Mock()
        mock_redis_module.Redis.return_value = mock_redis_client
        mock_redis_client.ping.return_value = True
        mock_redis_client.script_load.return_value = "script_sha"
        mock_redis_client.evalsha.return_value = 1
        mock_redis_client.ttl.return_value = 60

        @rate_limit(key="integration_test", rate="5/s")
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("X-RateLimit-Limit", response.headers)
        self.assertEqual(response.headers["X-RateLimit-Limit"], "5")
