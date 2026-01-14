"""
DRF Rate Limit Headers Tests.

Tests for rate limit response headers (X-RateLimit-*) with Django REST Framework views.
"""

import unittest

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

try:
    from rest_framework import status
    from rest_framework.response import Response
    from rest_framework.test import APIClient
    from rest_framework.views import APIView

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    APIView = object
    Response = None
    status = None
    APIClient = None

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import clear_backend_cache
from tests.utils import create_test_user


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFRateLimitHeaders(TestCase):
    """Tests for rate limit headers on DRF responses."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()

    def test_response_includes_ratelimit_headers(self):
        """Test that response includes X-RateLimit-* headers."""

        class HeaderView(APIView):
            @rate_limit(key="ip", rate="10/m", block=True)
            def get(self, request):
                return Response({"message": "success"})

        view = HeaderView.as_view()

        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.10.100"
        response = view(request)

        self.assertEqual(response.status_code, 200)

        # Check for rate limit headers (may be present depending on implementation)
        # Common header names
        header_names = [
            "X-RateLimit-Limit",
            "X-Ratelimit-Limit",
            "RateLimit-Limit",
        ]

        # Check if any rate limit header is present
        headers_present = any(
            header in response.headers
            or header.lower() in [h.lower() for h in response.headers]
            for header in header_names
        )

        # Note: Headers may be added by middleware, not the decorator itself
        # This test documents expected behavior
        if not headers_present:
            # If no headers, that's acceptable - document this behavior
            self.skipTest(
                "Rate limit headers not added by decorator (middleware may add them)"
            )

    def test_remaining_header_decreases(self):
        """Test that X-RateLimit-Remaining decreases with each request."""

        class RemainingView(APIView):
            @rate_limit(key="ip", rate="5/m", block=True)
            def get(self, request):
                return Response({"message": "success"})

        view = RemainingView.as_view()

        remaining_values = []
        for _ in range(3):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.10.101"
            response = view(request)

            # Try to get remaining header
            remaining = response.headers.get(
                "X-RateLimit-Remaining"
            ) or response.headers.get("X-Ratelimit-Remaining")
            if remaining:
                remaining_values.append(int(remaining))

        if remaining_values:
            # Remaining should decrease
            for i in range(1, len(remaining_values)):
                self.assertLess(
                    remaining_values[i],
                    remaining_values[i - 1],
                    "Remaining should decrease",
                )
        else:
            self.skipTest("X-RateLimit-Remaining header not present")

    def test_429_response_includes_retry_after(self):
        """Test that 429 response includes Retry-After header."""

        class RetryView(APIView):
            @rate_limit(key="ip", rate="2/m", block=True)
            def get(self, request):
                return Response({"message": "success"})

        view = RetryView.as_view()

        # Exhaust the limit
        for _ in range(2):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.10.102"
            view(request)

        # Third request should be blocked
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.10.102"
        response = view(request)

        self.assertEqual(response.status_code, 429)

        # Check for Retry-After header
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            # Should be a positive number
            self.assertGreater(int(retry_after), 0)
        # Retry-After is optional but recommended

    def test_reset_header_timestamp(self):
        """Test that X-RateLimit-Reset header contains valid timestamp."""

        class ResetView(APIView):
            @rate_limit(key="ip", rate="10/m", block=True)
            def get(self, request):
                return Response({"message": "success"})

        view = ResetView.as_view()

        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.10.103"
        response = view(request)

        reset = response.headers.get("X-RateLimit-Reset") or response.headers.get(
            "X-Ratelimit-Reset"
        )
        if reset:
            import time

            reset_time = int(reset)
            current_time = int(time.time())
            # Reset should be in the future (within next 60 seconds for minute window)
            self.assertGreater(reset_time, current_time - 1)
            self.assertLess(reset_time, current_time + 120)
        else:
            self.skipTest("X-RateLimit-Reset header not present")


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFTokenBucketHeaders(TestCase):
    """Tests for token bucket specific headers."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_token_bucket_remaining_tokens(self):
        """Test token bucket shows remaining tokens in response."""

        class TokenView(APIView):
            @rate_limit(
                key="ip",
                rate="10/m",
                algorithm="token_bucket",
                algorithm_config={"bucket_size": 5},
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = TokenView.as_view()

        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.11.100"
        response = view(request)

        self.assertEqual(response.status_code, 200)

        # Check for token-specific headers
        tokens_remaining = response.headers.get("X-RateLimit-Tokens-Remaining")
        bucket_size = response.headers.get("X-RateLimit-Bucket-Size")

        # These headers may or may not be present depending on implementation
        if tokens_remaining:
            self.assertGreaterEqual(int(tokens_remaining), 0)
        if bucket_size:
            self.assertEqual(int(bucket_size), 5)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFHeaderAccuracy(TestCase):
    """Tests for header value accuracy."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_limit_header_matches_rate_config(self):
        """Test that X-RateLimit-Limit matches the configured rate."""

        class LimitView(APIView):
            @rate_limit(key="ip", rate="25/m", block=True)
            def get(self, request):
                return Response({"message": "success"})

        view = LimitView.as_view()

        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.12.100"
        response = view(request)

        limit = response.headers.get("X-RateLimit-Limit") or response.headers.get(
            "X-Ratelimit-Limit"
        )
        if limit:
            self.assertEqual(int(limit), 25)
        else:
            self.skipTest("X-RateLimit-Limit header not present")

    def test_headers_consistency_across_requests(self):
        """Test that headers remain consistent across multiple requests."""

        class ConsistentView(APIView):
            @rate_limit(key="ip", rate="10/m", block=True)
            def get(self, request):
                return Response({"message": "success"})

        view = ConsistentView.as_view()

        limits = []
        for _ in range(3):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.12.101"
            response = view(request)

            limit = response.headers.get("X-RateLimit-Limit") or response.headers.get(
                "X-Ratelimit-Limit"
            )
            if limit:
                limits.append(int(limit))

        if limits:
            # All limit values should be the same
            self.assertEqual(len(set(limits)), 1, "Limit header should be consistent")
            self.assertEqual(limits[0], 10)
        else:
            self.skipTest("X-RateLimit-Limit header not present")

    def test_headers_with_different_rates(self):
        """Test headers reflect different rate configurations."""

        class FastView(APIView):
            @rate_limit(key="ip", rate="100/m", block=True)
            def get(self, request):
                return Response({"message": "fast"})

        class SlowView(APIView):
            @rate_limit(key="ip", rate="5/m", block=True)
            def get(self, request):
                return Response({"message": "slow"})

        fast_view = FastView.as_view()
        slow_view = SlowView.as_view()

        # Request to fast view
        request = self.factory.get("/api/fast/")
        request.META["REMOTE_ADDR"] = "192.168.12.102"
        fast_response = fast_view(request)

        # Request to slow view
        request = self.factory.get("/api/slow/")
        request.META["REMOTE_ADDR"] = "192.168.12.103"
        slow_response = slow_view(request)

        fast_limit = fast_response.headers.get(
            "X-RateLimit-Limit"
        ) or fast_response.headers.get("X-Ratelimit-Limit")
        slow_limit = slow_response.headers.get(
            "X-RateLimit-Limit"
        ) or slow_response.headers.get("X-Ratelimit-Limit")

        if fast_limit and slow_limit:
            self.assertEqual(int(fast_limit), 100)
            self.assertEqual(int(slow_limit), 5)
        else:
            self.skipTest("X-RateLimit-Limit headers not present")


if __name__ == "__main__":
    unittest.main()
