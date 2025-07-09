"""
Simple DRF integration test without requiring DRF installation.

This module provides basic tests for DRF integration patterns that can run
without DRF being installed, using mocks to simulate DRF behavior.
"""

import unittest
from unittest.mock import Mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from django_smart_ratelimit.decorator import rate_limit


class DRFIntegrationMockTests(TestCase):
    """
    Tests for DRF integration using mocks.

    These tests verify that the rate limiting decorator works correctly
    with DRF-like patterns without requiring DRF to be installed.
    """

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        cache.clear()

    def test_rate_limiting_decorator_with_mock_viewset(self):
        """Test rate limiting decorator with mock ViewSet"""

        # Mock DRF ViewSet behavior
        class MockViewSet:
            def __init__(self):
                self.action = "list"
                self.request = None

            @rate_limit(key="user", rate="10/m")
            def list(self, request):
                return {"message": "success", "data": []}

        # Create viewset instance
        viewset = MockViewSet()

        # Create request
        request = self.factory.get("/api/test/")
        request.user = self.user

        # Test the decorated method
        result = viewset.list(request)
        self.assertEqual(result["message"], "success")

    def test_rate_limiting_with_mock_apiview(self):
        """Test rate limiting with mock APIView"""

        # Mock DRF APIView behavior
        class MockAPIView:
            @rate_limit(key="ip", rate="5/m")
            def get(self, request):
                return {"message": "get success"}

            @rate_limit(key="user", rate="3/m")
            def post(self, request):
                return {"message": "post success"}

        # Create view instance
        view = MockAPIView()

        # Test GET method
        request = self.factory.get("/api/test/")
        request.user = self.user
        result = view.get(request)
        self.assertEqual(result["message"], "get success")

        # Test POST method
        request = self.factory.post("/api/test/", {"data": "test"})
        request.user = self.user
        result = view.post(request)
        self.assertEqual(result["message"], "post success")

    def test_custom_key_functions(self):
        """Test custom key functions for rate limiting"""

        def user_or_ip_key(group, request):
            """Custom key: user ID if authenticated, otherwise IP"""
            if request.user.is_authenticated:
                return f"user:{request.user.id}"
            return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

        def user_role_key(group, request):
            """Custom key: user ID with role"""
            if request.user.is_authenticated:
                role = "staff" if request.user.is_staff else "user"
                return f"{request.user.id}:{role}"
            return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

        # Mock view with custom key functions
        class MockView:
            @rate_limit(key=user_or_ip_key, rate="10/m")
            def get_with_user_or_ip(self, request):
                return {"message": "success"}

            @rate_limit(key=user_role_key, rate="20/m")
            def get_with_user_role(self, request):
                return {"message": "success"}

        view = MockView()

        # Test with authenticated user
        request = self.factory.get("/api/test/")
        request.user = self.user
        result = view.get_with_user_or_ip(request)
        self.assertEqual(result["message"], "success")

        # Test with staff user
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="staffpass123",
            is_staff=True,
        )
        request.user = staff_user
        result = view.get_with_user_role(request)
        self.assertEqual(result["message"], "success")

    def test_mock_serializer_validation(self):
        """Test rate limiting in mock serializer validation"""

        # Mock serializer behavior
        class MockSerializer:
            def __init__(self, data, context=None):
                self.data = data
                self.context = context or {}
                self.errors = {}

            def validate_title(self, value):
                """Validate title with rate limiting"""
                request = self.context.get("request")
                if request:
                    # Simulate rate limiting check
                    user_id = (
                        request.user.id if request.user.is_authenticated else "anon"
                    )
                    validation_key = f"validation:{user_id}"
                    current_count = cache.get(validation_key, 0)

                    if current_count >= 3:  # Low limit for testing
                        raise ValueError("Too many validation requests")

                    cache.set(validation_key, current_count + 1, 60)

                if len(value) < 3:
                    raise ValueError("Title too short")
                return value

            def is_valid(self):
                """Check if data is valid"""
                try:
                    self.validate_title(self.data.get("title", ""))
                    return True
                except ValueError as e:
                    self.errors["title"] = str(e)
                    return False

        # Test serializer validation
        request = self.factory.post("/api/test/")
        request.user = self.user

        # Test valid data
        serializer = MockSerializer(
            {"title": "Valid Title"}, context={"request": request}
        )
        self.assertTrue(serializer.is_valid())

        # Test invalid data
        serializer = MockSerializer({"title": "ab"}, context={"request": request})
        self.assertFalse(serializer.is_valid())
        self.assertIn("title", serializer.errors)

        # Test rate limiting (make 3 validation requests)
        for i in range(3):
            serializer = MockSerializer({"title": "Test"}, context={"request": request})
            serializer.is_valid()

        # 4th request should be rate limited
        serializer = MockSerializer({"title": "Test"}, context={"request": request})
        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Too many validation requests", serializer.errors.get("title", "")
        )

    def test_mock_permission_rate_limiting(self):
        """Test rate limiting in mock permission"""

        # Mock permission behavior
        class MockPermission:
            def has_permission(self, request, view):
                """Check permission with rate limiting"""
                user_id = request.user.id if request.user.is_authenticated else "anon"
                user_key = f"permission:{user_id}"
                current_count = cache.get(user_key, 0)

                if current_count >= 5:  # Low limit for testing
                    return False

                cache.set(user_key, current_count + 1, 60)
                return True

        permission = MockPermission()

        # Mock view
        view = Mock()

        # Test permission checks
        request = self.factory.get("/api/test/")
        request.user = self.user

        # First few requests should be allowed
        for i in range(5):
            result = permission.has_permission(request, view)
            self.assertTrue(result)

        # 6th request should be denied
        result = permission.has_permission(request, view)
        self.assertFalse(result)

    def test_dynamic_rate_limiting(self):
        """Test dynamic rate limiting based on user characteristics"""

        def calculate_rate_limit(user):
            """Calculate rate limit based on user characteristics"""
            if user.is_staff:
                return "50/m"
            elif user.is_authenticated:
                return "20/m"
            else:
                return "10/m"

        # Mock view with dynamic rate limiting
        class MockView:
            def get(self, request):
                rate = calculate_rate_limit(request.user)
                return {"message": "success", "rate": rate}

        view = MockView()

        # Test with regular user
        request = self.factory.get("/api/test/")
        request.user = self.user
        result = view.get(request)
        self.assertEqual(result["rate"], "20/m")

        # Test with staff user
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="staffpass123",
            is_staff=True,
        )
        request.user = staff_user
        result = view.get(request)
        self.assertEqual(result["rate"], "50/m")

        # Test with anonymous user
        request.user = Mock()
        request.user.is_authenticated = False
        request.user.is_staff = False
        result = view.get(request)
        self.assertEqual(result["rate"], "10/m")

    def test_bulk_operation_rate_limiting(self):
        """Test rate limiting for bulk operations"""

        # Mock bulk operation view
        class MockBulkView:
            def post(self, request):
                items = request.data.get("items", [])
                bulk_size = len(items)

                # Apply different rate limits based on bulk size
                if bulk_size > 10:
                    rate_key = f"bulk_large:{request.user.id}"
                    limit = 2
                else:
                    rate_key = f"bulk_small:{request.user.id}"
                    limit = 5

                current_count = cache.get(rate_key, 0)
                if current_count >= limit:
                    return {"error": "Rate limit exceeded", "status": 429}

                cache.set(rate_key, current_count + 1, 60)
                return {"message": f"Processed {bulk_size} items", "status": 200}

        view = MockBulkView()

        # Test small bulk operation
        request = self.factory.post("/api/bulk/")
        request.user = self.user
        request.data = {"items": [1, 2, 3]}
        result = view.post(request)
        self.assertEqual(result["status"], 200)

        # Test large bulk operation
        request.data = {"items": list(range(15))}
        result = view.post(request)
        self.assertEqual(result["status"], 200)

    def test_time_based_rate_limiting(self):
        """Test time-based rate limiting"""

        import datetime

        def get_time_based_rate():
            """Get rate based on current time"""
            current_hour = datetime.datetime.now().hour
            if 9 <= current_hour <= 17:  # Business hours
                return "10/m"
            else:
                return "20/m"

        # Mock view with time-based rate limiting
        class MockTimeView:
            def get(self, request):
                rate = get_time_based_rate()
                return {"message": "success", "rate": rate}

        view = MockTimeView()
        request = self.factory.get("/api/test/")
        request.user = self.user

        result = view.get(request)
        self.assertIn("rate", result)
        self.assertTrue(result["rate"] in ["10/m", "20/m"])

    def test_bypass_conditions(self):
        """Test rate limiting bypass conditions"""

        def should_bypass_rate_limit(request):
            """Check if rate limiting should be bypassed"""
            # Bypass for superusers
            if request.user.is_superuser:
                return True

            # Bypass for internal API calls
            if request.META.get("HTTP_X_INTERNAL_API") == "true":
                return True

            # Bypass for monitoring requests
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


class DRFIntegrationUtilityTests(TestCase):
    """
    Tests for DRF integration utility functions.
    """

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        cache.clear()

    def test_key_function_helpers(self):
        """Test helper functions for key generation"""

        def extract_user_info(request):
            """Extract user information for rate limiting"""
            if request.user.is_authenticated:
                return {
                    "id": request.user.id,
                    "username": request.user.username,
                    "is_staff": request.user.is_staff,
                    "is_superuser": request.user.is_superuser,
                }
            return {
                "ip": request.META.get("REMOTE_ADDR", "unknown"),
                "user_agent": request.META.get("HTTP_USER_AGENT", "unknown"),
            }

        # Test with authenticated user
        request = self.factory.get("/api/test/")
        request.user = self.user
        user_info = extract_user_info(request)

        self.assertEqual(user_info["id"], self.user.id)
        self.assertEqual(user_info["username"], self.user.username)
        self.assertFalse(user_info["is_staff"])
        self.assertFalse(user_info["is_superuser"])

        # Test with anonymous user
        request = self.factory.get("/api/test/")
        request.user = Mock()
        request.user.is_authenticated = False
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        request.META["HTTP_USER_AGENT"] = "TestAgent/1.0"

        user_info = extract_user_info(request)
        self.assertEqual(user_info["ip"], "127.0.0.1")
        self.assertEqual(user_info["user_agent"], "TestAgent/1.0")

    def test_rate_limit_validation_helpers(self):
        """Test helper functions for rate limit validation"""

        def validate_rate_format(rate):
            """Validate rate format"""
            if not isinstance(rate, str):
                return False

            parts = rate.split("/")
            if len(parts) != 2:
                return False

            try:
                count = int(parts[0])
                period = parts[1]
                return count > 0 and period in ["s", "m", "h", "d"]
            except ValueError:
                return False

        # Test valid rates
        self.assertTrue(validate_rate_format("10/m"))
        self.assertTrue(validate_rate_format("100/h"))
        self.assertTrue(validate_rate_format("1/s"))
        self.assertTrue(validate_rate_format("1000/d"))

        # Test invalid rates
        self.assertFalse(validate_rate_format("invalid"))
        self.assertFalse(validate_rate_format("10"))
        self.assertFalse(validate_rate_format("10/x"))
        self.assertFalse(validate_rate_format("0/m"))
        self.assertFalse(validate_rate_format(10))


if __name__ == "__main__":
    unittest.main()
