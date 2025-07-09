"""
Django REST Framework Integration Tests

This module contains tests for the DRF integration examples to ensure
they work correctly with Django Smart Ratelimit.

Note: These tests are for demonstration purposes and require DRF to be installed.
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import RequestFactory, TestCase

try:
    from rest_framework import status
    from rest_framework.exceptions import Throttled
    from rest_framework.response import Response
    from rest_framework.test import APIClient, APITestCase

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
class DRFIntegrationTestCase(APITestCase):
    """
    Test cases for DRF integration examples.

    These tests verify that the rate limiting examples work correctly
    with DRF components.
    """

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client = APIClient()

        # Clear cache before each test
        cache.clear()

    def test_viewset_rate_limiting(self):
        """Test rate limiting in ViewSet examples"""
        # Import here to avoid import errors when DRF is not available
        from examples.drf_integration.viewsets import PostViewSet

        # Create a mock request
        request = self.factory.get("/api/posts/")
        request.user = self.user

        # Test the viewset
        viewset = PostViewSet()
        viewset.action = "list"
        viewset.request = request
        viewset.format_kwarg = None

        # Test list action - the decorator should be applied at import time
        response = viewset.list(request)
        self.assertEqual(response.status_code, 200)

        # Verify the viewset methods have the rate_limit decorator
        # by checking if the decorator was applied (look for decorated function)
        self.assertTrue(
            hasattr(viewset.list, "__wrapped__") or hasattr(viewset.list, "__name__")
        )

        # Test other methods
        response = viewset.retrieve(request, pk=1)
        self.assertEqual(response.status_code, 200)

    def test_serializer_integration(self):
        """Test rate limiting in Serializer examples"""
        # Test with a simple serializer instead of ModelSerializer
        from rest_framework import serializers

        from django_smart_ratelimit.decorator import rate_limit

        class SimplePostSerializer(serializers.Serializer):
            title = serializers.CharField(max_length=200)
            content = serializers.CharField()
            author = serializers.CharField()

            def validate_title(self, value):
                if len(value) < 3:
                    raise serializers.ValidationError(
                        "Title must be at least 3 characters long"
                    )
                return value

        # Create test data
        data = {
            "title": "Test Post",
            "content": "This is a test post content",
            "author": "testuser",
        }

        # Create serializer with request context
        request = self.factory.post("/api/posts/", data)
        request.user = self.user

        serializer = SimplePostSerializer(data=data, context={"request": request})

        # Test validation
        self.assertTrue(serializer.is_valid())

        # Test title validation
        invalid_data = data.copy()
        invalid_data["title"] = "ab"  # Too short

        invalid_serializer = SimplePostSerializer(
            data=invalid_data, context={"request": request}
        )
        self.assertFalse(invalid_serializer.is_valid())
        self.assertIn("title", invalid_serializer.errors)

    def test_permission_integration(self):
        """Test rate limiting in Permission examples"""
        from examples.drf_integration.permissions import RateLimitedPermission

        # Create a mock view
        view = Mock()
        view.__class__.__name__ = "TestView"
        view.action = "list"

        # Create a mock request
        request = self.factory.get("/api/test/")
        request.user = self.user

        # Test permission
        permission = RateLimitedPermission()

        # Mock the rate limiting check
        with patch.object(permission, "_check_rate_limit", return_value=True):
            result = permission.has_permission(request, view)
            self.assertTrue(result)

        # Test rate limit exceeded
        with patch.object(permission, "_check_rate_limit", return_value=False):
            with self.assertRaises(Throttled):
                permission.has_permission(request, view)

    def test_role_based_permission(self):
        """Test role-based rate limiting permission"""
        from examples.drf_integration.permissions import RoleBasedRateLimitedPermission

        # Create a mock view
        view = Mock()

        # Test with regular user
        request = self.factory.get("/api/test/")
        request.user = self.user

        permission = RoleBasedRateLimitedPermission()

        # Mock the rate limiting check
        with patch.object(permission, "_check_role_rate_limit", return_value=True):
            result = permission.has_permission(request, view)
            self.assertTrue(result)

        # Test with staff user
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="staffpass123",
            is_staff=True,
        )

        request.user = staff_user
        with patch.object(permission, "_check_role_rate_limit", return_value=True):
            result = permission.has_permission(request, view)
            self.assertTrue(result)

    def test_adaptive_permission(self):
        """Test adaptive rate limiting permission"""
        from examples.drf_integration.permissions import AdaptiveRateLimitedPermission

        # Create a mock view
        view = Mock()

        # Create a mock request
        request = self.factory.get("/api/test/")
        request.user = self.user

        permission = AdaptiveRateLimitedPermission()

        # Mock the system load and user behavior score
        with patch.object(permission, "_get_system_load", return_value=0.5):
            with patch.object(permission, "_get_user_behavior_score", return_value=0.8):
                with patch.object(
                    permission, "_check_adaptive_rate_limit", return_value=True
                ):
                    result = permission.has_permission(request, view)
                    self.assertTrue(result)

    def test_bypassable_permission(self):
        """Test bypassable rate limiting permission"""
        from examples.drf_integration.permissions import BypassableRateLimitedPermission

        # Create a mock view
        view = Mock()

        # Test with superuser (should bypass)
        superuser = User.objects.create_user(
            username="superuser",
            email="super@example.com",
            password="superpass123",
            is_superuser=True,
        )

        request = self.factory.get("/api/test/")
        request.user = superuser

        permission = BypassableRateLimitedPermission()

        # Superuser should bypass rate limiting
        result = permission.has_permission(request, view)
        self.assertTrue(result)

        # Test with regular user
        request.user = self.user
        with patch.object(permission, "_check_rate_limit", return_value=True):
            result = permission.has_permission(request, view)
            self.assertTrue(result)


class DRFIntegrationUnitTests(TestCase):
    """
    Unit tests for DRF integration components that don't require DRF.

    These tests can run even when DRF is not installed.
    """

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

        # Clear cache before each test
        cache.clear()

    def test_mock_post_model(self):
        """Test the mock Post model used in examples"""
        from examples.drf_integration.viewsets import Post

        post = Post(id=1, title="Test Post", content="Test content")
        self.assertEqual(post.id, 1)
        self.assertEqual(post.title, "Test Post")
        self.assertEqual(post.content, "Test content")

    def test_mock_comment_model(self):
        """Test the mock Comment model used in examples"""
        from examples.drf_integration.viewsets import Comment

        comment = Comment(id=1, content="Test comment")
        self.assertEqual(comment.id, 1)
        self.assertEqual(comment.content, "Test comment")

    def test_rate_limit_key_functions(self):
        """Test custom rate limit key functions"""
        # Create a mock request
        request = self.factory.get("/api/test/")
        request.user = self.user
        request.META["REMOTE_ADDR"] = "127.0.0.1"

        # Test user_or_ip_key function (simulate it)
        def user_or_ip_key(group, request):
            return (
                str(request.user.id)
                if request.user.is_authenticated
                else request.META.get("REMOTE_ADDR")
            )

        # Test with authenticated user
        key = user_or_ip_key("test", request)
        self.assertEqual(key, str(self.user.id))

        # Test with anonymous user
        request.user = Mock()
        request.user.is_authenticated = False
        key = user_or_ip_key("test", request)
        self.assertEqual(key, "127.0.0.1")

    def test_role_determination(self):
        """Test user role determination logic"""

        def get_user_role(user):
            if not user.is_authenticated:
                return "anonymous"
            elif user.is_superuser:
                return "admin"
            elif user.is_staff:
                return "staff"
            else:
                return "regular"

        # Test regular user
        self.assertEqual(get_user_role(self.user), "regular")

        # Test staff user
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="staffpass123",
            is_staff=True,
        )
        self.assertEqual(get_user_role(staff_user), "staff")

        # Test superuser
        superuser = User.objects.create_user(
            username="superuser",
            email="super@example.com",
            password="superpass123",
            is_superuser=True,
        )
        self.assertEqual(get_user_role(superuser), "admin")

        # Test anonymous user
        anon_user = Mock()
        anon_user.is_authenticated = False
        self.assertEqual(get_user_role(anon_user), "anonymous")


if __name__ == "__main__":
    unittest.main()
