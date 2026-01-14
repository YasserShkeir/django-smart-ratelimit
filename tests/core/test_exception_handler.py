from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from django_smart_ratelimit.decorator import rate_limit
from django_smart_ratelimit.exceptions import BackendError
from django_smart_ratelimit.messages import ERROR_RATE_LIMIT_EXCEEDED


def custom_exception_handler(request, exception):
    return HttpResponse("Custom Error", status=500)


class TestExceptionHandler(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_default_exception_handler(self, mock_get_backend):
        # Setup backend to raise BackendError
        mock_backend = Mock()
        mock_backend.incr.side_effect = BackendError("Backend failed")
        mock_backend.increment.side_effect = BackendError("Backend failed")
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="ip", rate="5/m")
        def my_view(request):
            return HttpResponse("OK")

        request = self.factory.get("/")
        response = my_view(request)

        # Should return 429 by default
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.content.decode(), ERROR_RATE_LIMIT_EXCEEDED)

    @override_settings(
        RATELIMIT_EXCEPTION_HANDLER="tests.core.test_exception_handler.custom_exception_handler"
    )
    @patch("django_smart_ratelimit.decorator.get_backend")
    def test_custom_exception_handler(self, mock_get_backend):
        # Setup backend to raise BackendError
        mock_backend = Mock()
        mock_backend.incr.side_effect = BackendError("Backend failed")
        mock_backend.increment.side_effect = BackendError("Backend failed")
        mock_get_backend.return_value = mock_backend

        @rate_limit(key="ip", rate="5/m")
        def my_view(request):
            return HttpResponse("OK")

        request = self.factory.get("/")
        response = my_view(request)

        # Should return 500 from custom handler
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.content.decode(), "Custom Error")
