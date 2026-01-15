"""
Tests for key_functions module.
"""

from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpRequest
from django.test import TestCase

from django_smart_ratelimit import (
    geographic_key,
    tenant_aware_key,
    time_aware_key,
    user_or_ip_key,
    user_role_key,
)


class KeyFunctionsTests(TestCase):
    """Tests for key generation functions."""

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

    def test_user_or_ip_key_authenticated(self):
        """Test user_or_ip_key with authenticated user."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        key = user_or_ip_key(request)

        self.assertEqual(key, f"user:{self.user.id}")

    def test_user_or_ip_key_anonymous(self):
        """Test user_or_ip_key with anonymous user."""
        request = HttpRequest()
        request.user = AnonymousUser()
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        key = user_or_ip_key(request)

        self.assertEqual(key, "ip:127.0.0.1")

    def test_user_or_ip_key_no_user_attribute(self):
        """Test user_or_ip_key with no user attribute."""
        request = HttpRequest()
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        key = user_or_ip_key(request)

        self.assertEqual(key, "ip:127.0.0.1")

    def test_user_role_key_authenticated_user(self):
        """Test user_role_key with authenticated regular user."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        key = user_role_key(request)

        self.assertEqual(key, f"{self.user.id}:user")

    def test_user_role_key_staff_user(self):
        """Test user_role_key with staff user."""
        request = HttpRequest()
        request.user = self.staff_user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        key = user_role_key(request)

        self.assertEqual(key, f"{self.staff_user.id}:staff")

    def test_user_role_key_anonymous(self):
        """Test user_role_key with anonymous user."""
        request = HttpRequest()
        request.user = AnonymousUser()
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        key = user_role_key(request)

        self.assertEqual(key, "ip:127.0.0.1")

    def test_geographic_key_with_country_header(self):
        """Test geographic_key with country header."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1", "HTTP_CF_IPCOUNTRY": "US"}

        key = geographic_key(request)

        self.assertEqual(key, f"geo:US:user:{self.user.id}")

    def test_geographic_key_no_country_header(self):
        """Test geographic_key without country header."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        key = geographic_key(request)

        self.assertEqual(key, f"geo:unknown:user:{self.user.id}")

    def test_tenant_aware_key_from_get_params(self):
        """Test tenant_aware_key with GET parameters."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.GET = {"tenant_id": "tenant123"}

        key = tenant_aware_key(request)

        self.assertEqual(key, f"tenant:tenant123:user:{self.user.id}")

    def test_tenant_aware_key_from_header(self):
        """Test tenant_aware_key with HTTP header."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1", "HTTP_TENANT_ID": "tenant456"}

        key = tenant_aware_key(request)

        self.assertEqual(key, f"tenant:tenant456:user:{self.user.id}")

    def test_tenant_aware_key_from_user_attribute(self):
        """Test tenant_aware_key with user attribute."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        # Mock tenant_id attribute on user
        setattr(self.user, "tenant_id", "tenant789")

        key = tenant_aware_key(request)

        self.assertEqual(key, f"tenant:tenant789:user:{self.user.id}")

    def test_tenant_aware_key_no_tenant(self):
        """Test tenant_aware_key with no tenant information."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        key = tenant_aware_key(request)

        self.assertEqual(key, f"user:{self.user.id}")

    def test_tenant_aware_key_custom_field(self):
        """Test tenant_aware_key with custom tenant field."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        request.GET = {"org_id": "org123"}

        key = tenant_aware_key(request, tenant_field="org_id")

        self.assertEqual(key, f"tenant:org123:user:{self.user.id}")

    def test_time_aware_key_hour_window(self):
        """Test time_aware_key with hour window."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        key = time_aware_key(request, time_window="hour")

        self.assertIn(f"user:{self.user.id}", key)
        self.assertIn("time:hour:", key)

    def test_time_aware_key_day_window(self):
        """Test time_aware_key with day window."""
        request = HttpRequest()
        request.user = self.user
        request.META = {"REMOTE_ADDR": "127.0.0.1"}

        key = time_aware_key(request, time_window="day")

        self.assertIn(f"user:{self.user.id}", key)
        self.assertIn("time:day:", key)

    def test_key_functions_with_forwarded_for(self):
        """Test key functions with X-Forwarded-For header."""
        request = HttpRequest()
        request.user = AnonymousUser()
        request.META = {
            "REMOTE_ADDR": "10.0.0.1",
            "HTTP_X_FORWARDED_FOR": "192.168.1.1, 10.0.0.1",
        }

        key = user_or_ip_key(request)

        self.assertEqual(key, "ip:192.168.1.1")

    def test_key_functions_with_real_ip(self):
        """Test key functions with X-Real-IP header."""
        request = HttpRequest()
        request.user = AnonymousUser()
        request.META = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_REAL_IP": "192.168.1.1"}

        key = user_or_ip_key(request)

        self.assertEqual(key, "ip:192.168.1.1")
