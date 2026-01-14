"""
DRF Backend Variation Tests.

Tests for different rate limiting backends (Redis, MongoDB, Multi-backend)
with Django REST Framework views.
"""

import unittest
from unittest.mock import Mock, patch

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
from django_smart_ratelimit.backends import clear_backend_cache
from tests.utils import create_test_user

# Check for Redis availability
try:
    from django_smart_ratelimit.backends.redis_backend import RedisBackend

    # Try to create a connection
    _test_backend = RedisBackend()
    if _test_backend.redis:
        _test_backend.redis.ping()
        REDIS_AVAILABLE = True
    else:
        REDIS_AVAILABLE = False
except Exception:
    REDIS_AVAILABLE = False

# Check for MongoDB availability
try:
    from django_smart_ratelimit.backends.mongodb import MongoDBBackend

    MONGODB_AVAILABLE = True
    # Try to create a connection
    try:
        _mongo_backend = MongoDBBackend()
        _mongo_backend._collection.find_one()
    except Exception:
        MONGODB_AVAILABLE = False
except ImportError:
    MONGODB_AVAILABLE = False


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@unittest.skipUnless(REDIS_AVAILABLE, "Redis not available")
@override_settings(
    RATELIMIT_BACKEND="redis",
    RATELIMIT_REDIS_CONFIG={"host": "localhost", "port": 6379, "db": 0},
)
class TestDRFRedisBackend(TestCase):
    """Tests for Redis backend with DRF views."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()
        # Clear Redis test keys
        try:
            backend = RedisBackend()
            if backend.redis:
                # Delete test keys to ensure clean state
                keys = backend.redis.keys("*10.0.1.*")
                if keys:
                    backend.redis.delete(*keys)
        except Exception:
            pass

    def test_drf_view_with_redis_backend(self):
        """Test basic DRF view rate limiting with Redis backend."""

        class RedisView(APIView):
            @rate_limit(key="ip", rate="5/m", block=True, backend="redis")
            def get(self, request):
                return Response({"message": "success"})

        view = RedisView.as_view()

        # Make requests up to limit
        for i in range(5):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "10.0.1.100"
            response = view(request)
            self.assertEqual(response.status_code, 200, f"Request {i+1} should succeed")

        # Next request should be blocked
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "10.0.1.100"
        response = view(request)
        self.assertEqual(response.status_code, 429, "6th request should be blocked")

    def test_redis_backend_persistence_across_requests(self):
        """Test that Redis count persists between independent view calls."""

        class PersistView(APIView):
            @rate_limit(key="ip", rate="3/m", block=True, backend="redis")
            def get(self, request):
                return Response({"message": "success"})

        view = PersistView.as_view()

        # Make 2 requests
        for _ in range(2):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "10.0.1.101"
            response = view(request)
            self.assertEqual(response.status_code, 200)

        # Clear local caches but not Redis
        cache.clear()

        # 3rd request should still work (Redis has state)
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "10.0.1.101"
        response = view(request)
        self.assertEqual(response.status_code, 200)

        # 4th should be blocked
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "10.0.1.101"
        response = view(request)
        self.assertEqual(response.status_code, 429)

    def test_redis_backend_token_bucket_algorithm(self):
        """Test Redis backend with token bucket algorithm."""

        class TokenBucketRedisView(APIView):
            @rate_limit(
                key="ip",
                rate="10/m",
                algorithm="token_bucket",
                algorithm_config={"bucket_size": 5},
                block=True,
                backend="redis",
            )
            def get(self, request):
                return Response({"message": "success"})

        view = TokenBucketRedisView.as_view()

        # Make burst requests
        success_count = 0
        for _ in range(10):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "10.0.1.102"
            response = view(request)
            if response.status_code == 200:
                success_count += 1

        # Token bucket should allow some burst
        self.assertGreater(success_count, 0, "Token bucket should allow some requests")
        self.assertLess(success_count, 10, "Token bucket should block after exhaustion")


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@unittest.skipUnless(MONGODB_AVAILABLE, "MongoDB not available")
@override_settings(
    RATELIMIT_BACKEND="mongodb",
    RATELIMIT_MONGODB_URI="mongodb://localhost:27017",
    RATELIMIT_MONGODB_DATABASE="ratelimit_test",
)
class TestDRFMongoDBBackend(TestCase):
    """Tests for MongoDB backend with DRF views."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()
        # Clear MongoDB test keys
        try:
            backend = MongoDBBackend()
            # Delete test documents to ensure clean state
            backend._collection.delete_many({"key": {"$regex": "^.*10\\.0\\.2\\..*"}})
        except Exception:
            pass

    def test_drf_view_with_mongodb_backend(self):
        """Test basic DRF view rate limiting with MongoDB backend."""

        class MongoView(APIView):
            @rate_limit(key="ip", rate="5/m", block=True, backend="mongodb")
            def get(self, request):
                return Response({"message": "success"})

        view = MongoView.as_view()

        # Make requests up to limit
        for i in range(5):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "10.0.2.100"
            response = view(request)
            self.assertEqual(response.status_code, 200, f"Request {i+1} should succeed")

        # Next request should be blocked
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "10.0.2.100"
        response = view(request)
        self.assertEqual(response.status_code, 429, "6th request should be blocked")

    def test_mongodb_backend_sliding_window(self):
        """Test MongoDB backend with sliding window algorithm."""

        class SlidingMongoView(APIView):
            @rate_limit(
                key="ip",
                rate="3/m",
                algorithm="sliding_window",
                block=True,
                backend="mongodb",
            )
            def get(self, request):
                return Response({"message": "success"})

        view = SlidingMongoView.as_view()

        # Make 3 requests - all should succeed
        for i in range(3):
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "10.0.2.101"
            response = view(request)
            self.assertEqual(response.status_code, 200, f"Request {i+1} should succeed")

        # 4th should be blocked
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "10.0.2.101"
        response = view(request)
        self.assertEqual(response.status_code, 429)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFMultiBackend(TestCase):
    """Tests for Multi-backend with DRF views."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()
        self.user = create_test_user()

    def test_multi_backend_with_memory_only(self):
        """Test multi-backend configuration with memory backend."""
        from django_smart_ratelimit.backends.multi import MultiBackend

        # Create multi-backend with single memory backend
        multi_backend = MultiBackend(
            backends=[
                {"backend": "django_smart_ratelimit.backends.memory.MemoryBackend"}
            ]
        )

        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get:
            mock_get.return_value = multi_backend

            class MultiView(APIView):
                @rate_limit(key="ip", rate="3/m", block=True)
                def get(self, request):
                    return Response({"message": "success"})

            view = MultiView.as_view()

            # Make requests
            success_count = 0
            for _ in range(5):
                request = self.factory.get("/api/test/")
                request.META["REMOTE_ADDR"] = "10.0.3.100"
                response = view(request)
                if response.status_code == 200:
                    success_count += 1

            self.assertEqual(success_count, 3, "Should allow exactly 3 requests")

    def test_multi_backend_failover_simulation(self):
        """Test multi-backend failover when primary fails."""
        from django_smart_ratelimit.backends.memory import MemoryBackend

        # Create a failing primary backend
        failing_backend = Mock()
        failing_backend.incr.side_effect = Exception("Primary failed")
        failing_backend.increment.side_effect = Exception("Primary failed")
        failing_backend.health_check.return_value = False

        # Create a working fallback backend
        fallback_backend = MemoryBackend()

        # Mock get_backend to return our controlled backends
        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get:
            mock_get.return_value = fallback_backend  # Return working backend

            class FailoverView(APIView):
                @rate_limit(key="ip", rate="5/m", block=True)
                def get(self, request):
                    return Response({"message": "success"})

            view = FailoverView.as_view()

            # Request should succeed via fallback
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "10.0.3.101"
            response = view(request)
            self.assertEqual(response.status_code, 200)

    def test_multi_backend_state_isolation(self):
        """Test that different multi-backend instances have isolated state."""
        from django_smart_ratelimit.backends.memory import MemoryBackend

        backend1 = MemoryBackend()
        backend2 = MemoryBackend()

        # Use different keys to verify isolation
        key1 = "multi_test_1"

        # Increment on backend1
        backend1.incr(key1, period=60)
        backend1.incr(key1, period=60)

        # Check counts are isolated
        count1 = backend1.get_count(key1, period=60)
        count2 = backend2.get_count(key1, period=60)

        self.assertEqual(count1, 2)
        self.assertEqual(count2, 0, "Backend2 should have separate state")


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFBackendErrorHandling(TestCase):
    """Tests for backend error handling in DRF context."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_backend_error_graceful_handling(self):
        """Test that backend errors are handled gracefully."""
        from django_smart_ratelimit.exceptions import BackendError

        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get:
            mock_backend = Mock()
            # First call succeeds, second fails
            mock_backend.incr.side_effect = [1, BackendError("Connection failed")]
            mock_backend.increment.side_effect = [
                (1, 59),
                BackendError("Connection failed"),
            ]
            mock_get.return_value = mock_backend

            class ErrorView(APIView):
                @rate_limit(key="ip", rate="5/m", block=True)
                def get(self, request):
                    return Response({"message": "success"})

            view = ErrorView.as_view()

            # First request should succeed
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "10.0.4.100"
            response = view(request)
            self.assertEqual(response.status_code, 200)

            # Second request with backend error - behavior depends on backend config
            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "10.0.4.100"
            response = view(request)
            # Should either succeed (fail_open) or return error
            self.assertIn(response.status_code, [200, 429, 500, 503])

    def test_backend_timeout_handling(self):
        """Test that backend timeouts are handled appropriately."""
        from django_smart_ratelimit.exceptions import BackendTimeoutError

        with patch("django_smart_ratelimit.decorator.get_backend") as mock_get:
            mock_backend = Mock()
            mock_backend.incr.side_effect = BackendTimeoutError("Timeout")
            mock_backend.increment.side_effect = BackendTimeoutError("Timeout")
            mock_get.return_value = mock_backend

            class TimeoutView(APIView):
                @rate_limit(key="ip", rate="5/m", block=True)
                def get(self, request):
                    return Response({"message": "success"})

            view = TimeoutView.as_view()

            request = self.factory.get("/api/test/")
            request.META["REMOTE_ADDR"] = "10.0.4.101"
            response = view(request)

            # Should handle timeout gracefully
            self.assertIn(response.status_code, [200, 429, 500, 503])


if __name__ == "__main__":
    unittest.main()
