from unittest.mock import Mock

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from django_smart_ratelimit.utils import (
    add_rate_limit_headers,
    add_token_bucket_headers,
    debug_ratelimit_status,
    format_debug_info,
    is_exempt_request,
    load_function_from_string,
    should_skip_static_media,
)


class UtilsCoverageTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(
        RATELIMIT_BACKEND="django_smart_ratelimit.backends.memory.MemoryBackend"
    )
    def test_debug_ratelimit_status(self):
        request = self.factory.get("/test")
        # Mock user
        request.user = Mock()
        request.user.is_authenticated = True
        request.user.pk = 999
        request.user.id = 999

        info = debug_ratelimit_status(request)

        self.assertEqual(info["request_path"], "/test")
        self.assertTrue(info["user_authenticated"])
        self.assertIn("backend_counts", info)
        self.assertIn("user", info["backend_counts"])
        self.assertIn("ip", info["backend_counts"])

    def test_format_debug_info(self):
        info = {
            "request_path": "/api",
            "request_method": "GET",
            "user_authenticated": True,
            "user_id": 123,
            "remote_addr": "1.2.3.4",
            "middleware_processed": True,
            "middleware_limit": "10/m",
            "middleware_remaining": 9,
            "backend_counts": {"ip": {"key": "ip:1.2.3.4", "count": 1}},
            "backend_type": "MemoryBackend",
        }

        output = format_debug_info(info)
        self.assertIn("Path: /api", output)
        self.assertIn("User: Authenticated", output)
        self.assertIn("User ID: 123", output)
        self.assertIn("ip: 1", output)

    def test_is_exempt_request(self):
        req = self.factory.get("/exempt")

        # Test path exemption
        self.assertTrue(is_exempt_request(req, exempt_paths=["/exempt"]))
        self.assertFalse(is_exempt_request(req, exempt_paths=["/other"]))

        # Test IP exemption
        req_ip = self.factory.get("/", REMOTE_ADDR="192.168.1.1")
        self.assertTrue(is_exempt_request(req_ip, exempt_ips=["192.168.1.1"]))
        self.assertFalse(is_exempt_request(req_ip, exempt_ips=["10.0.0.1"]))

    def test_load_function_from_string(self):
        func = load_function_from_string(
            "django_smart_ratelimit.utils.is_exempt_request"
        )
        self.assertEqual(func, is_exempt_request)

        with self.assertRaises(ImproperlyConfigured):
            load_function_from_string("invalid.module.function")

    @override_settings(STATIC_URL="/static/", MEDIA_URL="/media/")
    def test_should_skip_static_media(self):
        req_static = self.factory.get("/static/css/style.css")
        self.assertTrue(should_skip_static_media(req_static))

        req_media = self.factory.get("/media/images/photo.jpg")
        self.assertTrue(should_skip_static_media(req_media))

        req_normal = self.factory.get("/api/v1/")
        self.assertFalse(should_skip_static_media(req_normal))

    def test_add_rate_limit_headers_retry_after(self):
        response = HttpResponse()
        # Mock 429
        response.status_code = 429

        add_rate_limit_headers(response, limit=10, remaining=0, period=60)

        self.assertIn("Retry-After", response.headers)
        self.assertEqual(response.headers["Retry-After"], "60")

    def test_add_token_bucket_headers(self):
        response = HttpResponse()
        metadata = {"tokens_remaining": 5, "bucket_size": 10, "refill_rate": 2.5}
        add_token_bucket_headers(response, metadata, limit=10, period=60)

        self.assertEqual(response.headers["X-RateLimit-Bucket-Size"], "10")
        self.assertEqual(response.headers["X-RateLimit-Bucket-Remaining"], "5")
        self.assertEqual(response.headers["X-RateLimit-Refill-Rate"], "2.50")
