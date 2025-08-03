"""
Tests for middleware and decorator interaction to prevent double-counting.

This module contains tests to ensure that when both middleware and decorator
are applied, they don't interfere with each other and provide consistent
rate limiting behavior.
"""

from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from django_smart_ratelimit.decorator import rate_limit
from django_smart_ratelimit.middleware import RateLimitMiddleware


class MiddlewareDecoratorInteractionTests(TestCase):
    """Test interaction between middleware and decorator."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()

    @patch("django_smart_ratelimit.decorator.get_backend")
    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_middleware_and_decorator_no_double_counting(
        self, mock_middleware_backend, mock_decorator_backend
    ):
        """Test that middleware and decorator don't double-count requests."""
        # Set up mock backends
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_backend.get_count.return_value = 1

        mock_middleware_backend.return_value = mock_backend
        mock_decorator_backend.return_value = mock_backend

        # Create a view with decorator
        @rate_limit(key="user", rate="10/m")
        def test_view(request):
            return HttpResponse("Success")

        # Set up middleware
        def get_response(request):
            return test_view(request)

        with override_settings(
            RATELIMIT_MIDDLEWARE={
                "DEFAULT_RATE": "100/h",
                "RATE_LIMITS": {"/api/": "50/h"},
            }
        ):
            middleware = RateLimitMiddleware(get_response)

            # Make a request through middleware
            request = self.factory.get("/api/test")
            request.user = Mock()
            request.user.is_authenticated = True
            request.user.id = 1

            response = middleware(request)

            # Verify response is successful
            self.assertEqual(response.status_code, 200)

            # Middleware should increment once
            self.assertEqual(mock_backend.incr.call_count, 1)

            # Decorator should call get_count (not incr) when middleware processed
            self.assertEqual(mock_backend.get_count.call_count, 1)

            # Verify middleware marked the request as processed
            self.assertTrue(getattr(request, "_ratelimit_middleware_processed", False))
            self.assertEqual(
                getattr(request, "_ratelimit_middleware_limit", None), 50
            )  # /api/ rate

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_only_normal_behavior(self, mock_get_backend):
        """Test that decorator works normally when middleware hasn't processed request."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="user", rate="10/m")
        def test_view(request):
            return HttpResponse("Success")

        request = self.factory.get("/test")
        request.user = Mock()
        request.user.is_authenticated = True
        request.user.id = 1

        response = test_view(request)

        # Verify response is successful
        self.assertEqual(response.status_code, 200)

        # Decorator should increment normally
        mock_backend.incr.assert_called_once()

        # Should not call get_count when middleware hasn't processed
        mock_backend.get_count.assert_not_called()

    @patch("django_smart_ratelimit.decorator.get_backend")
    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_more_restrictive_decorator_limit_enforced(
        self, mock_middleware_backend, mock_decorator_backend
    ):
        """Test that more restrictive decorator limit is enforced over middleware."""
        # Set up mock backends
        mock_backend = Mock()
        mock_backend.incr.return_value = 5  # 5 requests made
        mock_backend.get_count.return_value = 5

        mock_middleware_backend.return_value = mock_backend
        mock_decorator_backend.return_value = mock_backend

        # Create a view with very restrictive decorator limit
        @rate_limit(key="user", rate="3/m")  # Only 3 requests per minute
        def test_view(request):
            return HttpResponse("Success")

        # Set up middleware with higher limit
        def get_response(request):
            return test_view(request)

        with override_settings(
            RATELIMIT_MIDDLEWARE={
                "DEFAULT_RATE": "100/h",  # 100 per hour = ~1.67 per minute
            }
        ):
            middleware = RateLimitMiddleware(get_response)

            request = self.factory.get("/test")
            request.user = Mock()
            request.user.is_authenticated = True
            request.user.id = 1

            response = middleware(request)

            # Should be rate limited by decorator (5 > 3)
            self.assertEqual(response.status_code, 429)

            # Verify middleware incremented
            self.assertEqual(mock_backend.incr.call_count, 1)

            # Verify decorator checked count without incrementing
            self.assertEqual(mock_backend.get_count.call_count, 1)

    @patch("django_smart_ratelimit.decorator.get_backend")
    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_header_consistency_with_both_applied(
        self, mock_middleware_backend, mock_decorator_backend
    ):
        """Test that headers show consistent information when both are applied."""
        # Set up mock backends
        mock_backend = Mock()
        mock_backend.incr.return_value = 2  # 2 requests made
        mock_backend.get_count.return_value = 2

        mock_middleware_backend.return_value = mock_backend
        mock_decorator_backend.return_value = mock_backend

        @rate_limit(key="user", rate="5/m")  # 5 per minute
        def test_view(request):
            return HttpResponse("Success")

        def get_response(request):
            return test_view(request)

        with override_settings(
            RATELIMIT_MIDDLEWARE={
                "DEFAULT_RATE": "100/h",  # ~1.67 per minute, more permissive
            }
        ):
            middleware = RateLimitMiddleware(get_response)

            request = self.factory.get("/test")
            request.user = Mock()
            request.user.is_authenticated = True
            request.user.id = 1

            response = middleware(request)

            self.assertEqual(response.status_code, 200)

            # Headers should reflect the more restrictive decorator limit
            self.assertIn("X-RateLimit-Limit", response.headers)
            # The effective limit should be the minimum of both limits
            # But headers should be clear about what limit is being enforced

            # Verify that remaining count makes sense
            remaining = int(response.headers.get("X-RateLimit-Remaining", 0))
            self.assertGreaterEqual(remaining, 0)
            self.assertLessEqual(remaining, 5)  # Should not exceed decorator limit

    def test_middleware_skip_paths_not_processed_by_decorator(self):
        """Test that skipped paths are properly handled."""

        @rate_limit(key="user", rate="5/m")
        def test_view(request):
            return HttpResponse("Success")

        def get_response(request):
            return test_view(request)

        with override_settings(
            RATELIMIT_MIDDLEWARE={
                "SKIP_PATHS": ["/admin/", "/health/"],
            }
        ):
            middleware = RateLimitMiddleware(get_response)

            request = self.factory.get("/admin/users/")
            request.user = Mock()
            request.user.is_authenticated = True
            request.user.id = 1

            response = middleware(request)

            self.assertEqual(response.status_code, 200)

            # Request should not be marked as processed by middleware
            self.assertFalse(getattr(request, "_ratelimit_middleware_processed", False))

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_browser_secondary_requests_are_skipped(self, mock_get_backend):
        """Test that browser secondary requests don't count towards rate limit."""
        mock_backend = Mock()
        mock_backend.incr.return_value = 1
        mock_get_backend.return_value = mock_backend

        # Decorator that skips browser secondary requests (like the user's issue)
        @rate_limit(
            key="ip",
            rate="10/m",
            skip_if=lambda req: (
                req.path in ["/favicon.ico", "/robots.txt"]
                or req.path.startswith("/static/")
                or req.method in ["OPTIONS", "HEAD"]
            ),
        )
        def test_view(request):
            return HttpResponse("Success")

        # Test main request - should be counted
        request = self.factory.get("/api/test")
        response = test_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_backend.incr.call_count, 1)

        # Test favicon request - should be skipped
        favicon_request = self.factory.get("/favicon.ico")
        response = test_view(favicon_request)
        self.assertEqual(response.status_code, 200)
        # Should still be 1, not incremented
        self.assertEqual(mock_backend.incr.call_count, 1)

        # Test OPTIONS request - should be skipped
        options_request = self.factory.options("/api/test")
        response = test_view(options_request)
        self.assertEqual(response.status_code, 200)
        # Should still be 1, not incremented
        self.assertEqual(mock_backend.incr.call_count, 1)

    @patch("django_smart_ratelimit.decorator.get_backend")
    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_user_issue_scenario_count_increases_by_multiple(
        self, mock_middleware_backend, mock_decorator_backend
    ):
        """Test the specific user issue: count increasing by 2-3 per request."""
        # Set up mock backends
        mock_backend = Mock()
        # Simulate what was happening: count going up by 2-3 per "single" request
        call_count = 0

        def mock_incr(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return call_count

        mock_backend.incr.side_effect = mock_incr
        mock_backend.get_count.return_value = 1

        mock_middleware_backend.return_value = mock_backend
        mock_decorator_backend.return_value = mock_backend

        # Create a view with decorator (user's setup)
        @rate_limit(key="ip", rate="10/m")
        def test_view(request):
            return HttpResponse("Success")

        # Set up middleware (user had both)
        def get_response(request):
            return test_view(request)

        with override_settings(
            RATELIMIT_MIDDLEWARE={
                "DEFAULT_RATE": "100/h",
                "RATE_LIMITS": {"/api/": "100/h"},
            }
        ):
            middleware = RateLimitMiddleware(get_response)

            # Before fix: This would increment twice (middleware + decorator)
            # After fix: Should only increment once (middleware marks request)
            request = self.factory.get("/api/test")
            response = middleware(request)

            self.assertEqual(response.status_code, 200)

            # After fix: Only middleware should increment, decorator should use get_count
            self.assertEqual(
                mock_backend.incr.call_count, 1
            )  # Only middleware increments
            self.assertEqual(
                mock_backend.get_count.call_count, 1
            )  # Decorator uses get_count

    @patch("django_smart_ratelimit.decorator.get_backend")
    @patch("django_smart_ratelimit.middleware.get_backend")
    def test_user_issue_scenario_header_mismatch(
        self, mock_middleware_backend, mock_decorator_backend
    ):
        """Test the specific user issue: headers showing wrong values despite view overrides."""
        # Set up mock backends
        mock_backend = Mock()
        mock_backend.incr.return_value = 5  # 5 requests made
        mock_backend.get_count.return_value = 5

        mock_middleware_backend.return_value = mock_backend
        mock_decorator_backend.return_value = mock_backend

        # User's scenario: decorator set to 10/m, middleware set to 100/h
        @rate_limit(key="ip", rate="10/m")  # User's view override
        def test_view(request):
            return HttpResponse("Success")

        def get_response(request):
            return test_view(request)

        with override_settings(
            RATELIMIT_MIDDLEWARE={
                "DEFAULT_RATE": "600/h",  # User mentioned limit of 600
                "RATE_LIMITS": {"/api/": "100/h"},
            }
        ):
            middleware = RateLimitMiddleware(get_response)

            request = self.factory.get("/api/test")
            response = middleware(request)

            # Should show decorator's limit in headers (10), not middleware's (100)
            self.assertEqual(response["X-RateLimit-Limit"], "10")
            self.assertEqual(response["X-RateLimit-Remaining"], "5")  # 10 - 5 = 5
