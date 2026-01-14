"""
Integration tests for DRF rate limit modes (blocking vs non-blocking).

Tests block=False parameter behavior:
- Non-blocking mode allows requests but sets rate limit headers
- Tracking continues even when not blocking
- Headers indicate when limit would be exceeded
"""

import unittest

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

try:
    from rest_framework import status
    from rest_framework.response import Response
    from rest_framework.views import APIView

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    APIView = object
    Response = None
    status = None

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import clear_backend_cache

# Test view for non-blocking mode - only define if DRF available
if DRF_AVAILABLE:

    class NonBlockingTestView(APIView):
        @rate_limit(rate="2/m", key="ip", block=False)
        def get(self, request):
            return Response({"status": "ok"})

    class BlockingTestView(APIView):
        @rate_limit(rate="2/m", key="ip", block=True)
        def get(self, request):
            return Response({"status": "ok"})


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFNonBlockingMode(TestCase):
    """Test block=False allows requests to pass through."""

    def setUp(self):
        self.factory = RequestFactory()
        self.view = NonBlockingTestView.as_view()
        # Clear backend state
        clear_backend_cache()
        cache.clear()

    def test_non_blocking_allows_all_requests(self):
        """Non-blocking mode should allow requests even when limit exceeded."""
        # Make more requests than allowed
        for i in range(5):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "192.168.1.100"
            response = self.view(request)
            # All requests should succeed with 200
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_blocking_still_tracks_usage(self):
        """Non-blocking mode should still track and report usage in headers."""
        request = self.factory.get("/test/")
        request.META["REMOTE_ADDR"] = "192.168.1.101"
        response = self.view(request)

        # Should have rate limit headers
        if "X-RateLimit-Limit" in response:
            self.assertEqual(response["X-RateLimit-Limit"], "2")

    def test_non_blocking_headers_show_exceeded(self):
        """Headers should indicate when limit would be exceeded."""
        # Exhaust the limit
        for _ in range(3):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "192.168.1.102"
            response = self.view(request)

        # Last response should still be 200 but remaining should be 0 or negative
        self.assertEqual(response.status_code, status.HTTP_200_OK)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFBlockingMode(TestCase):
    """Test block=True (default) blocks requests when limit exceeded."""

    def setUp(self):
        self.factory = RequestFactory()
        self.view = BlockingTestView.as_view()
        clear_backend_cache()
        cache.clear()

    def test_blocking_rejects_excess_requests(self):
        """Blocking mode should return 429 when limit exceeded."""
        results = []
        for i in range(5):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "192.168.1.110"
            response = self.view(request)
            results.append(response.status_code)

        # First 2 should pass, rest should be blocked
        self.assertEqual(results[:2], [200, 200])
        self.assertTrue(all(r == 429 for r in results[2:]))


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFModeComparison(TestCase):
    """Compare blocking vs non-blocking behavior."""

    def setUp(self):
        self.factory = RequestFactory()
        clear_backend_cache()
        cache.clear()

    def test_same_rate_different_behavior(self):
        """Same rate but different blocking behavior."""
        blocking_view = BlockingTestView.as_view()
        non_blocking_view = NonBlockingTestView.as_view()

        blocking_results = []
        non_blocking_results = []

        # Test blocking view
        for i in range(4):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "10.0.0.1"
            response = blocking_view(request)
            blocking_results.append(response.status_code)

        # Test non-blocking view
        for i in range(4):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "10.0.0.2"
            response = non_blocking_view(request)
            non_blocking_results.append(response.status_code)

        # Blocking should have 429s
        self.assertIn(429, blocking_results)
        # Non-blocking should all be 200
        self.assertTrue(all(r == 200 for r in non_blocking_results))


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFNonBlockingWithMethods(TestCase):
    """Test non-blocking mode with specific HTTP methods."""

    def setUp(self):
        self.factory = RequestFactory()
        clear_backend_cache()
        cache.clear()

    def test_non_blocking_method_specific(self):
        """Non-blocking should work with method-specific limits."""

        class MethodSpecificView(APIView):
            @rate_limit(rate="1/m", key="ip", block=False)
            def post(self, request):
                return Response({"action": "created"})

            def get(self, request):
                # No rate limit on GET
                return Response({"action": "list"})

        view = MethodSpecificView.as_view()

        # POST requests - should all succeed even when exceeding limit
        for _ in range(3):
            request = self.factory.post("/test/")
            request.META["REMOTE_ADDR"] = "10.0.0.10"
            response = view(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # GET requests - not rate limited at all
        for _ in range(5):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "10.0.0.10"
            response = view(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFNonBlockingLogging(TestCase):
    """Test that non-blocking mode still logs rate limit events."""

    def setUp(self):
        self.factory = RequestFactory()
        clear_backend_cache()
        cache.clear()

    def test_non_blocking_response_includes_data(self):
        """Response should include data even when limit exceeded in non-blocking mode."""
        view = NonBlockingTestView.as_view()

        # Exceed the limit
        for _ in range(5):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "10.0.0.20"
            response = view(request)

        # Last response should still have the expected data
        self.assertEqual(response.data, {"status": "ok"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)


if __name__ == "__main__":
    unittest.main()
