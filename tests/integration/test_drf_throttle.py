"""
Tests for django-smart-ratelimit DRF throttle adapter.

Tests the SmartRateLimitThrottle and related classes that integrate
django-smart-ratelimit with Django REST Framework's throttling system.
"""

import unittest
from unittest.mock import Mock, patch

import pytest

from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings

try:
    from rest_framework.response import Response
    from rest_framework.test import APIClient, APITestCase
    from rest_framework.views import APIView

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not DRF_AVAILABLE, reason="Django REST Framework not installed"
)


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
        "DEFAULT_THROTTLE_RATES": {
            "user": "5/minute",
            "anon": "3/minute",
            "custom": "10/minute",
        }
    },
    RATELIMIT_BACKEND="django_smart_ratelimit.backends.memory.MemoryBackend",
)
class SmartRateLimitThrottleTestCase(APITestCase):
    """Test SmartRateLimitThrottle basic functionality."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset backend cache + state so each test sees a fresh MemoryBackend.
        from django_smart_ratelimit.backends import (
            clear_backend_cache,
            get_backend,
        )

        clear_backend_cache()
        backend = get_backend()
        if hasattr(backend, "clear_all"):
            backend.clear_all()

        self.factory = RequestFactory()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass"
        )
        self.client = APIClient()

    def tearDown(self):
        """Tear down — reset backend state for isolation."""
        from django_smart_ratelimit.backends import (
            clear_backend_cache,
            get_backend,
        )

        try:
            backend = get_backend()
            if hasattr(backend, "clear_all"):
                backend.clear_all()
        except Exception:
            pass
        clear_backend_cache()

    def test_throttle_unavailable_without_drf(self):
        """Test that throttle raises ImportError when DRF not installed."""
        with patch("django_smart_ratelimit.integrations.drf.BaseThrottle", None):
            from django_smart_ratelimit.integrations.drf import (
                SmartRateLimitThrottle,
            )

            with pytest.raises(ImportError, match="django-rest-framework"):
                SmartRateLimitThrottle()

    def test_user_throttle_basic(self):
        """Test UserRateLimitThrottle allows requests within limit."""
        from django_smart_ratelimit.integrations.drf import (
            UserRateLimitThrottle,
        )

        throttle = UserRateLimitThrottle()
        request = self.factory.get("/api/test/")
        request.user = self.user
        view = Mock()

        # First request should be allowed
        assert throttle.allow_request(request, view) is True

        # Wait() should return reasonable value
        wait_time = throttle.wait()
        assert wait_time is None or isinstance(wait_time, float)

    def test_user_throttle_exceeds_limit(self):
        """Test UserRateLimitThrottle blocks after limit exceeded."""
        from django_smart_ratelimit.integrations.drf import (
            UserRateLimitThrottle,
        )

        throttle = UserRateLimitThrottle()
        request = self.factory.get("/api/test/")
        request.user = self.user
        view = Mock()

        # Make requests up to limit
        for i in range(5):
            result = throttle.allow_request(request, view)
            assert result is True, f"Request {i+1} should be allowed"

        # 6th request should be blocked
        throttle_6 = UserRateLimitThrottle()
        result = throttle_6.allow_request(request, view)
        assert result is False, "Request 6 should be blocked"

    def test_anon_throttle_by_ip(self):
        """Test AnonRateLimitThrottle uses IP for anonymous users."""
        from django_smart_ratelimit.integrations.drf import (
            AnonRateLimitThrottle,
        )

        throttle = AnonRateLimitThrottle()
        request = self.factory.get("/api/test/")
        request.user = Mock(is_authenticated=False)
        request.META["REMOTE_ADDR"] = "192.168.1.1"
        view = Mock()

        # Should use IP-based key
        key = throttle.get_cache_key(request, view)
        assert "ip:" in key

        # First request allowed
        assert throttle.allow_request(request, view) is True

    def test_anon_throttle_limit(self):
        """Test AnonRateLimitThrottle blocks after limit (3/minute)."""
        from django_smart_ratelimit.integrations.drf import (
            AnonRateLimitThrottle,
        )

        request = self.factory.get("/api/test/")
        request.user = Mock(is_authenticated=False)
        request.META["REMOTE_ADDR"] = "192.168.1.1"
        view = Mock()

        # Make 3 requests
        for i in range(3):
            throttle = AnonRateLimitThrottle()
            result = throttle.allow_request(request, view)
            assert result is True, f"Request {i+1} should be allowed"

        # 4th should be blocked
        throttle = AnonRateLimitThrottle()
        result = throttle.allow_request(request, view)
        assert result is False, "Request 4 should be blocked"

    def test_different_users_have_separate_limits(self):
        """Test that different users have independent rate limits."""
        from django_smart_ratelimit.integrations.drf import (
            UserRateLimitThrottle,
        )

        User = get_user_model()
        user2 = User.objects.create_user(
            username="user2", email="user2@example.com", password="testpass"
        )

        # Request 1: user1
        request1 = self.factory.get("/api/test/")
        request1.user = self.user
        view = Mock()

        throttle = UserRateLimitThrottle()
        assert throttle.allow_request(request1, view) is True

        # Request 2: user2 (should have separate limit)
        request2 = self.factory.get("/api/test/")
        request2.user = user2
        view = Mock()

        throttle = UserRateLimitThrottle()
        assert throttle.allow_request(request2, view) is True

    def test_custom_rate_attribute(self):
        """Test throttle with custom rate attribute."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        class CustomThrottle(SmartRateLimitThrottle):
            scope = "custom"
            rate = "2/minute"

        throttle = CustomThrottle()
        request = self.factory.get("/api/test/")
        request.user = self.user
        view = Mock()

        # First 2 should pass
        assert throttle.allow_request(request, view) is True
        throttle = CustomThrottle()
        assert throttle.allow_request(request, view) is True

        # 3rd should fail
        throttle = CustomThrottle()
        assert throttle.allow_request(request, view) is False

    def test_custom_key_func(self):
        """Test throttle with custom key_func."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        def custom_key(request, view):
            """Use a custom header as key."""
            return request.META.get("HTTP_X_CUSTOM_KEY", "default")

        class CustomKeyThrottle(SmartRateLimitThrottle):
            scope = "custom"
            rate = "3/minute"
            key_func = custom_key

        request = self.factory.get("/api/test/")
        request.META["HTTP_X_CUSTOM_KEY"] = "special-key"
        view = Mock()

        throttle = CustomKeyThrottle()
        assert throttle.allow_request(request, view) is True

        # Verify it used custom key
        key = custom_key(request, view)
        assert key == "special-key"

    def test_callable_rate(self):
        """Test throttle with callable rate."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        def get_rate(throttle, request):
            """Return different rates based on user."""
            if hasattr(request, "user") and request.user.is_staff:
                return "100/minute"
            return "5/minute"

        class DynamicRateThrottle(SmartRateLimitThrottle):
            scope = "dynamic"
            rate = get_rate

        request = self.factory.get("/api/test/")
        request.user = self.user
        view = Mock()

        throttle = DynamicRateThrottle()
        # Should get regular rate for non-staff
        resolved_rate = throttle._get_rate(request, view)
        assert resolved_rate == "5/minute"

    def test_scoped_throttle_with_throttle_scope(self):
        """Test ScopedRateLimitThrottle respects view's throttle_scope."""
        from django_smart_ratelimit.integrations.drf import (
            ScopedRateLimitThrottle,
        )

        throttle = ScopedRateLimitThrottle()
        request = self.factory.get("/api/test/")
        request.user = self.user

        # Create view with throttle_scope
        view = Mock()
        view.throttle_scope = "custom"

        assert throttle.allow_request(request, view) is True

    def test_scoped_throttle_missing_scope_attribute(self):
        """Test ScopedRateLimitThrottle handles missing throttle_scope."""
        from django_smart_ratelimit.integrations.drf import (
            ScopedRateLimitThrottle,
        )

        throttle = ScopedRateLimitThrottle()
        request = self.factory.get("/api/test/")
        request.user = self.user

        # View without throttle_scope
        view = Mock(spec=[])

        # Should allow request and log warning
        with patch("django_smart_ratelimit.integrations.drf.logger") as mock_logger:
            result = throttle.allow_request(request, view)
            assert result is True
            mock_logger.warning.assert_called()

    def test_get_cache_key_defaults(self):
        """Test get_cache_key defaults to user ID or IP."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        throttle = SmartRateLimitThrottle()
        request = self.factory.get("/api/test/")
        request.user = self.user
        view = Mock()

        key = throttle.get_cache_key(request, view)
        assert f"user:{self.user.id}" == key

        # Anonymous user
        request.user = Mock(is_authenticated=False)
        request.META["REMOTE_ADDR"] = "10.0.0.1"

        key = throttle.get_cache_key(request, view)
        assert "ip:" in key

    def test_wait_returns_none_initially(self):
        """Test wait() returns None if not yet called."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        throttle = SmartRateLimitThrottle()
        throttle.scope = "user"
        request = self.factory.get("/api/test/")
        request.user = self.user
        Mock()

        # Before calling allow_request, wait should be None
        assert throttle.wait() is None

    def test_wait_returns_valid_seconds(self):
        """Test wait() returns valid wait time after throttle."""
        from django_smart_ratelimit.integrations.drf import (
            UserRateLimitThrottle,
        )

        throttle = UserRateLimitThrottle()
        request = self.factory.get("/api/test/")
        request.user = self.user
        view = Mock()

        # Consume the limit
        for _ in range(5):
            throttle = UserRateLimitThrottle()
            throttle.allow_request(request, view)

        # Get a throttle that was throttled
        throttle = UserRateLimitThrottle()
        throttle.allow_request(request, view)  # This should fail

        wait_time = throttle.wait()
        assert wait_time is not None
        assert isinstance(wait_time, float)
        assert wait_time > 0

    def test_throttle_success_and_failure(self):
        """Test throttle_success and throttle_failure methods."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        throttle = SmartRateLimitThrottle()

        assert throttle.throttle_success() is True
        assert throttle.throttle_failure() is False

    def test_backend_error_fail_open(self):
        """Test throttle allows request when backend fails with fail_open."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        throttle = SmartRateLimitThrottle()
        throttle.scope = "user"
        request = self.factory.get("/api/test/")
        request.user = self.user
        view = Mock()

        # Mock backend to raise error but with fail_open=True
        with patch(
            "django_smart_ratelimit.integrations.drf.get_backend"
        ) as mock_get_backend:
            mock_backend = Mock()
            mock_backend.fail_open = True
            mock_backend.incr.side_effect = Exception("Backend down")
            mock_get_backend.return_value = mock_backend

            # Should allow request
            result = throttle.allow_request(request, view)
            assert result is True

    def test_invalid_rate_string(self):
        """Test throttle handles invalid rate strings."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        class BadRateThrottle(SmartRateLimitThrottle):
            scope = "bad"
            rate = "invalid"

        throttle = BadRateThrottle()
        request = self.factory.get("/api/test/")
        request.user = self.user
        view = Mock()

        # Should allow request when rate parsing fails
        result = throttle.allow_request(request, view)
        assert result is True

    def test_no_rate_configured(self):
        """Test throttle when no rate is configured."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        class NoRateThrottle(SmartRateLimitThrottle):
            scope = "nonexistent_scope"

        throttle = NoRateThrottle()
        request = self.factory.get("/api/test/")
        request.user = self.user
        view = Mock()

        # Should allow request (can't throttle without rate)
        result = throttle.allow_request(request, view)
        assert result is True

    def test_get_cost_default(self):
        """Test get_cost returns default cost of 1."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        throttle = SmartRateLimitThrottle()
        request = self.factory.get("/api/test/")
        view = Mock()

        cost = throttle.get_cost(request, view)
        assert cost == 1

    def test_get_cost_callable(self):
        """Test get_cost with callable."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        def cost_func(request, view):
            return 5

        class CustomCostThrottle(SmartRateLimitThrottle):
            cost = cost_func

        throttle = CustomCostThrottle()
        request = self.factory.get("/api/test/")
        view = Mock()

        cost = throttle.get_cost(request, view)
        assert cost == 5

    def test_algorithm_attribute(self):
        """Test algorithm attribute is set correctly."""
        from django_smart_ratelimit.integrations.drf import (
            SmartRateLimitThrottle,
        )

        class SlidingWindowThrottle(SmartRateLimitThrottle):
            algorithm = "sliding_window"

        throttle = SlidingWindowThrottle()
        assert throttle.algorithm == "sliding_window"

    def test_multiple_throttles_on_request(self):
        """Test multiple throttles on same request (different scopes)."""
        from django_smart_ratelimit.integrations.drf import (
            AnonRateLimitThrottle,
            UserRateLimitThrottle,
        )

        request = self.factory.get("/api/test/")
        request.user = self.user
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        view = Mock()

        # Both should start independently
        user_throttle = UserRateLimitThrottle()
        anon_throttle = AnonRateLimitThrottle()

        assert user_throttle.allow_request(request, view) is True
        assert anon_throttle.allow_request(request, view) is True

        # Keys should be different
        user_key = user_throttle.get_cache_key(request, view)
        anon_key = anon_throttle.get_cache_key(request, view)
        assert user_key != anon_key


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(
    INSTALLED_APPS=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "rest_framework",
        "django_smart_ratelimit",
    ],
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_CLASSES": [
            "django_smart_ratelimit.integrations.drf.UserRateLimitThrottle",
            "django_smart_ratelimit.integrations.drf.AnonRateLimitThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "user": "3/minute",
            "anon": "2/minute",
        },
    },
    RATELIMIT_BACKEND="django_smart_ratelimit.backends.memory.MemoryBackend",
)
class DRFViewIntegrationTestCase(APITestCase):
    """Test DRF throttles in actual DRF views."""

    def setUp(self):
        """Set up test fixtures."""
        from django_smart_ratelimit.backends import (
            clear_backend_cache,
            get_backend,
        )

        clear_backend_cache()
        backend = get_backend()
        if hasattr(backend, "clear_all"):
            backend.clear_all()

        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass"
        )
        self.client = APIClient()

    def tearDown(self):
        """Tear down — reset backend state for isolation."""
        from django_smart_ratelimit.backends import (
            clear_backend_cache,
            get_backend,
        )

        try:
            backend = get_backend()
            if hasattr(backend, "clear_all"):
                backend.clear_all()
        except Exception:
            pass
        clear_backend_cache()

    def test_throttle_in_apiview(self):
        """Test throttle works in APIView."""
        from django_smart_ratelimit.integrations.drf import (
            UserRateLimitThrottle,
        )

        class TestView(APIView):
            throttle_classes = [UserRateLimitThrottle]

            def get(self, request):
                return Response({"message": "ok"})

        view = TestView.as_view()
        request = RequestFactory().get("/test/")
        request.user = self.user

        # Should work
        response = view(request)
        assert response.status_code == 200

    def test_throttle_in_viewset_integration(self):
        """Test throttle works with viewset actions."""
        from django_smart_ratelimit.integrations.drf import (
            UserRateLimitThrottle,
        )

        try:
            from rest_framework import viewsets
        except ImportError:
            self.skipTest("DRF viewsets not available")

        class TestViewSet(viewsets.ViewSet):
            throttle_classes = [UserRateLimitThrottle]

            def list(self, request):
                return Response([{"id": 1}])

        factory = RequestFactory()
        request = factory.get("/test/")
        request.user = self.user
        viewset = TestViewSet()

        response = viewset.list(request)
        assert response.status_code == 200
