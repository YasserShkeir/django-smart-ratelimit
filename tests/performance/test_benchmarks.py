import threading
import time
import tracemalloc

import pytest

from django_smart_ratelimit.backends.memory import MemoryBackend
from django_smart_ratelimit.backends.redis_backend import RedisBackend

# Mark all tests in this module as benchmark tests
pytestmark = pytest.mark.benchmark

REDIS_AVAILABLE = False
try:
    pass

    # Check if we can import, connection check later
    REDIS_AVAILABLE = True
except ImportError:
    pass


class TestMemoryBackendBenchmarks:
    @pytest.fixture
    def backend(self):
        return MemoryBackend()

    def test_increment_speed(self, backend, benchmark):
        """Benchmark single increment operation."""
        key = "bench:increment"
        benchmark(backend.incr, key, period=60)

    def test_check_rate_limit_speed(self, backend, benchmark):
        """Benchmark rate limit check."""
        key = "bench:check"
        benchmark(backend.check_rate_limit, key, limit=100, period=60)

    def test_high_key_count(self, backend, benchmark):
        """Benchmark with many unique keys."""

        def many_keys():
            for i in range(1000):
                backend.incr(f"bench:key:{i}", period=60)

        benchmark(many_keys)

    def test_concurrent_access(self, backend, benchmark):
        """Benchmark concurrent access."""

        def concurrent_ops():
            threads = []
            for i in range(10):
                t = threading.Thread(
                    target=lambda: [
                        backend.incr(f"bench:concurrent:{i}", period=60)
                        for _ in range(100)
                    ]
                )
                threads.append(t)

            for t in threads:
                t.start()
            for t in threads:
                t.join()

        benchmark(concurrent_ops)


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not available")
class TestRedisBackendBenchmarks:
    @pytest.fixture
    def backend(self):
        # Using DB 15 for tests to avoid conflicts
        try:
            b = RedisBackend(url="redis://localhost:6379/15")
            # Ping to ensure available
            b._check_connection()
            return b
        except Exception:
            pytest.skip("Redis connection failed")

    def test_increment_speed(self, backend, benchmark):
        if not backend:
            pytest.skip("No backend")
        benchmark(backend.incr, "bench:redis:inc", period=60)

    def test_pipeline_vs_individual(self, backend, benchmark):
        """Compare pipeline vs individual operations."""
        if not backend:
            pytest.skip("No backend")

        def individual():
            for i in range(100):
                backend.incr(f"bench:individual:{i}", period=60)

        benchmark(individual)


def test_backend_comparison(benchmark):
    """Compare all backends."""
    backends = {
        "memory": MemoryBackend(),
    }
    if REDIS_AVAILABLE:
        try:
            b = RedisBackend(url="redis://localhost:6379/15")
            b._check_connection()
            backends["redis"] = b
        except Exception:
            pass

    results = {}
    for name, backend in backends.items():
        start = time.perf_counter()
        for i in range(1000):
            backend.incr(f"compare:{i}", period=60)
        results[name] = time.perf_counter() - start

    print("\nBackend Comparison (1k ops):")
    for name, duration in results.items():
        print(f"  {name}: {duration:.3f}s ({1000/duration:.0f} ops/sec)")


def test_memory_usage():
    """Measure memory usage with many keys."""
    backend = MemoryBackend()

    tracemalloc.start()

    # Reduced to 10k for dev speed
    for i in range(10000):
        backend.incr(f"mem:key:{i}", period=60)

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\nMemory Usage (10k keys):")
    print(f"  Current: {current / 1024 / 1024:.2f} MB")
    print(f"  Peak: {peak / 1024 / 1024:.2f} MB")
    print(f"  Per key: {current / 10000:.0f} bytes")
