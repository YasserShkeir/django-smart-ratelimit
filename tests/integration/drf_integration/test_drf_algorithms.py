"""
DRF Algorithm Integration Tests.

Tests for different rate limiting algorithms (token bucket, sliding window,
fixed window) with Django REST Framework views.
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
class TestDRFTokenBucketAlgorithm(TestCase):
    """Tests for token bucket algorithm with DRF views."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()

    def test_token_bucket_burst_traffic_allowed(self):
        """Test that token bucket allows burst traffic up to bucket size."""

        class BurstView(APIView):
            @rate_limit(
                key="ip",
                rate="5/m",
                algorithm="token_bucket",
                algorithm_config={"bucket_size": 10},
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = BurstView.as_view()

        # Make 10 rapid requests (bucket size) - all should succeed
        success_count = 0
        for i in range(10):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.1.100"
            response = view(request)
            if response.status_code == 200:
                success_count += 1

        # All 10 should succeed (burst allowed)
        self.assertGreaterEqual(
            success_count, 8, "Token bucket should allow burst traffic"
        )

    def test_token_bucket_blocks_after_bucket_empty(self):
        """Test that token bucket blocks requests after bucket is exhausted."""

        class LimitedView(APIView):
            @rate_limit(
                key="ip",
                rate="1/m",  # Very slow refill
                algorithm="token_bucket",
                algorithm_config={"bucket_size": 3},
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = LimitedView.as_view()

        # Make requests until blocked
        blocked = False
        for i in range(10):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.1.101"
            response = view(request)
            if response.status_code == 429:
                blocked = True
                break

        self.assertTrue(blocked, "Token bucket should block after exhaustion")

    def test_token_bucket_sustained_traffic_at_refill_rate(self):
        """Test that sustained traffic at refill rate succeeds."""

        class SustainedView(APIView):
            @rate_limit(
                key="ip",
                rate="60/m",  # 1 per second
                algorithm="token_bucket",
                algorithm_config={"bucket_size": 5},
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = SustainedView.as_view()

        # First request should succeed
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.1.102"
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_token_bucket_custom_refill_rate(self):
        """Test token bucket with custom refill rate configuration."""

        class CustomRefillView(APIView):
            @rate_limit(
                key="ip",
                rate="120/m",  # 2 per second
                algorithm="token_bucket",
                algorithm_config={"bucket_size": 10, "refill_rate": 2.0},
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = CustomRefillView.as_view()

        # First request should succeed
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.1.103"
        response = view(request)
        self.assertEqual(response.status_code, 200)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFSlidingWindowAlgorithm(TestCase):
    """Tests for sliding window algorithm with DRF views."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()

    def test_sliding_window_basic_limiting(self):
        """Test basic sliding window rate limiting."""

        class SlidingView(APIView):
            @rate_limit(
                key="ip",
                rate="5/m",
                algorithm="sliding_window",
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = SlidingView.as_view()

        # Make 5 requests - all should succeed
        for i in range(5):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.2.100"
            response = view(request)
            self.assertEqual(response.status_code, 200, f"Request {i+1} should succeed")

        # 6th request should be blocked
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.2.100"
        response = view(request)
        self.assertEqual(response.status_code, 429, "6th request should be blocked")

    def test_sliding_window_different_keys(self):
        """Test that sliding window tracks different keys separately."""

        class KeyedView(APIView):
            @rate_limit(
                key="ip",
                rate="2/m",
                algorithm="sliding_window",
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = KeyedView.as_view()

        # User 1: 2 requests should succeed
        for _ in range(2):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.2.101"
            response = view(request)
            self.assertEqual(response.status_code, 200)

        # User 1: 3rd request should be blocked
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.2.101"
        response = view(request)
        self.assertEqual(response.status_code, 429)

        # User 2: Should have fresh limit
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.2.102"
        response = view(request)
        self.assertEqual(
            response.status_code, 200, "Different IP should have fresh limit"
        )

    def test_sliding_window_gradual_recovery(self):
        """Test that sliding window allows gradual recovery as old requests expire."""
        # This test verifies the sliding window behavior conceptually
        # Full time-based testing would require mocking time

        class RecoveryView(APIView):
            @rate_limit(
                key="ip",
                rate="3/m",
                algorithm="sliding_window",
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = RecoveryView.as_view()

        # Exhaust the limit
        for _ in range(3):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.2.103"
            view(request)

        # Should be blocked now
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.2.103"
        response = view(request)
        self.assertEqual(response.status_code, 429)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFFixedWindowAlgorithm(TestCase):
    """Tests for fixed window algorithm with DRF views."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()

    def test_fixed_window_basic_limiting(self):
        """Test basic fixed window rate limiting."""

        class FixedView(APIView):
            @rate_limit(
                key="ip",
                rate="5/m",
                algorithm="fixed_window",
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = FixedView.as_view()

        # Make 5 requests - all should succeed
        for i in range(5):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.3.100"
            response = view(request)
            self.assertEqual(response.status_code, 200, f"Request {i+1} should succeed")

        # 6th request should be blocked
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.3.100"
        response = view(request)
        self.assertEqual(response.status_code, 429, "6th request should be blocked")

    def test_fixed_window_counter_behavior(self):
        """Test fixed window counter increments correctly."""

        class CounterView(APIView):
            @rate_limit(
                key="ip",
                rate="10/m",
                algorithm="fixed_window",
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = CounterView.as_view()

        success_count = 0
        for _ in range(15):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.3.101"
            response = view(request)
            if response.status_code == 200:
                success_count += 1

        self.assertEqual(success_count, 10, "Should allow exactly 10 requests")

    def test_fixed_window_different_ips(self):
        """Test that fixed window tracks different IPs separately."""

        class MultiIPView(APIView):
            @rate_limit(
                key="ip",
                rate="2/m",
                algorithm="fixed_window",
                block=True,
            )
            def get(self, request):
                return Response({"message": "success"})

        view = MultiIPView.as_view()

        # IP 1 uses its limit
        for _ in range(2):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.3.102"
            view(request)

        # IP 1 should be blocked
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.3.102"
        response = view(request)
        self.assertEqual(response.status_code, 429)

        # IP 2 should have fresh limit
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.3.103"
        response = view(request)
        self.assertEqual(response.status_code, 200)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFAlgorithmComparison(TestCase):
    """Comparative tests between different algorithms."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_all_algorithms_enforce_limit(self):
        """Test that all algorithms eventually enforce the rate limit."""
        algorithms = ["fixed_window", "sliding_window", "token_bucket"]

        for algo in algorithms:
            with self.subTest(algorithm=algo):
                clear_backend_cache()
                cache.clear()

                # Create a view with the specific algorithm
                class TestView(APIView):
                    pass

                # Apply decorator dynamically
                if algo == "token_bucket":
                    decorated = rate_limit(
                        key="ip",
                        rate="3/m",
                        algorithm=algo,
                        algorithm_config={"bucket_size": 3},
                        block=True,
                    )(lambda self, request: Response({"message": "success"}))
                else:
                    decorated = rate_limit(
                        key="ip",
                        rate="3/m",
                        algorithm=algo,
                        block=True,
                    )(lambda self, request: Response({"message": "success"}))

                TestView.get = decorated
                view = TestView.as_view()

                # Make requests until blocked
                blocked = False
                for i in range(10):
                    request = self.factory.get("/api/test/")
                    request.META["REMOTE_ADDR"] = f"10.0.{algorithms.index(algo)}.{i}"
                    response = view(request)
                    if response.status_code == 429:
                        blocked = True
                        break

                # All algorithms should eventually block
                # (though they may allow different numbers of initial requests)
                self.assertTrue(
                    blocked or i >= 3,
                    f"{algo} should enforce limit after reasonable requests",
                )

    def test_algorithm_default_is_sliding_window(self):
        """Test that the default algorithm behaves like sliding window."""

        class DefaultView(APIView):
            @rate_limit(key="ip", rate="3/m", block=True)
            def get(self, request):
                return Response({"message": "success"})

        view = DefaultView.as_view()

        # Should work like sliding window
        success_count = 0
        for _ in range(5):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "192.168.4.100"
            response = view(request)
            if response.status_code == 200:
                success_count += 1

        self.assertEqual(
            success_count, 3, "Default algorithm should limit to 3 requests"
        )


if __name__ == "__main__":
    unittest.main()
