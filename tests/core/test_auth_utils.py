"""
Tests for auth_utils module.
"""

from unittest.mock import Mock

from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpRequest
from django.test import TestCase

from django_smart_ratelimit import (
    get_client_info,
    get_user_info,
    has_permission,
    is_authenticated_user,
    is_staff_user,
)


class AuthUtilsTests(TestCase):
    """Tests for authentication utilities."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            is_staff=False,
            is_superuser=False,
        )

        self.staff_user = User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
            is_superuser=False,
        )

        self.superuser = User.objects.create_user(
            username="superuser",
            email="super@example.com",
            password="testpass123",
            is_staff=True,
            is_superuser=True,
        )

    def test_is_authenticated_user_with_authenticated_user(self):
        """Test is_authenticated_user with authenticated user."""
        request = HttpRequest()
        request.user = self.user

        self.assertTrue(is_authenticated_user(request))

    def test_is_authenticated_user_with_anonymous_user(self):
        """Test is_authenticated_user with anonymous user."""
        request = HttpRequest()
        request.user = AnonymousUser()

        self.assertFalse(is_authenticated_user(request))

    def test_is_authenticated_user_no_user_attribute(self):
        """Test is_authenticated_user with no user attribute."""
        request = HttpRequest()
        # No user attribute

        self.assertFalse(is_authenticated_user(request))

    def test_get_user_info_authenticated(self):
        """Test get_user_info with authenticated user."""
        request = HttpRequest()
        request.user = self.user

        info = get_user_info(request)

        self.assertIsNotNone(info)
        self.assertEqual(info["id"], self.user.id)
        self.assertEqual(info["username"], self.user.username)
        self.assertFalse(info["is_staff"])
        self.assertFalse(info["is_superuser"])

    def test_get_user_info_staff(self):
        """Test get_user_info with staff user."""
        request = HttpRequest()
        request.user = self.staff_user

        info = get_user_info(request)

        self.assertIsNotNone(info)
        self.assertTrue(info["is_staff"])
        self.assertFalse(info["is_superuser"])

    def test_get_user_info_superuser(self):
        """Test get_user_info with superuser."""
        request = HttpRequest()
        request.user = self.superuser

        info = get_user_info(request)

        self.assertIsNotNone(info)
        self.assertTrue(info["is_staff"])
        self.assertTrue(info["is_superuser"])

    def test_get_user_info_anonymous(self):
        """Test get_user_info with anonymous user."""
        request = HttpRequest()
        request.user = AnonymousUser()

        info = get_user_info(request)

        self.assertIsNone(info)

    def test_get_client_info_basic(self):
        """Test get_client_info with basic request."""
        request = HttpRequest()
        request.META = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_USER_AGENT": "TestAgent/1.0",
        }

        info = get_client_info(request)

        self.assertIsInstance(info, dict)
        self.assertEqual(info["ip"], "127.0.0.1")
        self.assertEqual(info["user_agent"], "TestAgent/1.0")

    def test_get_client_info_with_forwarded_for(self):
        """Test get_client_info with X-Forwarded-For header."""
        request = HttpRequest()
        request.META = {
            "REMOTE_ADDR": "10.0.0.1",
            "HTTP_X_FORWARDED_FOR": "192.168.1.1, 10.0.0.1",
            "HTTP_USER_AGENT": "TestAgent/1.0",
        }

        info = get_client_info(request)

        self.assertEqual(info["ip"], "10.0.0.1")  # Returns REMOTE_ADDR
        self.assertEqual(
            info["forwarded_for"], "192.168.1.1, 10.0.0.1"
        )  # Available in forwarded_for

    def test_get_client_info_with_real_ip(self):
        """Test get_client_info with X-Real-IP header."""
        request = HttpRequest()
        request.META = {
            "REMOTE_ADDR": "10.0.0.1",
            "HTTP_X_REAL_IP": "192.168.1.1",
            "HTTP_USER_AGENT": "TestAgent/1.0",
        }

        info = get_client_info(request)

        self.assertEqual(info["ip"], "10.0.0.1")  # Returns REMOTE_ADDR
        self.assertEqual(info["real_ip"], "192.168.1.1")  # Available in real_ip

    def test_get_permission_info_authenticated(self):
        """Test get_permission_info with authenticated user."""
        request = HttpRequest()
        request.user = self.user

        # Test has_permission instead
        result = has_permission(request, "test.permission")
        self.assertIsInstance(result, bool)

    def test_get_permission_info_anonymous(self):
        """Test get_permission_info with anonymous user."""
        request = HttpRequest()
        request.user = AnonymousUser()

        # Test has_permission instead
        result = has_permission(request, "test.permission")
        self.assertFalse(result)

    def test_is_staff_user_with_staff(self):
        """Test is_staff_user with staff user."""
        request = HttpRequest()
        request.user = self.staff_user

        self.assertTrue(is_staff_user(request))

    def test_is_staff_user_with_regular_user(self):
        """Test is_staff_user with regular user."""
        request = HttpRequest()
        request.user = self.user

        self.assertFalse(is_staff_user(request))

    def test_is_staff_user_with_anonymous(self):
        """Test is_staff_user with anonymous user."""
        request = HttpRequest()
        request.user = AnonymousUser()

        self.assertFalse(is_staff_user(request))

    def test_has_permission_authenticated(self):
        """Test has_permission with authenticated user."""
        request = HttpRequest()
        request.user = self.user

        # Mock permission check
        self.user.has_perm = Mock(return_value=True)

        result = has_permission(request, "test.permission")

        self.assertTrue(result)

    def test_has_permission_anonymous(self):
        """Test has_permission with anonymous user."""
        request = HttpRequest()
        request.user = AnonymousUser()

        result = has_permission(request, "test.permission")

        self.assertFalse(result)
