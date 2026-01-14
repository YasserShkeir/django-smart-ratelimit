from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from django_smart_ratelimit.backends.memory import MemoryBackend
from django_smart_ratelimit.decorator import rate_limit
from django_smart_ratelimit.exceptions import BackendError, RateLimitException
from django_smart_ratelimit.middleware import RateLimitMiddleware


def custom_exception_handler(request, exception):
    """Custom exception handler for testing."""
    request.exception_handled = True
    request.handled_exception = exception
    return HttpResponse("Handled", status=503)


class ErrorHandlingTests(TestCase):
    """Tests for standardized error handling and fail-open behavior."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_backend_error_hierarchy(self):
        """Test that BackendError inherits from RateLimitException."""
        err = BackendError("Test error")
        self.assertIsInstance(err, RateLimitException)
        self.assertIsInstance(err, Exception)

    def test_fail_open_behavior_backend_level(self):
        """Test that fail_open=True suppresses exceptions and allows requests at backend level."""
        backend = MemoryBackend(fail_open=True)

        # Patch normalize_key to simulate an internal error
        with patch(
            "django_smart_ratelimit.backends.memory.normalize_key",
            side_effect=Exception("Normalization failed"),
        ):
            # fail_open=True: Should return 0 (allowed) and NOT raise
            count = backend.incr("key", 60)
            self.assertEqual(count, 0)

            # fail_open=False: Should RAISE BackendError
            backend.fail_open = False
            with self.assertRaises(BackendError):
                backend.incr("key", 60)

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_decorator_fail_open_behavior(self, mock_get_backend):
        """
        Verify that when fail_open is True (implemented by backend returning 0/Safe),
        the request is allowed.
        """
        # Scenario: Backend configured to fail open catches internal error and returns 0 keys
        mock_backend = Mock()
        mock_backend.incr.return_value = 0
        mock_backend.increment.return_value = (0, 100)
        mock_backend.get_reset_time.return_value = 0
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="test", rate="10/m", block=True)
        def my_view(request):
            return HttpResponse("OK")

        request = self.factory.get("/")
        response = my_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")

    @patch("django_smart_ratelimit.decorator.get_backend")
    @patch("django_smart_ratelimit.decorator.get_exception_handler")
    def test_decorator_fail_closed_behavior_caught(
        self, mock_get_handler, mock_get_backend
    ):
        """
        Verify that when backend raises BackendError (fail_open=False),
        the decorator catches it and invokes the exception handler.
        """
        mock_backend = Mock()
        mock_backend.incr.side_effect = BackendError("Connection Refused")
        mock_backend.increment.side_effect = BackendError("Connection Refused")
        mock_get_backend.return_value = mock_backend

        # Mock handler to return specific 503
        mock_response = HttpResponse("Service Unavailable", status=503)
        mock_handler = Mock(return_value=mock_response)
        mock_get_handler.return_value = mock_handler

        @rate_limit(key="test", rate="10/m", block=True)
        def my_view(request):
            return HttpResponse("OK")

        request = self.factory.get("/")
        response = my_view(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b"Service Unavailable")
        mock_handler.assert_called_once()
        args, _ = mock_handler.call_args
        self.assertIsInstance(args[1], BackendError)

    @patch("django_smart_ratelimit.middleware.get_backend")
    @patch("django_smart_ratelimit.middleware.get_exception_handler")
    def test_middleware_error_handling(self, mock_get_handler, mock_get_backend):
        """
        Test that middleware catches BackendError and delegates to handler.
        """
        mock_backend = Mock()
        mock_backend.incr.side_effect = BackendError("DB Down")
        mock_get_backend.return_value = mock_backend

        mock_response = HttpResponse("Middleware Error", status=500)
        mock_handler = Mock(return_value=mock_response)
        mock_get_handler.return_value = mock_handler

        # Middleware setup
        def get_response(req):
            return HttpResponse("OK")

        middleware = RateLimitMiddleware(get_response)

        request = self.factory.get("/")
        response = middleware(request)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.content, b"Middleware Error")
