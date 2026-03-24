"""
Tests for new features: enums, custom response handlers, and custom time windows.

Covers issues:
- #44: StrEnum for algorithms and keys
- #45: Custom HttpResponse / render(template)
- #16: JSON response decorator parameter
- #7 / #22: Custom time windows
"""

import sys
import time
import unittest
import uuid
from unittest.mock import Mock, patch, MagicMock

from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, TestCase, override_settings

from django_smart_ratelimit import rate_limit, ratelimit, parse_rate
from django_smart_ratelimit.backends.memory import MemoryBackend
from django_smart_ratelimit.enums import Algorithm, RateLimitKey
from tests.utils import BaseBackendTestCase, create_test_user


def _unique_key():
    """Generate a unique key to avoid cross-test state leaks."""
    return f"test:{uuid.uuid4().hex[:8]}"


# =============================================================================
# Issue #44: StrEnum for algorithms and keys
# =============================================================================


class AlgorithmEnumTests(TestCase):
    """Test the Algorithm enum for type-safe algorithm selection."""

    def test_algorithm_values(self):
        """Algorithm enum has all expected algorithm values."""
        self.assertEqual(Algorithm.SLIDING_WINDOW, "sliding_window")
        self.assertEqual(Algorithm.FIXED_WINDOW, "fixed_window")
        self.assertEqual(Algorithm.TOKEN_BUCKET, "token_bucket")

    def test_algorithm_is_str(self):
        """Algorithm enum values are strings (StrEnum behavior)."""
        self.assertIsInstance(Algorithm.SLIDING_WINDOW, str)
        self.assertIsInstance(Algorithm.FIXED_WINDOW, str)
        self.assertIsInstance(Algorithm.TOKEN_BUCKET, str)

    def test_algorithm_str_representation(self):
        """Algorithm enum str() returns the value."""
        self.assertEqual(str(Algorithm.SLIDING_WINDOW), "sliding_window")
        self.assertEqual(str(Algorithm.TOKEN_BUCKET), "token_bucket")

    def test_algorithm_string_comparison(self):
        """Algorithm enum compares equal to its string value."""
        self.assertEqual(Algorithm.SLIDING_WINDOW, "sliding_window")
        self.assertTrue(Algorithm.FIXED_WINDOW == "fixed_window")
        self.assertFalse(Algorithm.TOKEN_BUCKET == "sliding_window")

    def test_algorithm_in_dict_key(self):
        """Algorithm enum works as dict key, interchangeable with strings."""
        d = {Algorithm.SLIDING_WINDOW: "sw"}
        self.assertEqual(d["sliding_window"], "sw")

    def test_algorithm_membership(self):
        """Algorithm enum supports membership testing."""
        self.assertIn("sliding_window", [a.value for a in Algorithm])
        self.assertIn("token_bucket", [a.value for a in Algorithm])

    def test_algorithm_iteration(self):
        """Algorithm enum supports iteration."""
        algorithms = list(Algorithm)
        self.assertEqual(len(algorithms), 3)


class RateLimitKeyEnumTests(TestCase):
    """Test the RateLimitKey enum for type-safe key selection."""

    def test_key_values(self):
        """RateLimitKey enum has all expected key values."""
        self.assertEqual(RateLimitKey.IP, "ip")
        self.assertEqual(RateLimitKey.USER, "user")
        self.assertEqual(RateLimitKey.USER_OR_IP, "user_or_ip")
        self.assertEqual(RateLimitKey.HEADER, "header")
        self.assertEqual(RateLimitKey.PARAM, "param")

    def test_key_is_str(self):
        """RateLimitKey enum values are strings (StrEnum behavior)."""
        for key in RateLimitKey:
            self.assertIsInstance(key, str)

    def test_key_string_comparison(self):
        """RateLimitKey enum compares equal to its string value."""
        self.assertEqual(RateLimitKey.IP, "ip")
        self.assertEqual(RateLimitKey.USER, "user")


@override_settings(RATELIMIT_BACKEND="memory")
class EnumDecoratorIntegrationTests(BaseBackendTestCase):
    """Test enums work correctly with the rate_limit decorator."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def test_algorithm_enum_in_decorator(self):
        """Algorithm enum can be used as algorithm parameter."""
        key = _unique_key()

        @rate_limit(key=key, rate="100/m", algorithm=Algorithm.SLIDING_WINDOW)
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_key_enum_in_decorator(self):
        """RateLimitKey enum can be used as key parameter."""

        @rate_limit(key=RateLimitKey.IP, rate="100/m")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_ratelimit_alias_with_enums(self):
        """ratelimit alias also works with enums."""

        @ratelimit(key=RateLimitKey.IP, rate="100/m", block=False)
        def view(request):
            return HttpResponse("OK")

        self.assertTrue(callable(view))

    def test_algorithm_enum_in_settings(self):
        """Algorithm enum can be used in Django settings."""
        with override_settings(RATELIMIT_ALGORITHM=Algorithm.FIXED_WINDOW):
            from django_smart_ratelimit.config import RateLimitSettings

            settings = RateLimitSettings.from_django_settings()
            self.assertEqual(settings.default_algorithm, "fixed_window")


class StrEnumBackportTests(TestCase):
    """Test StrEnum backport for Python < 3.11."""

    def test_backport_produces_str_enum(self):
        """Backport class produces values that are strings."""
        self.assertTrue(issubclass(type(Algorithm.SLIDING_WINDOW), str))

    def test_backport_enum_identity(self):
        """Enum members maintain identity."""
        self.assertIs(Algorithm("sliding_window"), Algorithm.SLIDING_WINDOW)

    def test_enum_value_error_on_invalid(self):
        """Invalid value raises ValueError."""
        with self.assertRaises(ValueError):
            Algorithm("nonexistent_algorithm")


# =============================================================================
# Issue #45 / #16: Custom response handlers and JSON responses
# =============================================================================


@override_settings(RATELIMIT_BACKEND="memory")
class CustomResponseCallbackTests(BaseBackendTestCase):
    """Test the response_callback parameter on the decorator."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def test_response_callback_called_on_limit(self):
        """response_callback is called when rate limit is exceeded."""
        custom_response = HttpResponse("Custom 429", status=429)
        callback = Mock(return_value=custom_response)
        key = _unique_key()

        @rate_limit(key=key, rate="1/m", response_callback=callback)
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        # First request should pass
        resp1 = view(request)
        self.assertEqual(resp1.status_code, 200)
        callback.assert_not_called()
        # Second request should trigger callback
        resp2 = view(request)
        self.assertEqual(resp2.status_code, 429)
        self.assertIn(b"Custom 429", resp2.content)
        callback.assert_called_once()

    def test_response_callback_receives_request(self):
        """response_callback receives the request object."""
        captured_request = {}
        key = _unique_key()

        def callback(request):
            captured_request["req"] = request
            return HttpResponse("Limited", status=429)

        @rate_limit(key=key, rate="1/m", response_callback=callback)
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        view(request)
        view(request)
        self.assertIn("req", captured_request)
        self.assertEqual(captured_request["req"].method, "GET")

    def test_response_callback_fallback_on_error(self):
        """Falls back to default response when callback raises an error."""
        key = _unique_key()

        def bad_callback(request):
            raise RuntimeError("Callback error")

        @rate_limit(key=key, rate="1/m", response_callback=bad_callback)
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        view(request)
        response = view(request)
        # Should still return 429 (default response)
        self.assertEqual(response.status_code, 429)

    def test_ratelimit_alias_passes_response_callback(self):
        """ratelimit alias correctly passes response_callback."""
        custom_response = HttpResponse("Alias callback", status=429)
        callback = Mock(return_value=custom_response)
        key = _unique_key()

        @ratelimit(key=key, rate="1/m", response_callback=callback)
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        view(request)
        resp = view(request)
        self.assertEqual(resp.status_code, 429)
        callback.assert_called_once()


@override_settings(RATELIMIT_BACKEND="memory")
class JSONContentNegotiationTests(BaseBackendTestCase):
    """Test automatic JSON response for API clients."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def test_json_response_for_json_accept_header(self):
        """Returns JSON when Accept: application/json is present."""
        key = _unique_key()

        @rate_limit(key=key, rate="1/m")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/", HTTP_ACCEPT="application/json")
        view(request)
        response = view(request)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_json_response_body_structure(self):
        """JSON response has expected structure with 'detail' field."""
        import json

        key = _unique_key()

        @rate_limit(key=key, rate="1/m")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/", HTTP_ACCEPT="application/json")
        view(request)
        response = view(request)
        body = json.loads(response.content)
        self.assertIn("detail", body)
        self.assertIn("rate limit", body["detail"].lower())

    def test_html_response_for_html_accept_header(self):
        """Returns default HTML/text when Accept is text/html."""
        key = _unique_key()

        @rate_limit(key=key, rate="1/m")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/", HTTP_ACCEPT="text/html")
        view(request)
        response = view(request)
        self.assertEqual(response.status_code, 429)
        self.assertNotEqual(response.get("Content-Type", ""), "application/json")

    def test_default_response_without_accept_header(self):
        """Returns default response when no Accept header present."""
        key = _unique_key()

        @rate_limit(key=key, rate="1/m")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        view(request)
        response = view(request)
        self.assertEqual(response.status_code, 429)

    def test_callback_takes_priority_over_json_negotiation(self):
        """response_callback takes priority over JSON content negotiation."""
        custom_response = HttpResponse("Custom", status=429)
        callback = Mock(return_value=custom_response)
        key = _unique_key()

        @rate_limit(key=key, rate="1/m", response_callback=callback)
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/", HTTP_ACCEPT="application/json")
        view(request)
        response = view(request)
        # Callback should be used, not JSON negotiation
        callback.assert_called_once()
        self.assertIn(b"Custom", response.content)


@override_settings(RATELIMIT_BACKEND="memory")
class GlobalResponseHandlerTests(BaseBackendTestCase):
    """Test the RATELIMIT_RESPONSE_HANDLER setting."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    @override_settings(
        RATELIMIT_RESPONSE_HANDLER="tests.unit.core.test_new_features.custom_handler"
    )
    def test_global_handler_callable(self):
        """Global handler is invoked when configured as dotted path."""
        key = _unique_key()

        @rate_limit(key=key, rate="1/m")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        view(request)
        response = view(request)
        self.assertEqual(response.status_code, 429)
        self.assertIn(b"Global handler", response.content)

    @override_settings(RATELIMIT_RESPONSE_HANDLER="nonexistent.module.handler")
    def test_global_handler_fallback_on_import_error(self):
        """Falls back to default when global handler import fails."""
        key = _unique_key()

        @rate_limit(key=key, rate="1/m")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        view(request)
        response = view(request)
        # Should still return 429 from default handler
        self.assertEqual(response.status_code, 429)

    def test_callback_takes_priority_over_global_handler(self):
        """Per-decorator callback takes priority over global handler."""
        custom_response = HttpResponse("Decorator callback", status=429)
        callback = Mock(return_value=custom_response)
        key = _unique_key()

        with override_settings(
            RATELIMIT_RESPONSE_HANDLER="tests.unit.core.test_new_features.custom_handler"
        ):

            @rate_limit(key=key, rate="1/m", response_callback=callback)
            def view(request):
                return HttpResponse("OK")

            request = self.factory.get("/test/")
            view(request)
            response = view(request)
            callback.assert_called_once()
            self.assertIn(b"Decorator callback", response.content)


def custom_handler(request):
    """Test handler used by GlobalResponseHandlerTests."""
    return HttpResponse("Global handler response", status=429)


class ResponseHandlerSettingsTests(TestCase):
    """Test RATELIMIT_RESPONSE_HANDLER in config."""

    def test_default_handler_is_none(self):
        """Default ratelimit_response_handler is None."""
        from django_smart_ratelimit.config import RateLimitSettings

        settings = RateLimitSettings()
        self.assertIsNone(settings.ratelimit_response_handler)

    @override_settings(RATELIMIT_RESPONSE_HANDLER="myapp.views.rate_limited")
    def test_handler_loaded_from_django_settings(self):
        """ratelimit_response_handler loaded from Django settings."""
        from django_smart_ratelimit.config import RateLimitSettings

        settings = RateLimitSettings.from_django_settings()
        self.assertEqual(settings.ratelimit_response_handler, "myapp.views.rate_limited")


# =============================================================================
# Issue #7 / #22: Custom time windows
# =============================================================================


class CustomTimeWindowTests(TestCase):
    """Test custom time window parsing in parse_rate()."""

    # Simple format (existing behavior preserved)
    def test_parse_simple_seconds(self):
        """Simple 'N/s' format returns 1 second period."""
        self.assertEqual(parse_rate("10/s"), (10, 1))

    def test_parse_simple_minutes(self):
        """Simple 'N/m' format returns 60 second period."""
        self.assertEqual(parse_rate("100/m"), (100, 60))

    def test_parse_simple_hours(self):
        """Simple 'N/h' format returns 3600 second period."""
        self.assertEqual(parse_rate("1000/h"), (1000, 3600))

    def test_parse_simple_days(self):
        """Simple 'N/d' format returns 86400 second period."""
        self.assertEqual(parse_rate("10000/d"), (10000, 86400))

    # Custom window format
    def test_parse_custom_seconds(self):
        """Custom 'N/Xs' format parses correctly."""
        self.assertEqual(parse_rate("10/30s"), (10, 30))

    def test_parse_custom_minutes(self):
        """Custom 'N/Xm' format parses correctly."""
        self.assertEqual(parse_rate("100/5m"), (100, 300))

    def test_parse_custom_hours(self):
        """Custom 'N/Xh' format parses correctly."""
        self.assertEqual(parse_rate("500/2h"), (500, 7200))

    def test_parse_custom_days(self):
        """Custom 'N/Xd' format parses correctly."""
        self.assertEqual(parse_rate("10000/7d"), (10000, 604800))

    def test_parse_custom_10_seconds(self):
        """10 requests per 10 seconds (issue #7 example)."""
        self.assertEqual(parse_rate("10/10s"), (10, 10))

    def test_parse_custom_15_minutes(self):
        """50 requests per 15 minutes."""
        self.assertEqual(parse_rate("50/15m"), (50, 900))

    def test_parse_custom_single_unit(self):
        """Custom '1s' is same as simple 's'."""
        self.assertEqual(parse_rate("10/1s"), (10, 1))
        self.assertEqual(parse_rate("10/1m"), (10, 60))

    def test_parse_invalid_rate_raises(self):
        """Invalid rate format raises ImproperlyConfigured."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            parse_rate("invalid")

    def test_parse_invalid_period_raises(self):
        """Unknown period unit raises ImproperlyConfigured."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            parse_rate("10/x")

    def test_parse_zero_multiplier_raises(self):
        """Zero multiplier raises ImproperlyConfigured."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            parse_rate("10/0s")


@override_settings(RATELIMIT_BACKEND="memory")
class CustomTimeWindowDecoratorTests(BaseBackendTestCase):
    """Test custom time windows work end-to-end with the decorator."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def test_decorator_with_custom_seconds(self):
        """Decorator works with custom second windows."""
        key = _unique_key()

        @rate_limit(key=key, rate="50/30s")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_decorator_with_custom_minutes(self):
        """Decorator works with custom minute windows."""
        key = _unique_key()

        @rate_limit(key=key, rate="100/5m")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_custom_window_rate_limiting(self):
        """Custom window enforces rate limits correctly."""
        key = _unique_key()

        @rate_limit(key=key, rate="2/30s")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        # First two requests should pass
        self.assertEqual(view(request).status_code, 200)
        self.assertEqual(view(request).status_code, 200)
        # Third should be rate limited
        self.assertEqual(view(request).status_code, 429)

    def test_custom_window_headers(self):
        """Custom window responses include rate limit headers."""
        key = _unique_key()

        @rate_limit(key=key, rate="10/30s")
        def view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        response = view(request)
        self.assertIn("X-RateLimit-Limit", response.headers)
        self.assertEqual(response["X-RateLimit-Limit"], "10")


# =============================================================================
# Issue #46: Async safety (documentation test)
# =============================================================================


class AsyncSafetyTests(TestCase):
    """Test that the library properly supports async views."""

    def test_rate_limit_wraps_async_function(self):
        """rate_limit can wrap async functions."""
        import asyncio

        @rate_limit(key="ip", rate="10/m")
        async def async_view(request):
            return HttpResponse("OK")

        self.assertTrue(asyncio.iscoroutinefunction(async_view))

    def test_algorithm_enum_with_async(self):
        """Algorithm enum works with async decorated views."""
        import asyncio

        @rate_limit(key="ip", rate="10/m", algorithm=Algorithm.SLIDING_WINDOW)
        async def async_view(request):
            return HttpResponse("OK")

        self.assertTrue(asyncio.iscoroutinefunction(async_view))


# =============================================================================
# Import / Export tests
# =============================================================================


class PublicAPIExportTests(TestCase):
    """Test that new features are properly exported from the package."""

    def test_algorithm_importable_from_package(self):
        """Algorithm can be imported from the main package."""
        from django_smart_ratelimit import Algorithm

        self.assertIsNotNone(Algorithm)

    def test_ratelimit_key_importable_from_package(self):
        """RateLimitKey can be imported from the main package."""
        from django_smart_ratelimit import RateLimitKey

        self.assertIsNotNone(RateLimitKey)

    def test_algorithm_in_all(self):
        """Algorithm is listed in __all__."""
        import django_smart_ratelimit

        self.assertIn("Algorithm", django_smart_ratelimit.__all__)

    def test_ratelimit_key_in_all(self):
        """RateLimitKey is listed in __all__."""
        import django_smart_ratelimit

        self.assertIn("RateLimitKey", django_smart_ratelimit.__all__)

    def test_enums_importable_from_enums_module(self):
        """Enums importable from the dedicated enums module."""
        from django_smart_ratelimit.enums import Algorithm, RateLimitKey

        self.assertEqual(Algorithm.SLIDING_WINDOW, "sliding_window")
        self.assertEqual(RateLimitKey.IP, "ip")
