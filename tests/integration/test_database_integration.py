"""Integration tests for DatabaseBackend.

These tests verify the database backend works correctly in real-world
scenarios with actual database connections.

Tests cover:
- Fixed window and sliding window algorithms
- Token bucket algorithm
- Decorator integration
- Middleware integration
- SQLite (runs by default)
- PostgreSQL (requires Docker or external database)
- MySQL (requires Docker or external database)
"""

import os
from datetime import timedelta
from unittest.mock import patch

import pytest

from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from django.utils import timezone

# Check database availability
POSTGRES_AVAILABLE = os.environ.get("DATABASE_URL", "").startswith("postgres")
MYSQL_AVAILABLE = os.environ.get("DATABASE_URL", "").startswith("mysql")


@pytest.fixture
def database_backend():
    """Create a DatabaseBackend for testing."""
    from django_smart_ratelimit.backends.database import DatabaseBackend

    backend = DatabaseBackend(
        algorithm="fixed_window",
        enable_background_cleanup=False,
        enable_circuit_breaker=False,
    )
    yield backend
    backend.clear_all()
    backend.shutdown()


@pytest.fixture
def sliding_backend():
    """Create a DatabaseBackend with sliding window algorithm."""
    from django_smart_ratelimit.backends.database import DatabaseBackend

    backend = DatabaseBackend(
        algorithm="sliding_window",
        enable_background_cleanup=False,
        enable_circuit_breaker=False,
    )
    yield backend
    backend.clear_all()
    backend.shutdown()


@pytest.fixture
def request_factory():
    """Create a request factory for testing."""
    return RequestFactory()


@pytest.mark.django_db(transaction=True)
class TestDatabaseIntegrationBasic:
    """Basic integration tests that work with SQLite."""

    def test_fixed_window_rate_limiting(self, database_backend):
        """Test fixed window rate limiting end-to-end."""
        key = "integration:fixed:1"
        limit = 5
        period = 60

        # Make requests up to limit
        for i in range(limit):
            allowed, metadata = database_backend.check_rate_limit(key, limit, period)
            assert allowed is True, f"Request {i+1} should be allowed"
            assert metadata["remaining"] == limit - (i + 1)

        # Next request should be blocked
        allowed, metadata = database_backend.check_rate_limit(key, limit, period)
        assert allowed is False, "Request over limit should be blocked"
        assert metadata["remaining"] == 0

    def test_sliding_window_rate_limiting(self, sliding_backend):
        """Test sliding window rate limiting end-to-end."""
        key = "integration:sliding:1"
        limit = 5
        period = 60

        # Make requests up to limit
        for i in range(limit):
            allowed, metadata = sliding_backend.check_rate_limit(key, limit, period)
            assert allowed is True, f"Request {i+1} should be allowed"

        # Next request should be blocked
        allowed, metadata = sliding_backend.check_rate_limit(key, limit, period)
        assert allowed is False, "Request over limit should be blocked"

    def test_token_bucket_rate_limiting(self, database_backend):
        """Test token bucket rate limiting end-to-end."""
        key = "integration:bucket:1"

        # Full bucket with 10 tokens
        allowed, metadata = database_backend.token_bucket_check(
            key, bucket_size=10, refill_rate=1.0, initial_tokens=10, tokens_requested=5
        )
        assert allowed is True
        assert metadata["tokens_remaining"] == 5

        # Request 5 more
        allowed, metadata = database_backend.token_bucket_check(
            key, bucket_size=10, refill_rate=1.0, initial_tokens=10, tokens_requested=5
        )
        assert allowed is True
        assert metadata["tokens_remaining"] <= 1  # Might have refilled a tiny bit

        # Request 5 more should fail (not enough tokens)
        allowed, metadata = database_backend.token_bucket_check(
            key, bucket_size=10, refill_rate=1.0, initial_tokens=10, tokens_requested=5
        )
        assert allowed is False

    def test_multiple_keys_isolation(self, database_backend):
        """Test that different keys are isolated."""
        key1 = "integration:isolated:1"
        key2 = "integration:isolated:2"

        # Fill up key1
        for _ in range(5):
            database_backend.incr(key1, 60)

        # Key1 should be at limit
        assert database_backend.get_count(key1, 60) == 5

        # Key2 should be independent
        assert database_backend.get_count(key2, 60) == 0
        database_backend.incr(key2, 60)
        assert database_backend.get_count(key2, 60) == 1

    def test_reset_functionality(self, database_backend):
        """Test that reset clears rate limit data."""
        key = "integration:reset:1"

        # Fill up
        for _ in range(5):
            database_backend.incr(key, 60)
        assert database_backend.get_count(key, 60) == 5

        # Reset
        database_backend.reset(key)
        assert database_backend.get_count(key, 60) == 0

        # Should be able to make requests again
        database_backend.incr(key, 60)
        assert database_backend.get_count(key, 60) == 1

    def test_cleanup_removes_expired(self, database_backend):
        """Test that cleanup removes expired entries."""
        from django_smart_ratelimit.models import RateLimitCounter

        now = timezone.now()

        # Create expired counter directly
        RateLimitCounter.objects.create(
            key="integration:expired:1",
            count=5,
            window_start=now - timedelta(hours=2),
            window_end=now - timedelta(hours=1),
        )

        # Create active counter
        RateLimitCounter.objects.create(
            key="integration:active:1",
            count=3,
            window_start=now,
            window_end=now + timedelta(hours=1),
        )

        # Run cleanup
        deleted = database_backend.cleanup_expired()

        # Expired should be deleted
        assert deleted["counters"] >= 1
        assert not RateLimitCounter.objects.filter(key="integration:expired:1").exists()
        assert RateLimitCounter.objects.filter(key="integration:active:1").exists()


@pytest.mark.django_db(transaction=True)
class TestDecoratorIntegration:
    """Test database backend integration with rate limit decorator."""

    def test_decorator_with_database_backend(self, database_backend):
        """Test rate limit decorator uses database backend."""
        from django_smart_ratelimit.decorator import rate_limit

        # Create a simple view with block=True to get 429 response
        @rate_limit(rate="3/m", key="ip", block=True)
        def test_view(request):
            return HttpResponse("OK")

        # Create a mock request
        request = HttpRequest()
        request.META = {"REMOTE_ADDR": "192.168.1.100"}

        # Patch get_backend to return our database backend
        with patch(
            "django_smart_ratelimit.decorator.get_backend",
            return_value=database_backend,
        ):
            # Make requests up to limit
            for i in range(3):
                response = test_view(request)
                assert response.status_code == 200

            # 4th request should return 429
            response = test_view(request)
            assert response.status_code == 429

    def test_decorator_block_mode(self, database_backend):
        """Test decorator with block=True returns 429."""
        from django_smart_ratelimit.decorator import rate_limit

        @rate_limit(rate="2/m", key="ip", block=True)
        def blocked_view(request):
            return HttpResponse("OK")

        request = HttpRequest()
        request.META = {"REMOTE_ADDR": "192.168.1.101"}

        with patch(
            "django_smart_ratelimit.decorator.get_backend",
            return_value=database_backend,
        ):
            # Make allowed requests
            blocked_view(request)
            blocked_view(request)

            # 3rd request should return 429
            response = blocked_view(request)
            assert response.status_code == 429


@pytest.mark.django_db(transaction=True)
class TestHealthAndStats:
    """Test health check and statistics with real database."""

    def test_health_check_returns_healthy(self, database_backend):
        """Test health check returns healthy status."""
        health = database_backend.health_check()

        assert health["status"] == "healthy"
        assert health["response_time"] >= 0
        assert "database_vendor" in health

    def test_stats_reflect_actual_data(self, database_backend):
        """Test that stats reflect actual database state."""
        # Create some data
        database_backend.incr("stats:test:1", 60)
        database_backend.incr("stats:test:2", 60)
        database_backend.token_bucket_check("stats:bucket:1", 100, 10.0, 100, 1)

        stats = database_backend.get_stats()

        assert stats["active_counters"] >= 2
        assert stats["token_buckets"] >= 1
        assert stats["total_records"] >= 3


@pytest.mark.skipif(not POSTGRES_AVAILABLE, reason="PostgreSQL not configured")
@pytest.mark.django_db(transaction=True)
class TestPostgreSQLIntegration:
    """Integration tests specific to PostgreSQL.

    These tests require PostgreSQL to be available and configured
    via the DATABASE_URL environment variable.
    """

    def test_postgres_concurrent_access(self, database_backend):
        """Test concurrent access with PostgreSQL row locking."""
        import threading

        key = "postgres:concurrent:1"
        results = []
        lock = threading.Lock()

        def increment():
            for _ in range(10):
                count = database_backend.incr(key, 60)
                with lock:
                    results.append(count)

        threads = [threading.Thread(target=increment) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # With proper locking, we should have exactly 50 increments
        assert database_backend.get_count(key, 60) == 50

    def test_postgres_select_for_update(self, database_backend):
        """Test that SELECT FOR UPDATE works correctly."""
        key = "postgres:lock:1"

        # Multiple rapid requests should not lose counts
        for _ in range(100):
            database_backend.incr(key, 60)

        assert database_backend.get_count(key, 60) == 100


@pytest.mark.skipif(not MYSQL_AVAILABLE, reason="MySQL not configured")
@pytest.mark.django_db(transaction=True)
class TestMySQLIntegration:
    """Integration tests specific to MySQL.

    These tests require MySQL to be available and configured
    via the DATABASE_URL environment variable.
    """

    def test_mysql_concurrent_access(self, database_backend):
        """Test concurrent access with MySQL row locking."""
        import threading

        key = "mysql:concurrent:1"
        results = []
        lock = threading.Lock()

        def increment():
            for _ in range(10):
                count = database_backend.incr(key, 60)
                with lock:
                    results.append(count)

        threads = [threading.Thread(target=increment) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # With proper locking, we should have exactly 50 increments
        assert database_backend.get_count(key, 60) == 50


@pytest.mark.django_db(transaction=True)
class TestSQLiteIntegration:
    """Integration tests specific to SQLite (default test database)."""

    def test_sqlite_sequential_access(self, database_backend):
        """Test sequential access works correctly with SQLite."""
        key = "sqlite:sequential:1"

        for i in range(50):
            count = database_backend.incr(key, 60)
            assert count == i + 1

        assert database_backend.get_count(key, 60) == 50

    def test_sqlite_transactions(self, database_backend):
        """Test that SQLite transactions work correctly."""
        key = "sqlite:transaction:1"

        # Create some data
        database_backend.incr(key, 60)
        database_backend.incr(key, 60)

        # Verify count
        assert database_backend.get_count(key, 60) == 2

        # Reset should also work transactionally
        database_backend.reset(key)
        assert database_backend.get_count(key, 60) == 0


@pytest.mark.django_db(transaction=True)
class TestAlgorithmComparison:
    """Compare fixed window vs sliding window behavior."""

    def test_fixed_vs_sliding_window_accuracy(self, database_backend, sliding_backend):
        """Compare accuracy of fixed vs sliding window."""
        fixed_key = "compare:fixed:1"
        sliding_key = "compare:sliding:1"
        limit = 10
        period = 60

        # Both should allow same number in a single burst
        for i in range(limit):
            allowed_fixed, _ = database_backend.check_rate_limit(
                fixed_key, limit, period
            )
            allowed_sliding, _ = sliding_backend.check_rate_limit(
                sliding_key, limit, period
            )
            assert allowed_fixed is True
            assert allowed_sliding is True

        # Both should block at limit
        allowed_fixed, _ = database_backend.check_rate_limit(fixed_key, limit, period)
        allowed_sliding, _ = sliding_backend.check_rate_limit(
            sliding_key, limit, period
        )
        assert allowed_fixed is False
        assert allowed_sliding is False
