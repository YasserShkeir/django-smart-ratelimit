from django.test import RequestFactory, TestCase

from django_smart_ratelimit.config import RateLimitSettings
from django_smart_ratelimit.decorator import rate_limit


class DecoratorInjectionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_settings_injection(self):
        """Test that settings can be injected into the decorator."""
        # Create custom settings with a specific default limit
        custom_settings = RateLimitSettings(
            enabled=True,
            default_limit="1/m",  # Very restrictive limit
        )

        # Apply decorator with injected settings and NO explicit rate
        # Should use default_limit="1/m" from custom_settings
        # We need to simulate a persistent backend or mock it,
        # but since default is memory backend, it should work if we ensure same backend instance
        # or just rely on global memory backend state for the test duration?
        # Actually default backend is configured in settings.

        # We need to verify that rate="1/m" is used.
        # We can mock validate_rate_config or check headers.

        @rate_limit(key="ip", settings=custom_settings)
        def my_view(request):
            return "OK"

        request = self.factory.get("/")

        # First request should pass
        response = my_view(request)
        self.assertEqual(response, "OK")

        # Second request should be blocked (1/m limit)
        response = my_view(request)
        # Note: Depending on backend implementation, it returning 429 response object or raising exception handled by exception handler.
        # Default behavior is Block=True, returns HttpResponseTooManyRequests (status 429)

        if hasattr(response, "status_code"):
            self.assertEqual(response.status_code, 429)
        else:
            # Should not happen if blocked
            self.fail("Should have been blocked")

    def test_settings_injection_override(self):
        """Test that explicit rate overrides injected settings default."""
        custom_settings = RateLimitSettings(
            enabled=True,
            default_limit="1/m",
        )

        # explicit rate "100/m" should override "1/m"
        @rate_limit(key="ip", rate="100/m", settings=custom_settings)
        def my_view(request):
            return "OK"

        request = self.factory.get("/")

        # First request pass
        response = my_view(request)
        self.assertEqual(response, "OK")

        # Second request pass (limit is 100/m)
        response = my_view(request)
        self.assertEqual(response, "OK")
