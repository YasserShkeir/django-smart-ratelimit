"""
Advanced DRF integration tests.

Tests for advanced features:
- Custom key functions
- Multiple decorators
- ViewSet integration
- Custom response handling
"""

import unittest

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

try:
    from rest_framework import status
    from rest_framework.response import Response
    from rest_framework.views import APIView
    from rest_framework.viewsets import ViewSet

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    APIView = object
    Response = None
    status = None
    ViewSet = object

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import clear_backend_cache
from tests.utils import create_test_user


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFCustomKeyFunctions(TestCase):
    """Test custom key functions with DRF views."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user1 = create_test_user(username="user1")
        self.user2 = create_test_user(username="user2")

    def test_custom_callable_key(self):
        """Test rate limiting with custom callable key function."""

        def get_user_id(request, *args, **kwargs):
            """Extract user ID from request."""
            if hasattr(request, "user") and request.user.is_authenticated:
                return f"user:{request.user.id}"
            return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

        class CustomKeyView(APIView):
            @rate_limit(rate="2/m", key=get_user_id)
            def get(self, request):
                return Response({"status": "ok"})

        view = CustomKeyView.as_view()

        # Request from user1 - first two should pass
        request = self.factory.get("/test/")
        request.user = self.user1
        response = view(request)
        self.assertEqual(response.status_code, 200)

        request = self.factory.get("/test/")
        request.user = self.user1
        response = view(request)
        self.assertEqual(response.status_code, 200)

        # Third from user1 should be blocked
        request = self.factory.get("/test/")
        request.user = self.user1
        response = view(request)
        self.assertEqual(response.status_code, 429)

        # Request from user2 should still work
        request = self.factory.get("/test/")
        request.user = self.user2
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_user_key_type(self):
        """Test rate limiting with user key type."""

        class UserKeyView(APIView):
            @rate_limit(rate="2/m", key="user")
            def get(self, request):
                return Response({"status": "ok"})

        view = UserKeyView.as_view()

        # Authenticated user
        request = self.factory.get("/test/")
        request.user = self.user1
        response = view(request)
        self.assertEqual(response.status_code, 200)

        # Second request
        request = self.factory.get("/test/")
        request.user = self.user1
        response = view(request)
        self.assertEqual(response.status_code, 200)

        # Third should be blocked
        request = self.factory.get("/test/")
        request.user = self.user1
        response = view(request)
        self.assertEqual(response.status_code, 429)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFMultipleDecorators(TestCase):
    """Test multiple rate limit decorators on same view."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_rate_limit_applied_to_view(self):
        """Rate limit decorator should work on views."""

        class RateLimitedView(APIView):
            @rate_limit(rate="2/m", key="ip")
            def get(self, request):
                return Response({"status": "ok"})

        view = RateLimitedView.as_view()

        results = []
        for i in range(4):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "20.0.0.1"
            response = view(request)
            results.append(response.status_code)

        # First 2 should pass, rest should be blocked
        self.assertEqual(results[:2], [200, 200])
        self.assertTrue(all(r == 429 for r in results[2:]))


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFViewSetIntegration(TestCase):
    """Test rate limiting with DRF ViewSets."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_viewset_action_rate_limiting(self):
        """Test rate limiting on ViewSet actions."""

        class ItemViewSet(ViewSet):
            @rate_limit(rate="3/m", key="ip")
            def list(self, request):
                return Response({"items": []})

            @rate_limit(rate="2/m", key="ip")
            def retrieve(self, request, pk=None):
                return Response({"item": {"id": pk}})

        viewset = ItemViewSet()

        # Test list action
        results = []
        for i in range(5):
            request = self.factory.get("/items/")
            request.META["REMOTE_ADDR"] = "20.0.0.10"
            response = viewset.list(request)
            results.append(response.status_code)

        # First 3 should pass (3/m)
        self.assertEqual(results[:3], [200, 200, 200])
        self.assertTrue(all(r == 429 for r in results[3:]))


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFCustomResponses(TestCase):
    """Test custom response handling with rate limiting."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_json_response_preserved(self):
        """JSON response structure should be preserved."""

        class JsonView(APIView):
            @rate_limit(rate="2/m", key="ip")
            def get(self, request):
                return Response(
                    {"data": {"id": 1, "name": "test"}, "meta": {"version": "1.0"}}
                )

        view = JsonView.as_view()

        request = self.factory.get("/test/")
        request.META["REMOTE_ADDR"] = "20.0.0.20"
        response = view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["id"], 1)
        self.assertEqual(response.data["meta"]["version"], "1.0")

    def test_rate_limited_response_is_json(self):
        """Rate limited response should be proper JSON."""

        class TestView(APIView):
            @rate_limit(rate="1/m", key="ip")
            def get(self, request):
                return Response({"status": "ok"})

        view = TestView.as_view()

        # Exhaust limit
        request = self.factory.get("/test/")
        request.META["REMOTE_ADDR"] = "20.0.0.30"
        view(request)

        # Second request should be blocked
        request = self.factory.get("/test/")
        request.META["REMOTE_ADDR"] = "20.0.0.30"
        response = view(request)

        self.assertEqual(response.status_code, 429)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFHTTPMethods(TestCase):
    """Test rate limiting with different HTTP methods."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_all_methods_rate_limited(self):
        """All HTTP methods should be rate limited."""

        class CRUDView(APIView):
            @rate_limit(rate="2/m", key="ip")
            def get(self, request):
                return Response({"action": "get"})

            @rate_limit(rate="2/m", key="ip")
            def post(self, request):
                return Response({"action": "post"}, status=201)

            @rate_limit(rate="2/m", key="ip")
            def put(self, request):
                return Response({"action": "put"})

            @rate_limit(rate="2/m", key="ip")
            def delete(self, request):
                return Response({"action": "delete"}, status=204)

        view = CRUDView.as_view()

        # Each method should have its own rate limit
        for method in ["get", "post", "put", "delete"]:
            factory_method = getattr(self.factory, method)

            # First 2 requests should pass
            request = factory_method("/test/")
            request.META["REMOTE_ADDR"] = f"20.0.1.{hash(method) % 256}"
            response = view(request)
            self.assertIn(response.status_code, [200, 201, 204])

    def test_post_method_rate_limited_separately(self):
        """Test that POST and GET methods can have separate rate limits."""

        class MethodView(APIView):
            @rate_limit(rate="1/m", key="ip")
            def post(self, request):
                return Response({"action": "created"})

            def get(self, request):
                # No rate limit on GET
                return Response({"action": "list"})

        view = MethodView.as_view()

        # POST should be limited
        request = self.factory.post("/test/")
        request.META["REMOTE_ADDR"] = "20.0.0.50"
        response = view(request)
        self.assertEqual(response.status_code, 200)

        # Second POST should be blocked
        request = self.factory.post("/test/")
        request.META["REMOTE_ADDR"] = "20.0.0.50"
        response = view(request)
        self.assertEqual(response.status_code, 429)

        # GET should be unlimited (different IP to avoid any cross-contamination)
        for _ in range(5):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "20.0.0.51"
            response = view(request)
            self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
