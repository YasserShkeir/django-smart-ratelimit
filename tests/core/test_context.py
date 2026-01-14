"""Tests for RateLimitContext object and integration."""

from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from django_smart_ratelimit.context import RateLimitContext
from django_smart_ratelimit.decorator import rate_limit
from tests.utils import BaseBackendTestCase, create_test_user


class TestRateLimitContext(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = create_test_user()

    def test_context_properties(self):
        """Test properties of RateLimitContext."""
        request = self.factory.get("/", REMOTE_ADDR="127.0.0.1")
        request.user = self.user

        ctx = RateLimitContext(request=request)

        self.assertEqual(ctx.client_ip, "127.0.0.1")
        self.assertEqual(ctx.user_id, str(self.user.pk))

    def test_context_to_headers(self):
        """Test conversion to headers."""
        request = self.factory.get("/")
        ctx = RateLimitContext(
            request=request,
            limit=100,
            allowed=True,
            current_count=50,
            remaining=50,
            reset_time=1234567890.5,
        )

        headers = ctx.to_headers()
        self.assertEqual(headers["X-RateLimit-Limit"], "100")
        self.assertEqual(headers["X-RateLimit-Remaining"], "50")
        self.assertEqual(headers["X-RateLimit-Reset"], "1234567890")


class TestRateLimitContextIntegration(BaseBackendTestCase):
    """Tests for integration of context into views."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_view_access_to_context(self, mock_get_backend):
        """Test that views can access request.ratelimit context."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        # Set increment for new refactor
        mock_backend.increment.return_value = (1, 9)
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="ip", rate="10/m")
        def my_view(request):
            self.assertTrue(hasattr(request, "ratelimit"))
            self.assertIsInstance(request.ratelimit, RateLimitContext)
            self.assertEqual(request.ratelimit.limit, 10)
            self.assertEqual(request.ratelimit.remaining, 9)
            return HttpResponse("OK")

        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        response = my_view(request)
        self.assertEqual(response.status_code, 200)
