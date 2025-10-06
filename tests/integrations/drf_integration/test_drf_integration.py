"""
Django REST Framework Integration Tests

This module contains focused tests for DRF integration with
Django Smart Ratelimit. These tests verify that rate limiting works
correctly with DRF components using the @rate_limit decorator.
"""

import unittest

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

try:
    from rest_framework import serializers, status, viewsets
    from rest_framework.response import Response
    from rest_framework.test import APIClient, APITestCase
    from rest_framework.views import APIView

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    # Fallback classes when DRF is not available
    APITestCase = TestCase
    APIClient = None
    APIView = None
    Response = None
    status = None
    serializers = None
    viewsets = None

from django_smart_ratelimit import rate_limit
from tests.utils import create_test_staff_user, create_test_user


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(
    INSTALLED_APPS=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django_smart_ratelimit",
        "rest_framework",
    ],
    REST_FRAMEWORK={
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.AllowAny",
        ],
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.AnonRateThrottle",
            "rest_framework.throttling.UserRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {"anon": "100/hour", "user": "1000/hour"},
    },
    RATELIMIT_BACKEND="django_smart_ratelimit.backends.memory.MemoryBackend",
    RATELIMIT_BACKEND_OPTIONS={
        "MAX_ENTRIES": 1000,
        "CLEANUP_INTERVAL": 300,
    },
)
class DRFRateLimitingTestCase(APITestCase):
    """
    Test cases for DRF rate limiting integration.

    These tests verify Django Smart Ratelimit works correctly
    with key DRF components using the @rate_limit decorator.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.user = create_test_user()
        self.staff_user = create_test_staff_user(password="staffpass123")
        self.client = APIClient()
        cache.clear()

    def test_apiview_rate_limiting(self):
        """Test APIView with rate_limit enforces allow and block sequence."""
        from unittest.mock import Mock, patch

        class TestAPIView(APIView):
            permission_classes = []  # Allow unauthenticated access

            @rate_limit(key="ip", rate="2/m", block=True)
            def get(self, request):
                return Response({"message": "success"})

            @rate_limit(key="user", rate="2/m", block=True)
            def post(self, request):
                return Response({"message": "created"}, status=status.HTTP_201_CREATED)

        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get_backend:
            mock_backend = Mock()
            mock_backend.incr.side_effect = [1, 2, 3]  # exceed limit of 2 on 3rd call
            mock_get_backend.return_value = mock_backend

            view = TestAPIView.as_view()

            request = self.factory.get("/api/test/")
            request.user = self.user

            self.assertEqual(view(request).status_code, 200)
            self.assertEqual(view(request).status_code, 200)
            self.assertEqual(view(request).status_code, 429)

    def test_viewset_rate_limiting(self):
        """Test ViewSet actions with rate_limit enforce limits."""
        from unittest.mock import Mock, patch

        class TestViewSet(viewsets.ViewSet):
            @rate_limit(key="ip", rate="2/m", block=True)
            def list(self, request, *args, **kwargs):
                return Response([{"id": 1, "name": "Test"}])

            @rate_limit(key="user", rate="2/m", block=True)
            def create(self, request, *args, **kwargs):
                return Response(
                    {"id": 999, "name": "Created"}, status=status.HTTP_201_CREATED
                )

            @rate_limit(key="ip", rate="1/m", block=True)
            def retrieve(self, request, *args, **kwargs):
                return Response({"id": 1, "name": "Retrieved Item"})

        # list()
        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get_backend:
            mock_backend = Mock()
            mock_backend.incr.side_effect = [1, 2, 3]
            mock_get_backend.return_value = mock_backend

            vs = TestViewSet()
            req = self.factory.get("/api/test/")
            req.user = self.user
            self.assertEqual(vs.list(req).status_code, 200)
            self.assertEqual(vs.list(req).status_code, 200)
            self.assertEqual(vs.list(req).status_code, 429)

        # retrieve()
        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get_backend:
            mock_backend = Mock()
            mock_backend.incr.side_effect = [1, 2]  # limit=1
            mock_get_backend.return_value = mock_backend

            vs = TestViewSet()
            req = self.factory.get("/api/test/1/")
            req.user = self.user
            self.assertEqual(vs.retrieve(req, pk=1).status_code, 200)
            self.assertEqual(vs.retrieve(req, pk=1).status_code, 429)

    def test_custom_key_functions(self):
        """Custom key function works with DRF APIView."""
        from unittest.mock import Mock, patch

        def user_or_ip_key(request, *args, **kwargs):
            if request.user.is_authenticated:
                return f"user:{request.user.id}"
            return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

        class TestView(APIView):
            @rate_limit(key=user_or_ip_key, rate="2/m", block=True)
            def get(self, request):
                return Response({"message": "success"})

        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get_backend:
            mock_backend = Mock()
            mock_backend.incr.side_effect = [1, 2, 3]
            mock_get_backend.return_value = mock_backend

            view = TestView.as_view()

            req = self.factory.get("/api/test/")
            req.user = self.user
            self.assertEqual(view(req).status_code, 200)
            self.assertEqual(view(req).status_code, 200)
            self.assertEqual(view(req).status_code, 429)

        # Anonymous user uses IP key (fresh counter)
        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get_backend:
            mock_backend = Mock()
            mock_backend.incr.return_value = 1
            mock_get_backend.return_value = mock_backend

            anon_req = self.factory.get("/api/test/")
            anon_req.user = Mock()
            anon_req.user.is_authenticated = False
            anon_req.META["REMOTE_ADDR"] = "127.0.0.1"
            self.assertEqual(view(anon_req).status_code, 200)

    def test_method_specific_rate_limiting(self):
        """Different HTTP methods may have different rate limits via decorator."""

        class TestView(APIView):
            permission_classes = []

            @rate_limit(key="user", rate="10/m")
            def get(self, _request):
                return Response({"message": "get success"})

            @rate_limit(key="user", rate="5/m")
            def post(self, _request):
                return Response(
                    {"message": "post success"}, status=status.HTTP_201_CREATED
                )

            @rate_limit(key="user", rate="3/m")
            def put(self, _request):
                return Response({"message": "put success"})

        view = TestView.as_view()

        req = self.factory.get("/api/test/")
        req.user = self.user
        self.assertEqual(view(req).status_code, 200)

        req = self.factory.post(
            "/api/test/", {"data": "test"}, content_type="application/json"
        )
        req.user = self.user
        req._dont_enforce_csrf_checks = True
        self.assertEqual(view(req).status_code, 201)

        req = self.factory.put(
            "/api/test/", {"data": "test"}, content_type="application/json"
        )
        req.user = self.user
        req._dont_enforce_csrf_checks = True
        self.assertEqual(view(req).status_code, 200)

    def test_serializer_validation_rate_limiting(self):
        """Serializer-level validation can read request from context and be rate limited."""

        class TestSerializer(serializers.Serializer):
            title = serializers.CharField(max_length=100)
            content = serializers.CharField(max_length=500)

            def validate_title(self, value):
                request = self.context.get("request")
                if request:
                    user_id = (
                        request.user.id if request.user.is_authenticated else "anon"
                    )
                    validation_key = f"validation:{user_id}"
                    current_count = cache.get(validation_key, 0)

                    if current_count >= 5:
                        raise serializers.ValidationError(
                            "Too many validation requests"
                        )

                    cache.set(validation_key, current_count + 1, 60)

                if len(value) < 3:
                    raise serializers.ValidationError("Title too short")
                return value

        request = self.factory.post("/api/test/")
        request.user = self.user

        for _ in range(5):
            serializer = TestSerializer(
                data={"title": "Test Title", "content": "Content"},
                context={"request": request},
            )
            self.assertTrue(serializer.is_valid())

        serializer = TestSerializer(
            data={"title": "Test Title", "content": "Content"},
            context={"request": request},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("title", serializer.errors)


if __name__ == "__main__":
    unittest.main()
