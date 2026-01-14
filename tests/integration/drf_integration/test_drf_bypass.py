"""
DRF Bypass Pattern Tests.

Tests for rate limit bypass patterns (skip_if) with Django REST Framework views.
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
from django_smart_ratelimit.auth_utils import (
    is_internal_request,
    is_staff_user,
    is_superuser,
    should_bypass_rate_limit,
)
from django_smart_ratelimit.backends import clear_backend_cache
from tests.utils import create_test_staff_user, create_test_superuser, create_test_user


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFSkipIfSuperuser(TestCase):
    """Tests for skip_if with superuser bypass."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()
        self.superuser = create_test_superuser()

    def test_skip_if_superuser_bypasses_limit(self):
        """Test that superuser bypasses rate limit when skip_if=is_superuser."""

        class SuperuserView(APIView):
            @rate_limit(key="user", rate="2/m", block=True, skip_if=is_superuser)
            def get(self, request):
                return Response({"message": "success"})

        view = SuperuserView.as_view()

        # Superuser can make unlimited requests
        for i in range(10):
            request = self.factory.get("/api/test/")
            request.user = self.superuser
            response = view(request)
            self.assertEqual(
                response.status_code, 200, f"Superuser request {i+1} should succeed"
            )

    def test_skip_if_superuser_regular_user_limited(self):
        """Test that regular user is still rate limited."""

        class SuperuserView(APIView):
            @rate_limit(key="user", rate="2/m", block=True, skip_if=is_superuser)
            def get(self, request):
                return Response({"message": "success"})

        view = SuperuserView.as_view()

        # Regular user should be limited
        success_count = 0
        for _ in range(5):
            request = self.factory.get("/api/test/")
            request.user = self.user
            response = view(request)
            if response.status_code == 200:
                success_count += 1

        self.assertEqual(
            success_count, 2, "Regular user should be limited to 2 requests"
        )


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFSkipIfStaff(TestCase):
    """Tests for skip_if with staff bypass."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()
        self.staff_user = create_test_staff_user()

    def test_skip_if_staff_bypasses_limit(self):
        """Test that staff user bypasses rate limit when skip_if=is_staff_user."""

        class StaffView(APIView):
            @rate_limit(key="user", rate="2/m", block=True, skip_if=is_staff_user)
            def get(self, request):
                return Response({"message": "success"})

        view = StaffView.as_view()

        # Staff user can make unlimited requests
        for i in range(10):
            request = self.factory.get("/api/test/")
            request.user = self.staff_user
            response = view(request)
            self.assertEqual(
                response.status_code, 200, f"Staff request {i+1} should succeed"
            )

    def test_skip_if_staff_regular_user_limited(self):
        """Test that regular user is still rate limited."""

        class StaffView(APIView):
            @rate_limit(key="user", rate="2/m", block=True, skip_if=is_staff_user)
            def get(self, request):
                return Response({"message": "success"})

        view = StaffView.as_view()

        # Regular user should be limited
        success_count = 0
        for _ in range(5):
            request = self.factory.get("/api/test/")
            request.user = self.user
            response = view(request)
            if response.status_code == 200:
                success_count += 1

        self.assertEqual(
            success_count, 2, "Regular user should be limited to 2 requests"
        )


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFSkipIfInternalIP(TestCase):
    """Tests for skip_if with internal IP bypass."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()

    def test_skip_if_internal_ip_bypasses_limit(self):
        """Test that internal IP bypasses rate limit."""

        class InternalView(APIView):
            @rate_limit(key="ip", rate="2/m", block=True, skip_if=is_internal_request)
            def get(self, request):
                return Response({"message": "success"})

        view = InternalView.as_view()

        # Internal IP (127.0.0.1) can make unlimited requests
        for i in range(10):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "127.0.0.1"
            request.user = self.user
            response = view(request)
            self.assertEqual(
                response.status_code, 200, f"Internal IP request {i+1} should succeed"
            )

    def test_skip_if_internal_10_network_bypasses(self):
        """Test that 10.x.x.x network bypasses rate limit."""

        class InternalView(APIView):
            @rate_limit(key="ip", rate="2/m", block=True, skip_if=is_internal_request)
            def get(self, request):
                return Response({"message": "success"})

        view = InternalView.as_view()

        # 10.x.x.x network should bypass
        for i in range(10):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "10.0.0.50"
            request.user = self.user
            response = view(request)
            self.assertEqual(
                response.status_code, 200, f"10.x.x.x request {i+1} should succeed"
            )

    def test_skip_if_external_ip_limited(self):
        """Test that external IP is rate limited."""

        class InternalView(APIView):
            @rate_limit(key="ip", rate="2/m", block=True, skip_if=is_internal_request)
            def get(self, request):
                return Response({"message": "success"})

        view = InternalView.as_view()

        # External IP should be limited
        success_count = 0
        for _ in range(5):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "203.0.113.50"  # External IP
            request.user = self.user
            response = view(request)
            if response.status_code == 200:
                success_count += 1

        self.assertEqual(
            success_count, 2, "External IP should be limited to 2 requests"
        )


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFSkipIfCustomCallable(TestCase):
    """Tests for skip_if with custom callable."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()

    def test_skip_if_custom_header_bypasses(self):
        """Test that custom header bypass works."""

        def check_internal_api_header(request, *args, **kwargs):
            return request.META.get("HTTP_X_INTERNAL_API") == "true"

        class CustomHeaderView(APIView):
            @rate_limit(
                key="ip", rate="2/m", block=True, skip_if=check_internal_api_header
            )
            def get(self, request):
                return Response({"message": "success"})

        view = CustomHeaderView.as_view()

        # Request with internal API header should bypass
        for i in range(10):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "203.0.113.60"
            request.META["HTTP_X_INTERNAL_API"] = "true"
            request.user = self.user
            response = view(request)
            self.assertEqual(
                response.status_code, 200, f"Internal API request {i+1} should succeed"
            )

    def test_skip_if_monitoring_user_agent_bypasses(self):
        """Test that monitoring user agent bypass works."""

        def check_monitoring_agent(request, *args, **kwargs):
            user_agent = request.META.get("HTTP_USER_AGENT", "")
            return "monitoring" in user_agent.lower()

        class MonitoringView(APIView):
            @rate_limit(
                key="ip", rate="2/m", block=True, skip_if=check_monitoring_agent
            )
            def get(self, request):
                return Response({"message": "success"})

        view = MonitoringView.as_view()

        # Request with monitoring user agent should bypass
        for i in range(10):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "203.0.113.70"
            request.META["HTTP_USER_AGENT"] = "monitoring-tool/1.0"
            request.user = self.user
            response = view(request)
            self.assertEqual(
                response.status_code,
                200,
                f"Monitoring agent request {i+1} should succeed",
            )

    def test_skip_if_callable_receives_request(self):
        """Test that skip_if callable receives the request object."""
        received_requests = []

        def capture_request(request, *args, **kwargs):
            received_requests.append(request)
            return False  # Don't skip

        class CaptureView(APIView):
            @rate_limit(key="ip", rate="10/m", block=True, skip_if=capture_request)
            def get(self, request):
                return Response({"message": "success"})

        view = CaptureView.as_view()

        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "203.0.113.80"
        request.user = self.user
        view(request)

        self.assertEqual(len(received_requests), 1)
        self.assertEqual(received_requests[0].META["REMOTE_ADDR"], "203.0.113.80")

    def test_skip_if_false_applies_rate_limit(self):
        """Test that when skip_if returns False, rate limit is applied."""

        def never_skip(request, *args, **kwargs):
            return False

        class NeverSkipView(APIView):
            @rate_limit(key="ip", rate="2/m", block=True, skip_if=never_skip)
            def get(self, request):
                return Response({"message": "success"})

        view = NeverSkipView.as_view()

        success_count = 0
        for _ in range(5):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "203.0.113.90"
            request.user = self.user
            response = view(request)
            if response.status_code == 200:
                success_count += 1

        self.assertEqual(
            success_count, 2, "Should be limited when skip_if returns False"
        )


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFBuiltInBypassFunctions(TestCase):
    """Tests for built-in bypass functions."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()
        self.superuser = create_test_superuser()
        self.staff_user = create_test_staff_user()

    def test_should_bypass_rate_limit_superuser(self):
        """Test should_bypass_rate_limit with superuser."""

        class BypassView(APIView):
            @rate_limit(
                key="user", rate="2/m", block=True, skip_if=should_bypass_rate_limit
            )
            def get(self, request):
                return Response({"message": "success"})

        view = BypassView.as_view()

        # Superuser should bypass
        for i in range(10):
            request = self.factory.get("/api/test/")
            request.user = self.superuser
            response = view(request)
            self.assertEqual(
                response.status_code, 200, f"Superuser request {i+1} should succeed"
            )

    def test_should_bypass_rate_limit_staff(self):
        """Test should_bypass_rate_limit with staff user (bypass_staff=True)."""
        from functools import partial

        # Create a custom bypass function with bypass_staff=True
        bypass_with_staff = partial(should_bypass_rate_limit, bypass_staff=True)

        class BypassView(APIView):
            @rate_limit(key="user", rate="2/m", block=True, skip_if=bypass_with_staff)
            def get(self, request):
                return Response({"message": "success"})

        view = BypassView.as_view()

        # Staff user should bypass when bypass_staff=True
        for i in range(10):
            request = self.factory.get("/api/test/")
            request.user = self.staff_user
            response = view(request)
            self.assertEqual(
                response.status_code, 200, f"Staff request {i+1} should succeed"
            )

    def test_should_bypass_rate_limit_regular_user_limited(self):
        """Test should_bypass_rate_limit with regular user."""

        class BypassView(APIView):
            @rate_limit(
                key="user", rate="2/m", block=True, skip_if=should_bypass_rate_limit
            )
            def get(self, request):
                return Response({"message": "success"})

        view = BypassView.as_view()

        # Regular user should be limited
        success_count = 0
        for _ in range(5):
            request = self.factory.get("/api/test/")
            request.user = self.user
            response = view(request)
            if response.status_code == 200:
                success_count += 1

        self.assertEqual(success_count, 2, "Regular user should be limited")


if __name__ == "__main__":
    unittest.main()
