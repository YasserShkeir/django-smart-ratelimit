"""
Tests for the rate limiting decorator.

This module contains tests for the @rate_limit decorator functionality.
"""

from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from tests.utils import BaseBackendTestCase, create_test_user

# Compatibility for Django < 4.2
try:
    from django.http import HttpResponseTooManyRequests
except ImportError:

    class HttpResponseTooManyRequests(HttpResponse):
        """HttpResponseTooManyRequests implementation."""

        status_code = 429


from django_smart_ratelimit import generate_key, parse_rate, rate_limit


class RateLimitDecoratorTests(BaseBackendTestCase):
    """Tests for the rate limiting decorator."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.factory = RequestFactory()
        self.user = create_test_user()

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
                result = parse_rate(rate_str)
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
                    parse_rate(rate_str)

    def test_generate_key_string(self):
        """Test key generation with string keys."""
        _request = self.factory.get("/")
        key = generate_key("test_key", _request)
        self.assertEqual(key, "test_key")

    def test_generate_key_callable(self):
        """Test key generation with callable keys."""
        _request = self.factory.get("/")

        def key_func(req):
            return f"user:{req.user.id if req.user.is_authenticated else 'anon'}"

        _request.user = self.user
        key = generate_key(key_func, _request)
        self.assertEqual(key, f"user:{self.user.id}")

        _request.user = AnonymousUser()
        key = generate_key(key_func, _request)
        self.assertEqual(key, "user:anon")

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_rate_limit_decorator_within_limit(self, mock_get_backend):
        """Test decorator when requests are within the limit."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m")
        def test_view(_request):
            return HttpResponse("Success")

        _request = self.factory.get("/")
        response = test_view(_request)

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
        def test_view(_request):
            return HttpResponse("Success")

        _request = self.factory.get("/")
        response = test_view(_request)

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
        def test_view(_request):
            return HttpResponse("Success")

        _request = self.factory.get("/")
        response = test_view(_request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "Success")
        self.assertEqual(response.headers["X-RateLimit-Remaining"], "0")

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_rate_limit_decorator_no_request(self, mock_get_backend):
        """Test decorator when no _request object is found."""
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m")
        def test_function(data):
            return f"Processed: {data}"

        result = test_function("test_data")

        self.assertEqual(result, "Processed: test_data")
        mock_backend.incr.assert_not_called()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_rate_limit_decorator_drf_viewset_method(self, mock_get_backend):
        """Test decorator with DRF ViewSet-style method signature."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        class TestViewSet:
            @rate_limit(key="ip", rate="10/m")
            def retrieve(self, request, *args, **kwargs):
                return HttpResponse("ViewSet Success")

        viewset = TestViewSet()
        request = self.factory.get("/", REMOTE_ADDR="192.168.1.1")

        response = viewset.retrieve(request)

        # Verify that the backend was called (request was found)
        mock_backend.incr.assert_called_once()
        args, _ = mock_backend.incr.call_args
        self.assertIn("ip:192.168.1.1", args[0])  # Check that IP key was generated
        self.assertEqual(args[1], 60)  # 1 minute = 60 seconds
        self.assertEqual(response.status_code, 200)

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_rate_limit_decorator_with_custom_backend(self, mock_get_backend):
        """Test decorator with custom backend specification."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m", backend="custom_backend")
        def test_view(_request):
            return HttpResponse("Success")

        _request = self.factory.get("/")
        response = test_view(_request)

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
        def test_view(_request):
            return HttpResponse("Success")

        _request = self.factory.get("/")
        response = test_view(_request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("X-RateLimit-Limit", response.headers)
        self.assertEqual(response.headers["X-RateLimit-Limit"], "5")
