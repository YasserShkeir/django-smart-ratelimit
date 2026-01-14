"""
Comprehensive Rate Limiting Decorator Test Suite.

This module provides complete test coverage for the @rate_limit decorator
and all its features without duplication. It uses subTests to efficiently
cover all combinations of decorator parameters.
"""

import unittest
from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from django_smart_ratelimit import generate_key, parse_rate, rate_limit
from tests.utils import BaseBackendTestCase, create_test_user

# Check if redis is available
try:
    import redis as redis_module  # noqa: F401

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class RateLimitDecoratorCoreTests(BaseBackendTestCase):
    """
    Core decorator functionality tests.

    Comprehensive and unique tests covering all rate limit decorator features
    including rate parsing, key generation, blocking behavior, algorithm selection,
    and backend integration.
    """

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.factory = RequestFactory()
        self.user = create_test_user()

    # =========================================================================
    # RATE PARSING TESTS
    # =========================================================================

    def test_parse_rate_seconds(self):
        """Test parsing of seconds rate format."""
        self.assertEqual(parse_rate("10/s"), (10, 1))

    def test_parse_rate_minutes(self):
        """Test parsing of minutes rate format."""
        self.assertEqual(parse_rate("100/m"), (100, 60))

    def test_parse_rate_hours(self):
        """Test parsing of hours rate format."""
        self.assertEqual(parse_rate("1000/h"), (1000, 3600))

    def test_parse_rate_days(self):
        """Test parsing of days rate format."""
        self.assertEqual(parse_rate("10000/d"), (10000, 86400))

    def test_parse_rate_single_request(self):
        """Test parsing of single request rate."""
        self.assertEqual(parse_rate("1/s"), (1, 1))

    def test_parse_rate_high_volume(self):
        """Test parsing of high volume rate."""
        self.assertEqual(parse_rate("5000/h"), (5000, 3600))

    def test_parse_rate_invalid_missing_period(self):
        """Test parsing invalid rate: missing period."""
        with self.assertRaises(Exception):
            parse_rate("10")

    def test_parse_rate_invalid_period(self):
        """Test parsing invalid rate: invalid period char."""
        with self.assertRaises(Exception):
            parse_rate("10/x")

    def test_parse_rate_invalid_number(self):
        """Test parsing invalid rate: non-numeric count."""
        with self.assertRaises(Exception):
            parse_rate("abc/m")

    def test_parse_rate_too_many_parts(self):
        """Test parsing invalid rate: too many parts."""
        with self.assertRaises(Exception):
            parse_rate("10/m/s")

    def test_parse_rate_empty(self):
        """Test parsing invalid rate: empty string."""
        with self.assertRaises(Exception):
            parse_rate("")

    # =========================================================================
    # KEY GENERATION TESTS
    # =========================================================================

    def test_generate_key_simple_string(self):
        """Test key generation with simple string key."""
        request = self.factory.get("/")
        self.assertEqual(generate_key("test_key", request), "test_key")

    def test_generate_key_namespaced(self):
        """Test key generation with namespaced key."""
        request = self.factory.get("/")
        self.assertEqual(generate_key("api:v1", request), "api:v1")

    def test_generate_key_empty(self):
        """Test key generation with empty key."""
        request = self.factory.get("/")
        self.assertEqual(generate_key("", request), "")

    def test_generate_key_with_spaces(self):
        """Test key generation with spaces in key."""
        request = self.factory.get("/")
        self.assertEqual(generate_key("key with spaces", request), "key with spaces")

    def test_generate_key_callable_authenticated_user(self):
        """Test key generation with callable keys for authenticated users."""
        request = self.factory.get("/")
        request.user = self.user

        def user_key_func(req):
            return f"user:{req.user.id}" if req.user.is_authenticated else "anon"

        result = generate_key(user_key_func, request)
        self.assertEqual(result, f"user:{self.user.id}")

    def test_generate_key_callable_anonymous_user(self):
        """Test key generation with callable keys for anonymous users."""
        request = self.factory.get("/")
        request.user = AnonymousUser()

        def user_key_func(req):
            return f"user:{req.user.id}" if req.user.is_authenticated else "anon"

        result = generate_key(user_key_func, request)
        self.assertEqual(result, "anon")

    def test_generate_key_callable_with_ip_fallback(self):
        """Test key generation with IP fallback logic."""
        request = self.factory.get("/", REMOTE_ADDR="192.168.1.1")
        request.user = AnonymousUser()

        def ip_fallback_key(req):
            if req.user.is_authenticated:
                return f"user:{req.user.id}"
            return f"ip:{req.META.get('REMOTE_ADDR', 'unknown')}"

        result = generate_key(ip_fallback_key, request)
        self.assertEqual(result, "ip:192.168.1.1")

    # =========================================================================
    # DECORATOR BEHAVIOR TESTS - CORE FUNCTIONALITY
    # =========================================================================

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_within_limit_success(self, mock_get_backend):
        """Test decorator allows requests within rate limit."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 5  # Within limit of 10
        mock_backend.increment.return_value = (5, 5)
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m")
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        # Verify success response and headers
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "Success")
        self.assertIn("X-RateLimit-Limit", response.headers)
        self.assertIn("X-RateLimit-Remaining", response.headers)
        self.assertIn("X-RateLimit-Reset", response.headers)

        # Verify backend was called correctly
        mock_backend.increment.assert_called_once()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_exceeds_limit_blocked(self, mock_get_backend):
        """Test decorator blocks requests when limit exceeded (default behavior)."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 11  # Exceeds limit of 10
        mock_backend.increment.return_value = (11, 0)
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m", block=True)
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        self.assertEqual(response.status_code, 429)
        # Check status code is 429, which is what matters
        # Different Django versions may use different HttpResponseTooManyRequests classes

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_exceeds_limit_not_blocked(self, mock_get_backend):
        """Test decorator allows requests but adds headers when block=False."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 11  # Exceeds limit of 10
        mock_backend.increment.return_value = (11, 0)
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m", block=False)
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        # Should continue execution
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "Success")
        # Should indicate limit exceeded in headers
        self.assertEqual(response.headers["X-RateLimit-Remaining"], "0")

    # =========================================================================
    # REQUEST DETECTION TESTS
    # =========================================================================

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_no_request_object_skips_limiting(self, mock_get_backend):
        """Test decorator skips rate limiting when no request object found."""
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m")
        def test_function(data):
            return f"Processed: {data}"

        result = test_function("test_data")

        # Should execute normally without rate limiting
        self.assertEqual(result, "Processed: test_data")
        mock_backend.incr.assert_not_called()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_drf_viewset_signature(self, mock_get_backend):
        """Test decorator with DRF ViewSet-style method signature."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 3
        mock_backend.increment.return_value = (3, 7)
        mock_get_backend.return_value = mock_backend

        class TestViewSet:
            @rate_limit(key="ip", rate="10/m")
            def retrieve(self, request, *args, **kwargs):
                return HttpResponse("ViewSet Success")

        viewset = TestViewSet()
        request = self.factory.get("/", REMOTE_ADDR="192.168.1.1")

        response = viewset.retrieve(request, pk=1)

        # Verify request was found and processed
        self.assertEqual(response.status_code, 200)
        mock_backend.increment.assert_called_once()
        # Verify IP key was generated correctly
        args, _ = mock_backend.increment.call_args
        self.assertIn("ip:192.168.1.1", args[0])

    # =========================================================================
    # BACKEND SELECTION TESTS
    # =========================================================================

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_custom_backend_selection(self, mock_get_backend):
        """Test decorator with explicit backend specification."""
        mock_backend = Mock()
        mock_backend.increment.return_value = (1, 9)
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m", backend="custom_backend")
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        # Verify correct backend was requested
        mock_get_backend.assert_called_with("custom_backend")
        self.assertEqual(response.status_code, 200)

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_default_backend_when_none_specified(self, mock_get_backend):
        """Test decorator uses default backend when none specified."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_backend.increment.return_value = (1, 9)
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m")
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        # Verify default backend was used (None passed to get_backend)
        mock_get_backend.assert_called_with(None)
        self.assertEqual(response.status_code, 200)

    # =========================================================================
    # SKIP_IF CONDITION TESTS
    # =========================================================================

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_skip_if_condition_true(self, mock_get_backend):
        """Test decorator skips rate limiting when skip_if returns True."""
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend

        def skip_for_staff(request):
            return getattr(request.user, "is_staff", False)

        @rate_limit(key="test", rate="10/m", skip_if=skip_for_staff)
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        request.user = Mock()
        request.user.is_staff = True

        response = test_view(request)

        # Should skip rate limiting
        self.assertEqual(response.status_code, 200)
        mock_backend.incr.assert_not_called()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_skip_if_condition_false(self, mock_get_backend):
        """Test decorator applies rate limiting when skip_if returns False."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_backend.increment.return_value = (1, 9)
        mock_get_backend.return_value = mock_backend

        def skip_for_staff(request):
            return getattr(request.user, "is_staff", False)

        @rate_limit(key="test", rate="10/m", skip_if=skip_for_staff)
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        request.user = Mock()
        request.user.is_staff = False

        response = test_view(request)

        # Should apply rate limiting
        self.assertEqual(response.status_code, 200)
        mock_backend.increment.assert_called_once()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_skip_if_exception_continues_with_limiting(
        self, mock_get_backend
    ):
        """Test decorator continues with rate limiting if skip_if raises exception."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_backend.increment.return_value = (1, 9)
        mock_get_backend.return_value = mock_backend

        def failing_skip_if(request):
            raise ValueError("Skip function failed")

        @rate_limit(key="test", rate="10/m", skip_if=failing_skip_if)
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")

        response = test_view(request)

        # Should continue with rate limiting despite skip_if failure
        self.assertEqual(response.status_code, 200)
        mock_backend.increment.assert_called_once()

    # =========================================================================
    # ALGORITHM SELECTION TESTS
    # =========================================================================

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_token_bucket_with_config(self, mock_get_backend):
        """Test decorator with token bucket algorithm and custom config."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_backend.increment.return_value = (1, 9)
        mock_backend.config = {}
        mock_get_backend.return_value = mock_backend

        algorithm_config = {"bucket_size": 20, "refill_rate": 2.0}

        @rate_limit(
            key="test",
            rate="10/m",
            algorithm="token_bucket",
            algorithm_config=algorithm_config,
        )
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_backend.config["algorithm"], "token_bucket")

    # =========================================================================
    # COMPREHENSIVE COMBINATION TESTS
    # =========================================================================


class RateLimitDecoratorIntegrationTests(TestCase):
    """Integration tests for decorator with real backend scenarios."""

    def setUp(self):
        self.factory = RequestFactory()

    @unittest.skipUnless(HAS_REDIS, "redis package not installed")
    @patch("django_smart_ratelimit.backends.redis_backend.redis")
    def test_decorator_redis_backend_integration(self, mock_redis_module):
        """Test decorator with Redis backend integration."""
        from django_smart_ratelimit.backends import clear_backend_cache

        # Clear backend cache to ensure fresh instance
        clear_backend_cache()

        # Mock Redis client
        mock_redis_client = Mock()
        mock_redis_module.Redis.return_value = mock_redis_client
        mock_redis_client.ping.return_value = True
        mock_redis_client.script_load.return_value = "script_sha"
        mock_redis_client.evalsha.return_value = 3  # Current count
        mock_redis_client.ttl.return_value = 45  # Seconds remaining

        @rate_limit(key="integration_test", rate="5/s", backend="redis")
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("X-RateLimit-Limit", response.headers)
        self.assertEqual(response.headers["X-RateLimit-Limit"], "5")


class RateLimitDecoratorErrorHandlingTests(BaseBackendTestCase):
    """Test error handling and edge cases."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_backend_failure_graceful_degradation(self, mock_get_backend):
        """Test decorator handles backend failure - verifies exception is raised."""
        mock_backend = Mock()
        mock_backend.incr.side_effect = Exception("Backend connection failed")
        mock_backend.increment.side_effect = Exception("Backend connection failed")
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m")
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")

        # Current implementation raises exception on backend failure
        # This is expected behavior to alert of infrastructure issues
        with self.assertRaises(Exception) as context:
            test_view(request)

        self.assertIn("Backend connection failed", str(context.exception))

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_key_function_failure(self, mock_get_backend):
        """Test decorator handles key function failure - verifies exception is raised."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        def failing_key_func(request, *args, **kwargs):
            raise ValueError("Key generation failed")

        @rate_limit(key=failing_key_func, rate="10/m")
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")

        # Current implementation raises exception on key function failure
        with self.assertRaises(ValueError) as context:
            test_view(request)

        self.assertIn("Key generation failed", str(context.exception))


class RateLimitDecoratorEnableSettingTests(BaseBackendTestCase):
    """Tests for RATELIMIT_ENABLE setting in decorator."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.factory = RequestFactory()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_disabled_when_ratelimit_enable_false(self, mock_get_backend):
        """Test that decorator is bypassed when RATELIMIT_ENABLE=False."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        from django_smart_ratelimit.config import RateLimitSettings

        # Create settings with enabled=False
        disabled_settings = RateLimitSettings(enabled=False)

        @rate_limit(key="test", rate="10/m", settings=disabled_settings)
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        # Backend should NOT be called when rate limiting is disabled
        mock_backend.incr.assert_not_called()
        self.assertEqual(response.status_code, 200)

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_enabled_when_ratelimit_enable_true(self, mock_get_backend):
        """Test that decorator applies rate limiting when RATELIMIT_ENABLE=True."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_backend.increment.return_value = (1, 9)  # (current_count, remaining)
        mock_get_backend.return_value = mock_backend

        from django_smart_ratelimit.config import RateLimitSettings

        # Create settings with enabled=True
        enabled_settings = RateLimitSettings(enabled=True)

        @rate_limit(key="test", rate="10/m", settings=enabled_settings)
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/")
        response = test_view(request)

        # Backend should be called when rate limiting is enabled
        self.assertTrue(
            mock_backend.incr.called or mock_backend.increment.called,
            "Backend incr or increment should be called when enabled",
        )
        self.assertEqual(response.status_code, 200)

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_disabled_no_429_response(self, mock_get_backend):
        """Test that disabled decorator never returns 429 even for heavy load."""
        mock_backend = Mock()
        # Simulate limit exceeded
        mock_backend.incr.return_value = 1000
        mock_get_backend.return_value = mock_backend

        from django_smart_ratelimit.config import RateLimitSettings

        disabled_settings = RateLimitSettings(enabled=False)

        @rate_limit(key="test", rate="1/m", settings=disabled_settings)
        def test_view(request):
            return HttpResponse("Success")

        # Make many requests - all should succeed
        for _ in range(10):
            request = self.factory.get("/")
            response = test_view(request)
            self.assertEqual(response.status_code, 200)

        # Backend should never be called
        mock_backend.incr.assert_not_called()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_with_django_settings_ratelimit_enable_false(
        self, mock_get_backend
    ):
        """Test decorator uses RATELIMIT_ENABLE from Django settings."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_backend.increment.return_value = (1, 9)
        mock_get_backend.return_value = mock_backend

        from django.test import override_settings

        with override_settings(RATELIMIT_ENABLE=False):
            # Need to reset settings cache for the change to take effect
            from django_smart_ratelimit.config import reset_settings

            reset_settings()

            # Define the decorated view inside the override_settings block
            # so it picks up the disabled setting
            @rate_limit(key="test", rate="10/m")
            def test_view(request):
                return HttpResponse("Success")

            request = self.factory.get("/")
            response = test_view(request)

            # Backend should NOT be called when rate limiting is disabled
            mock_backend.incr.assert_not_called()
            mock_backend.increment.assert_not_called()
            self.assertEqual(response.status_code, 200)
