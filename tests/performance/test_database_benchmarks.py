"""Performance benchmarks for DatabaseBackend.

These tests measure the performance of the database backend for
rate limiting operations. They compare against memory and Redis
backends when available.

Run with: pytest tests/performance/test_database_benchmarks.py --benchmark-only
"""

import time
import tracemalloc

import pytest

# Mark all tests in this module as benchmark tests
pytestmark = [pytest.mark.benchmark, pytest.mark.django_db(transaction=True)]

# Check backend availability
REDIS_AVAILABLE = False
try:
    from django_smart_ratelimit.backends.redis_backend import RedisBackend

    REDIS_AVAILABLE = True
except ImportError:
    pass


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
def sliding_database_backend():
    """Create a DatabaseBackend with sliding window."""
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
def memory_backend():
    """Create a MemoryBackend for comparison."""
    from django_smart_ratelimit.backends.memory import MemoryBackend

    return MemoryBackend()


class TestDatabaseBackendBenchmarks:
    """Benchmark tests for DatabaseBackend."""

    def test_increment_speed_fixed_window(self, database_backend, benchmark):
        """Benchmark single increment operation with fixed window."""
        key = "bench:db:increment:fixed"
        benchmark(database_backend.incr, key, period=60)

    def test_increment_speed_sliding_window(self, sliding_database_backend, benchmark):
        """Benchmark single increment operation with sliding window."""
        key = "bench:db:increment:sliding"
        benchmark(sliding_database_backend.incr, key, period=60)

    def test_check_rate_limit_speed(self, database_backend, benchmark):
        """Benchmark rate limit check operation."""
        key = "bench:db:check"
        benchmark(database_backend.check_rate_limit, key, limit=100, period=60)

    def test_get_count_speed(self, database_backend, benchmark):
        """Benchmark get_count operation."""
        key = "bench:db:getcount"
        # Pre-populate some data
        for _ in range(10):
            database_backend.incr(key, 60)
        benchmark(database_backend.get_count, key, period=60)

    def test_token_bucket_check_speed(self, database_backend, benchmark):
        """Benchmark token bucket check operation."""
        key = "bench:db:bucket"
        benchmark(
            database_backend.token_bucket_check,
            key,
            bucket_size=100,
            refill_rate=10.0,
            initial_tokens=100,
            tokens_requested=1,
        )

    def test_high_key_count(self, database_backend, benchmark):
        """Benchmark with many unique keys."""

        def many_keys():
            for i in range(100):  # Reduced for SQLite compatibility
                database_backend.incr(f"bench:db:key:{i}", period=60)

        benchmark(many_keys)

    def test_reset_speed(self, database_backend, benchmark):
        """Benchmark reset operation."""
        key = "bench:db:reset"
        # Pre-populate
        for _ in range(10):
            database_backend.incr(key, 60)
        benchmark(database_backend.reset, key)


class TestDatabaseVsMemoryComparison:
    """Compare database backend to memory backend."""

    def test_increment_comparison(self, database_backend, memory_backend):
        """Compare increment speed between database and memory."""
        iterations = 100

        # Benchmark database backend
        db_start = time.perf_counter()
        for i in range(iterations):
            database_backend.incr(f"compare:db:{i}", period=60)
        db_time = time.perf_counter() - db_start

        # Benchmark memory backend
        mem_start = time.perf_counter()
        for i in range(iterations):
            memory_backend.incr(f"compare:mem:{i}", period=60)
        mem_time = time.perf_counter() - mem_start

        print(f"\nIncrement Comparison ({iterations} ops):")
        print(f"  Database: {db_time:.4f}s ({iterations/db_time:.0f} ops/sec)")
        print(f"  Memory: {mem_time:.4f}s ({iterations/mem_time:.0f} ops/sec)")
        print(f"  Ratio: Database is {db_time/mem_time:.1f}x slower")

    def test_check_rate_limit_comparison(self, database_backend, memory_backend):
        """Compare check_rate_limit speed between database and memory."""
        iterations = 100

        # Benchmark database backend
        db_start = time.perf_counter()
        for i in range(iterations):
            database_backend.check_rate_limit(f"compare:db:check:{i}", 100, 60)
        db_time = time.perf_counter() - db_start

        # Benchmark memory backend
        mem_start = time.perf_counter()
        for i in range(iterations):
            memory_backend.check_rate_limit(f"compare:mem:check:{i}", 100, 60)
        mem_time = time.perf_counter() - mem_start

        print(f"\nRate Limit Check Comparison ({iterations} ops):")
        print(f"  Database: {db_time:.4f}s ({iterations/db_time:.0f} ops/sec)")
        print(f"  Memory: {mem_time:.4f}s ({iterations/mem_time:.0f} ops/sec)")
        print(f"  Ratio: Database is {db_time/mem_time:.1f}x slower")


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not available")
class TestDatabaseVsRedisComparison:
    """Compare database backend to Redis backend."""

    @pytest.fixture
    def redis_backend(self):
        """Create Redis backend for comparison."""
        try:
            backend = RedisBackend(url="redis://localhost:6379/15")
            backend._check_connection()
            return backend
        except Exception:
            pytest.skip("Redis connection failed")

    def test_all_backends_comparison(
        self, database_backend, memory_backend, redis_backend
    ):
        """Compare all backends in a single test."""
        iterations = 50

        backends = {
            "Database": database_backend,
            "Memory": memory_backend,
            "Redis": redis_backend,
        }

        results = {}
        for name, backend in backends.items():
            start = time.perf_counter()
            for i in range(iterations):
                backend.incr(f"all:compare:{name}:{i}", period=60)
            results[name] = time.perf_counter() - start

        print(f"\nAll Backends Comparison ({iterations} ops):")
        for name, duration in sorted(results.items(), key=lambda x: x[1]):
            print(f"  {name}: {duration:.4f}s ({iterations/duration:.0f} ops/sec)")


class TestDatabaseConcurrencyBenchmarks:
    """Benchmark concurrent access patterns."""

    def test_sequential_access_baseline(self, database_backend):
        """Baseline: sequential access for comparison."""
        key = "bench:sequential:baseline"
        iterations = 50

        start = time.perf_counter()
        for _ in range(iterations):
            database_backend.incr(key, 60)
        duration = time.perf_counter() - start

        print(f"\nSequential Access ({iterations} ops):")
        print(f"  Duration: {duration:.4f}s ({iterations/duration:.0f} ops/sec)")
        assert database_backend.get_count(key, 60) == iterations


class TestDatabaseMemoryUsage:
    """Test memory usage of database backend."""

    def test_memory_footprint(self, database_backend):
        """Measure memory footprint of database operations."""
        tracemalloc.start()

        # Perform operations
        for i in range(100):
            database_backend.incr(f"mem:test:{i}", period=60)

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print(f"\nMemory Usage (100 database ops):")
        print(f"  Current: {current / 1024:.2f} KB")
        print(f"  Peak: {peak / 1024:.2f} KB")


class TestDatabaseCleanupBenchmarks:
    """Benchmark cleanup operations."""

    def test_cleanup_speed(self, database_backend, benchmark):
        """Benchmark cleanup operation."""
        from datetime import timedelta

        from django.utils import timezone

        from django_smart_ratelimit.models import RateLimitCounter

        # Create some expired entries
        now = timezone.now()
        for i in range(50):
            RateLimitCounter.objects.create(
                key=f"cleanup:bench:{i}",
                count=1,
                window_start=now - timedelta(hours=2),
                window_end=now - timedelta(hours=1),
            )

        def run_cleanup():
            database_backend.cleanup_expired()

        benchmark(run_cleanup)

    def test_cleanup_large_dataset(self, database_backend):
        """Test cleanup performance with larger dataset."""
        from datetime import timedelta

        from django.utils import timezone

        from django_smart_ratelimit.models import RateLimitCounter

        now = timezone.now()

        # Create 500 expired entries
        entries = [
            RateLimitCounter(
                key=f"cleanup:large:{i}",
                count=1,
                window_start=now - timedelta(hours=2),
                window_end=now - timedelta(hours=1),
            )
            for i in range(500)
        ]
        RateLimitCounter.objects.bulk_create(entries)

        start = time.perf_counter()
        deleted = database_backend.cleanup_expired()
        duration = time.perf_counter() - start

        print(f"\nLarge Cleanup (500 entries):")
        print(f"  Duration: {duration:.4f}s")
        print(f"  Deleted: {deleted['counters']}")
        print(f"  Rate: {deleted['counters']/duration:.0f} deletes/sec")


class TestSlidingWindowBenchmarks:
    """Benchmark sliding window specific operations."""

    def test_sliding_window_scaling(self, sliding_database_backend):
        """Test how sliding window scales with entries."""

        key = "sliding:scale:test"
        iterations = 50

        times = []
        for batch in range(5):
            # Add more entries each batch
            for _ in range(iterations):
                sliding_database_backend.incr(key, 3600)  # 1 hour window

            # Measure time for next increment
            start = time.perf_counter()
            sliding_database_backend.incr(key, 3600)
            times.append(time.perf_counter() - start)

        print(f"\nSliding Window Scaling:")
        for i, t in enumerate(times):
            count = (i + 1) * iterations + 1
            print(f"  {count} entries: {t*1000:.2f}ms")
