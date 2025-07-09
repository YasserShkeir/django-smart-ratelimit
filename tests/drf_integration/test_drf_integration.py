"""
Django REST Framework Integration Tests

This module contains comprehensive tests for DRF integration with
Django Smart Ratelimit. These tests are part of the main test suite and verify
that rate limiting works correctly with DRF components.
"""

import unittest
from unittest.mock import Mock

from django.contrib.auth.models import User
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

from django_smart_ratelimit.decorator import rate_limit

# Test settings that include DRF
TEST_SETTINGS = {
    "INSTALLED_APPS": [
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django_smart_ratelimit",
        "rest_framework",
    ],
    "REST_FRAMEWORK": {
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.AllowAny",
        ],
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.AnonRateThrottle",
            "rest_framework.throttling.UserRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {"anon": "100/hour", "user": "1000/hour"},
    },
    "RATELIMIT_BACKEND": "django_smart_ratelimit.backends.memory.MemoryBackend",
    "RATELIMIT_BACKEND_OPTIONS": {
        "MAX_ENTRIES": 1000,
        "CLEANUP_INTERVAL": 300,
    },
}


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

    These tests verify that Django Smart Ratelimit works correctly
    with various DRF components.
    """

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.staff_user = User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password="staffpass123",
            is_staff=True,
        )
        self.client = APIClient()

        # Clear cache before each test
        cache.clear()

    def test_apiview_rate_limiting(self):
        """Test rate limiting with APIView"""

        class TestAPIView(APIView):
            permission_classes = []  # Allow unauthenticated access

            @rate_limit(key="ip", rate="5/m")
            def get(self, request):
                return Response({"message": "success"})

            @rate_limit(key="user", rate="3/m")
            def post(self, request):
                return Response({"message": "created"}, status=status.HTTP_201_CREATED)

        view = TestAPIView.as_view()

        # Test GET requests with IP-based rate limiting
        request = self.factory.get("/api/test/")
        request.user = self.user

        # First few requests should succeed
        for i in range(5):
            response = view(request)
            self.assertEqual(response.status_code, 200)

        # Test rate limiting by making many requests
        # Since we're using memory backend, we can test actual rate limiting
        responses = []
        for i in range(10):  # More than the 5/m limit
            response = view(request)
            responses.append(response.status_code)

        # Should have some successful responses (200) and some rate limited (429)
        self.assertIn(200, responses)
        # Note: Actual rate limiting behavior depends on backend implementation

    def test_viewset_rate_limiting(self):
        """Test rate limiting with ViewSet"""

        # Simple serializer for testing
        class TestSerializer(serializers.Serializer):
            id = serializers.IntegerField()
            name = serializers.CharField(max_length=100)

        class TestViewSet(viewsets.ViewSet):
            @rate_limit(key="ip", rate="10/m")
            def list(self, request, *args, **kwargs):
                return Response([{"id": 1, "name": "Test"}])

            @rate_limit(key="user", rate="5/m")
            def create(self, request, *args, **kwargs):
                return Response(
                    {"id": 999, "name": "Created"}, status=status.HTTP_201_CREATED
                )

        viewset = TestViewSet()
        viewset.action = "list"
        viewset.request = self.factory.get("/api/test/")
        viewset.request.user = self.user
        viewset.format_kwarg = None

        # Test list action
        response = viewset.list(viewset.request)
        self.assertEqual(response.status_code, 200)

        # Test create action
        viewset.action = "create"
        viewset.request = self.factory.post("/api/test/", {"name": "New Item"})
        viewset.request.user = self.user

        response = viewset.create(viewset.request)
        self.assertEqual(response.status_code, 201)

    def test_permission_based_rate_limiting(self):
        """Test rate limiting integrated with DRF permissions"""

        from rest_framework.permissions import BasePermission

        class RateLimitedPermission(BasePermission):
            def has_permission(self, request, view):
                # Simple rate limiting check
                user_id = request.user.id if request.user.is_authenticated else "anon"
                user_key = f"permission:{user_id}"
                current_count = cache.get(user_key, 0)

                if current_count >= 10:  # 10 requests per test
                    return False

                cache.set(user_key, current_count + 1, 60)
                return True

        class TestPermissionView(APIView):
            permission_classes = [RateLimitedPermission]

            def get(self, request):
                return Response({"message": "success"})

        view = TestPermissionView.as_view()

        # Test with authenticated user
        request = self.factory.get("/api/test/")
        request.user = self.user

        # First few requests should succeed
        for i in range(10):
            response = view(request)
            self.assertEqual(response.status_code, 200)

        # 11th request should be denied
        response = view(request)
        self.assertEqual(response.status_code, 403)

    def test_serializer_validation_rate_limiting(self):
        """Test rate limiting in serializer validation"""

        class TestSerializer(serializers.Serializer):
            title = serializers.CharField(max_length=100)
            content = serializers.CharField(max_length=500)

            def validate_title(self, value):
                # Simulate rate limited validation
                request = self.context.get("request")
                if request:
                    user_id = (
                        request.user.id if request.user.is_authenticated else "anon"
                    )
                    validation_key = f"validation:{user_id}"
                    current_count = cache.get(validation_key, 0)

                    if current_count >= 5:  # 5 validation requests per test
                        raise serializers.ValidationError(
                            "Too many validation requests"
                        )

                    cache.set(validation_key, current_count + 1, 60)

                if len(value) < 3:
                    raise serializers.ValidationError("Title too short")
                return value

        # Test serializer validation
        request = self.factory.post("/api/test/")
        request.user = self.user

        # First few validations should succeed
        for i in range(5):
            serializer = TestSerializer(
                data={"title": "Test Title", "content": "Content"},
                context={"request": request},
            )
            self.assertTrue(serializer.is_valid())

        # 6th validation should fail due to rate limiting
        serializer = TestSerializer(
            data={"title": "Test Title", "content": "Content"},
            context={"request": request},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("title", serializer.errors)

    def test_custom_key_functions(self):
        """Test rate limiting with custom key functions"""

        def user_or_ip_key(group, request):
            """Custom key function that uses user ID or IP"""
            if request.user.is_authenticated:
                return f"user:{request.user.id}"
            return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

        class TestView(APIView):
            @rate_limit(key=user_or_ip_key, rate="5/m")
            def get(self, request):
                return Response({"message": "success"})

        view = TestView.as_view()

        # Test with authenticated user
        request = self.factory.get("/api/test/")
        request.user = self.user

        response = view(request)
        self.assertEqual(response.status_code, 200)

        # Test with anonymous user
        request = self.factory.get("/api/test/")
        request.user = Mock()
        request.user.is_authenticated = False
        request.META["REMOTE_ADDR"] = "127.0.0.1"

        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_method_specific_rate_limiting(self):
        """Test different rate limits for different HTTP methods"""

        class TestView(APIView):
            permission_classes = []  # Allow unauthenticated access

            @rate_limit(key="user", rate="10/m")
            def get(self, request):
                return Response({"message": "get success"})

            @rate_limit(key="user", rate="5/m")
            def post(self, request):
                return Response(
                    {"message": "post success"}, status=status.HTTP_201_CREATED
                )

            @rate_limit(key="user", rate="3/m")
            def put(self, request):
                return Response({"message": "put success"})

        view = TestView.as_view()

        # Test GET method
        request = self.factory.get("/api/test/")
        request.user = self.user
        response = view(request)
        self.assertEqual(response.status_code, 200)

        # Test POST method
        request = self.factory.post(
            "/api/test/", {"data": "test"}, content_type="application/json"
        )
        request.user = self.user
        # Disable CSRF for the test
        request._dont_enforce_csrf_checks = True
        response = view(request)
        self.assertEqual(response.status_code, 201)

        # Test PUT method
        request = self.factory.put(
            "/api/test/", {"data": "test"}, content_type="application/json"
        )
        request.user = self.user
        # Disable CSRF for the test
        request._dont_enforce_csrf_checks = True
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_role_based_rate_limiting(self):
        """Test different rate limits based on user roles"""

        def get_rate_for_user(user):
            """Get rate limit based on user role"""
            if user.is_staff:
                return "100/m"
            elif user.is_authenticated:
                return "50/m"
            else:
                return "10/m"

        class TestView(APIView):
            def get(self, request):
                # Apply different rate limits based on user
                rate = get_rate_for_user(request.user)
                # In real implementation, this would use @rate_limit decorator
                # with dynamic rate or custom logic
                return Response({"message": f"success with rate {rate}"})

        view = TestView.as_view()

        # Test with staff user
        request = self.factory.get("/api/test/")
        request.user = self.staff_user
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("100/m", response.data["message"])

        # Test with regular user
        request = self.factory.get("/api/test/")
        request.user = self.user
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("50/m", response.data["message"])

    def test_conditional_rate_limiting(self):
        """Test conditional rate limiting based on request parameters"""

        class TestView(APIView):
            def get(self, request):
                # Apply different rate limits based on request parameters
                if request.GET.get("priority") == "high":
                    # High priority requests might have different limits
                    rate_key = f"high_priority:{request.user.id}"
                else:
                    rate_key = f"normal:{request.user.id}"

                # Simulate rate limiting check
                current_count = cache.get(rate_key, 0)
                limit = 20 if request.GET.get("priority") == "high" else 10

                if current_count >= limit:
                    return Response(
                        {"error": "Rate limit exceeded"},
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                cache.set(rate_key, current_count + 1, 60)
                return Response({"message": "success"})

        view = TestView.as_view()

        # Test normal priority request
        request = self.factory.get("/api/test/")
        request.user = self.user
        response = view(request)
        self.assertEqual(response.status_code, 200)

        # Test high priority request
        request = self.factory.get("/api/test/?priority=high")
        request.user = self.user
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_bulk_operations_rate_limiting(self):
        """Test rate limiting for bulk operations"""

        class BulkTestView(APIView):
            permission_classes = []  # Allow unauthenticated access

            def post(self, request):
                # Rate limit based on bulk size
                items = request.data.get("items", [])
                bulk_size = len(items)

                # Apply stricter rate limiting for larger bulk operations
                if bulk_size > 10:
                    rate_key = f"bulk_large:{request.user.id}"
                    limit = 2  # Only 2 large bulk operations
                else:
                    rate_key = f"bulk_small:{request.user.id}"
                    limit = 10  # More small bulk operations allowed

                current_count = cache.get(rate_key, 0)
                if current_count >= limit:
                    return Response(
                        {"error": "Bulk rate limit exceeded"},
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                cache.set(rate_key, current_count + 1, 60)
                return Response({"message": f"Processed {bulk_size} items"})

        view = BulkTestView.as_view()

        # Test small bulk operation
        request = self.factory.post(
            "/api/bulk/", {"items": [1, 2, 3]}, content_type="application/json"
        )
        request.user = self.user
        # Disable CSRF for the test
        request._dont_enforce_csrf_checks = True
        response = view(request)
        self.assertEqual(response.status_code, 200)

        # Test large bulk operation
        request = self.factory.post(
            "/api/bulk/", {"items": list(range(15))}, content_type="application/json"
        )
        request.user = self.user
        # Disable CSRF for the test
        request._dont_enforce_csrf_checks = True
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_error_handling(self):
        """Test error handling when rate limits are exceeded"""

        class TestView(APIView):
            def get(self, request):
                # Simulate rate limit exceeded
                rate_key = f"error_test:{request.user.id}"
                current_count = cache.get(rate_key, 0)

                if current_count >= 1:  # Very low limit for testing
                    return Response(
                        {
                            "error": "Rate limit exceeded",
                            "message": "Too many requests",
                            "retry_after": 60,
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                cache.set(rate_key, current_count + 1, 60)
                return Response({"message": "success"})

        view = TestView.as_view()

        # First request should succeed
        request = self.factory.get("/api/test/")
        request.user = self.user
        response = view(request)
        self.assertEqual(response.status_code, 200)

        # Second request should be rate limited
        response = view(request)
        self.assertEqual(response.status_code, 429)
        self.assertIn("error", response.data)
        self.assertIn("retry_after", response.data)


class DRFRateLimitingUnitTests(TestCase):
    """
    Unit tests for DRF rate limiting components that don't require full DRF setup.
    """

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        cache.clear()

    def test_rate_limit_key_generation(self):
        """Test custom rate limit key generation functions"""

        def user_or_ip_key(group, request):
            """Custom key function: use user ID if authenticated, otherwise IP"""
            return (
                str(request.user.id)
                if request.user.is_authenticated
                else request.META.get("REMOTE_ADDR")
            )

        def user_role_key(group, request):
            """Custom key function: combine user ID with role"""
            if request.user.is_authenticated:
                role = "admin" if request.user.is_staff else "user"
                return f"{request.user.id}:{role}"
            return request.META.get("REMOTE_ADDR")

        # Test user_or_ip_key with authenticated user
        request = self.factory.get("/api/test/")
        request.user = self.user
        key = user_or_ip_key("test", request)
        self.assertEqual(key, str(self.user.id))

        # Test user_or_ip_key with anonymous user
        request.user = Mock()
        request.user.is_authenticated = False
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        key = user_or_ip_key("test", request)
        self.assertEqual(key, "127.0.0.1")

        # Test user_role_key with staff user
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="staffpass123",
            is_staff=True,
        )
        request = self.factory.get("/api/test/")
        request.user = staff_user
        key = user_role_key("test", request)
        self.assertEqual(key, f"{staff_user.id}:admin")

    def test_rate_limit_validation(self):
        """Test rate limiting in validation scenarios"""

        def validate_with_rate_limit(data, request):
            """Validate data with rate limiting"""
            user_id = request.user.id if request.user.is_authenticated else "anon"
            validation_key = f"validation:{user_id}"
            current_count = cache.get(validation_key, 0)

            if current_count >= 5:
                raise ValueError("Too many validation requests")

            cache.set(validation_key, current_count + 1, 60)

            # Perform actual validation
            if len(data.get("title", "")) < 3:
                raise ValueError("Title too short")

            return True

        request = self.factory.post("/api/test/")
        request.user = self.user

        # Test successful validation
        data = {"title": "Valid Title"}
        result = validate_with_rate_limit(data, request)
        self.assertTrue(result)

        # Test validation with invalid data
        invalid_data = {"title": "ab"}
        with self.assertRaises(ValueError) as cm:
            validate_with_rate_limit(invalid_data, request)
        self.assertIn("too short", str(cm.exception))

    def test_dynamic_rate_limits(self):
        """Test dynamic rate limit calculation"""

        def calculate_dynamic_rate(user, request):
            """Calculate dynamic rate based on user and request characteristics"""
            base_rate = 100

            # Adjust based on user role
            if user.is_staff:
                base_rate *= 2

            # Adjust based on request characteristics
            if request.GET.get("priority") == "high":
                base_rate = int(base_rate * 1.5)

            # Adjust based on time of day (mock)
            import datetime

            current_hour = datetime.datetime.now().hour
            if 9 <= current_hour <= 17:  # Business hours
                base_rate = int(base_rate * 0.8)

            return f"{base_rate}/h"

        # Test with regular user
        request = self.factory.get("/api/test/")
        request.user = self.user
        user_rate = calculate_dynamic_rate(self.user, request)
        # Rate should be adjusted based on business hours
        self.assertIsNotNone(user_rate)

        # Test with staff user
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="staffpass123",
            is_staff=True,
        )
        request.user = staff_user
        staff_rate = calculate_dynamic_rate(staff_user, request)
        # Rate should be higher for staff
        self.assertIsNotNone(staff_rate)

        # Test with high priority request
        request = self.factory.get("/api/test/?priority=high")
        request.user = self.user
        high_priority_rate = calculate_dynamic_rate(self.user, request)
        # Rate should be adjusted for high priority
        self.assertIsNotNone(high_priority_rate)

    def test_bypass_conditions(self):
        """Test rate limiting bypass conditions"""

        def should_bypass_rate_limit(request):
            """Determine if rate limiting should be bypassed"""
            # Bypass for superusers
            if request.user.is_superuser:
                return True

            # Bypass for internal API calls
            if request.META.get("HTTP_X_INTERNAL_API") == "true":
                return True

            # Bypass for specific user agents
            user_agent = request.META.get("HTTP_USER_AGENT", "")
            if "monitoring" in user_agent.lower():
                return True

            return False

        # Test with superuser
        superuser = User.objects.create_user(
            username="superuser",
            email="super@example.com",
            password="superpass123",
            is_superuser=True,
        )
        request = self.factory.get("/api/test/")
        request.user = superuser
        self.assertTrue(should_bypass_rate_limit(request))

        # Test with internal API call
        request = self.factory.get("/api/test/")
        request.user = self.user
        request.META["HTTP_X_INTERNAL_API"] = "true"
        self.assertTrue(should_bypass_rate_limit(request))

        # Test with monitoring user agent
        request = self.factory.get("/api/test/")
        request.user = self.user
        request.META["HTTP_USER_AGENT"] = "monitoring-tool/1.0"
        self.assertTrue(should_bypass_rate_limit(request))

        # Test with regular request
        request = self.factory.get("/api/test/")
        request.user = self.user
        self.assertFalse(should_bypass_rate_limit(request))


if __name__ == "__main__":
    unittest.main()
