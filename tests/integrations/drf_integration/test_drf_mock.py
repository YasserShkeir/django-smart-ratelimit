"""
Simple DRF integration tests without requiring DRF installation.

These tests use mocks to simulate DRF behavior and focus on verifying that
@rate_limit decorator wiring works for DRF-like call patterns even when DRF
is not installed. They intentionally avoid duplicating behavior covered by the
full DRF integration tests.
"""

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from django_smart_ratelimit import rate_limit
from tests.utils import create_test_staff_user, create_test_superuser, create_test_user


class DRFIntegrationMockTests(TestCase):
    """
    Minimal decorator wiring tests for DRF-like objects using mocks.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.user = create_test_user()
        cache.clear()

    def test_rate_limiting_decorator_with_mock_viewset(self):
        """Decorator works on a ViewSet-like class method (self, request)."""

        class MockViewSet:
            def __init__(self):
                self.action = "list"

            @rate_limit(key="user", rate="10/m")
            def list(self, _request):
                return {"message": "success", "data": []}

        viewset = MockViewSet()
        req = self.factory.get("/api/test/")
        req.user = self.user
        result = viewset.list(req)
        self.assertEqual(result["message"], "success")

    def test_rate_limiting_with_mock_apiview(self):
        """Decorator works on APIView-like instance methods for multiple verbs."""

        class MockAPIView:
            @rate_limit(key="ip", rate="5/m")
            def get(self, _request):
                return {"message": "get success"}

            @rate_limit(key="user", rate="3/m")
            def post(self, _request):
                return {"message": "post success"}

        view = MockAPIView()

        req = self.factory.get("/api/test/")
        req.user = self.user
        self.assertEqual(view.get(req)["message"], "get success")

        req = self.factory.post("/api/test/", {"data": "test"})
        req.user = self.user
        self.assertEqual(view.post(req)["message"], "post success")

    def test_custom_key_functions(self):
        """Custom key fns receive request and return user/ip based keys."""

        def user_or_ip_key(request, *args, **kwargs):
            if request.user.is_authenticated:
                return f"user:{request.user.id}"
            return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

        def user_role_key(request, *args, **kwargs):
            if request.user.is_authenticated:
                role = "staff" if request.user.is_staff else "user"
                return f"{request.user.id}:{role}"
            return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

        class MockView:
            @rate_limit(key=user_or_ip_key, rate="10/m")
            def get_with_user_or_ip(self, _request):
                return {"message": "success"}

            @rate_limit(key=user_role_key, rate="20/m")
            def get_with_user_role(self, _request):
                return {"message": "success"}

        view = MockView()

        req = self.factory.get("/api/test/")
        req.user = self.user
        self.assertEqual(view.get_with_user_or_ip(req)["message"], "success")

        staff_user = create_test_staff_user()
        req.user = staff_user
        self.assertEqual(view.get_with_user_role(req)["message"], "success")

    def test_mock_serializer_validation(self):
        """Serializer-like object can rate limit validation via request in context."""

        class MockSerializer:
            def __init__(self, data, context=None):
                self.data = data
                self.context = context or {}
                self.errors = {}

            def validate_title(self, value):
                _request = self.context.get("_request")
                if _request:
                    user_id = (
                        _request.user.id if _request.user.is_authenticated else "anon"
                    )
                    key = f"validation:{user_id}"
                    cnt = cache.get(key, 0)
                    if cnt >= 3:
                        raise ValueError("Too many validation requests")
                    cache.set(key, cnt + 1, 60)
                if len(value) < 3:
                    raise ValueError("Title too short")
                return value

            def is_valid(self):
                try:
                    self.validate_title(self.data.get("title", ""))
                    return True
                except ValueError as e:
                    self.errors["title"] = str(e)
                    return False

        req = self.factory.post("/api/test/")
        req.user = self.user

        self.assertTrue(
            MockSerializer({"title": "Valid Title"}, {"_request": req}).is_valid()
        )
        self.assertFalse(MockSerializer({"title": "ab"}, {"_request": req}).is_valid())

        for _ in range(3):
            MockSerializer({"title": "Test"}, {"_request": req}).is_valid()
        self.assertFalse(
            MockSerializer({"title": "Test"}, {"_request": req}).is_valid()
        )

    def test_bypass_conditions(self):
        """Common bypass conditions can be evaluated from request META and user."""

        def should_bypass_rate_limit(_request):
            if _request.user.is_superuser:
                return True
            if _request.META.get("HTTP_X_INTERNAL_API") == "true":
                return True
            ua = _request.META.get("HTTP_USER_AGENT", "")
            if "monitoring" in ua.lower():
                return True
            return False

        superuser = create_test_superuser()
        req = self.factory.get("/api/test/")
        req.user = superuser
        self.assertTrue(should_bypass_rate_limit(req))

        req = self.factory.get("/api/test/")
        req.user = self.user
        req.META["HTTP_X_INTERNAL_API"] = "true"
        self.assertTrue(should_bypass_rate_limit(req))

        req = self.factory.get("/api/test/")
        req.user = self.user
        req.META["HTTP_USER_AGENT"] = "monitoring-tool/1.0"
        self.assertTrue(should_bypass_rate_limit(req))

        req = self.factory.get("/api/test/")
        req.user = self.user
        self.assertFalse(should_bypass_rate_limit(req))
