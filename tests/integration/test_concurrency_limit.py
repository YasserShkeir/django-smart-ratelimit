"""Tests for concurrency (in-flight) limiting (roadmap #76).

Backend semaphore tests run on memory always and on Redis when reachable. The
decorator tests use the in-process memory backend with real threads so several
requests are genuinely in flight at once.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import RequestFactory

from django_smart_ratelimit import concurrency_limit
from django_smart_ratelimit.backends import clear_backend_cache, get_backend
from django_smart_ratelimit.backends.memory import MemoryBackend


def _redis_backend():
    try:
        from django_smart_ratelimit.backends.redis_backend import RedisBackend

        b = RedisBackend()
        b.redis.ping()
        return b
    except Exception:
        return None


REDIS = _redis_backend()
skip_without_redis = pytest.mark.skipif(REDIS is None, reason="live Redis unavailable")


def _req(ip="203.0.113.5"):
    request = RequestFactory().get("/")
    request.META["REMOTE_ADDR"] = ip
    return request


# ---------------------------------------------------------------------------
# Backend semaphore primitive
# ---------------------------------------------------------------------------


def _semaphore_contract(backend):
    key = "sem:%s" % uuid.uuid4().hex
    members = [uuid.uuid4().hex for _ in range(4)]
    # max 2 concurrent -> first two acquire, next two are refused.
    assert [backend.concurrency_acquire(key, 2, 60, m) for m in members] == [
        True,
        True,
        False,
        False,
    ]
    # Releasing one frees exactly one slot.
    backend.concurrency_release(key, members[0])
    assert backend.concurrency_acquire(key, 2, 60, members[3]) is True
    for m in members:
        backend.concurrency_release(key, m)
    # All released -> full capacity available again.
    assert backend.concurrency_acquire(key, 2, 60, uuid.uuid4().hex) is True


def test_memory_semaphore_contract():
    _semaphore_contract(MemoryBackend())


@skip_without_redis
def test_redis_semaphore_contract():
    _semaphore_contract(REDIS)


def test_memory_semaphore_reclaims_leaked_slot():
    backend = MemoryBackend()
    key = "sem:%s" % uuid.uuid4().hex
    # Fill capacity, then age the holders past the ttl as if they crashed.
    backend.concurrency_acquire(key, 1, 60, "leaked")
    assert backend.concurrency_acquire(key, 1, 60, "blocked") is False
    for member in backend._concurrency[key]:
        backend._concurrency[key][member] -= 120  # 120s ago, ttl is 60
    # The leaked holder is reclaimed, so a new request can proceed.
    assert backend.concurrency_acquire(key, 1, 60, "fresh") is True


# ---------------------------------------------------------------------------
# Decorator under real concurrency
# ---------------------------------------------------------------------------


def test_decorator_blocks_over_capacity_request():
    clear_backend_cache()
    get_backend("memory")  # pre-warm so all threads share one in-process backend
    release = threading.Event()

    @concurrency_limit(key="ip", max_concurrent=2, backend="memory")
    def view(_request):
        release.wait(timeout=5)
        return HttpResponse("ok")

    def call():
        return view(_req(ip="9.9.9.9")).status_code

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(call) for _ in range(3)]
            time.sleep(0.5)  # let all three attempt to acquire
            release.set()
            codes = sorted(f.result(timeout=5) for f in futures)
        # Two ran concurrently (200); the third was over capacity (429).
        assert codes == [200, 200, 429]
    finally:
        release.set()
        clear_backend_cache()


def test_decorator_releases_slot_after_each_request():
    clear_backend_cache()

    @concurrency_limit(key="ip", max_concurrent=1, backend="memory")
    def view(_request):
        return HttpResponse("ok")

    # Sequential requests each release their slot, so all are allowed.
    assert [view(_req()).status_code for _ in range(5)] == [200] * 5
    clear_backend_cache()


def test_decorator_non_block_allows_over_capacity():
    clear_backend_cache()
    get_backend("memory")  # pre-warm so all threads share one in-process backend
    release = threading.Event()

    @concurrency_limit(key="ip", max_concurrent=1, backend="memory", block=False)
    def view(_request):
        release.wait(timeout=5)
        return HttpResponse("ok")

    def call():
        return view(_req(ip="8.8.8.8")).status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(call) for _ in range(2)]
            time.sleep(0.3)
            release.set()
            codes = [f.result(timeout=5) for f in futures]
        # block=False: the over-capacity request runs anyway.
        assert codes == [200, 200]
    finally:
        release.set()
        clear_backend_cache()


def test_decorator_requires_semaphore_backend():
    from django_smart_ratelimit.concurrency import _require_semaphore_backend

    class _NoSemaphore:
        pass

    with pytest.raises(ImproperlyConfigured):
        _require_semaphore_backend(_NoSemaphore())


@skip_without_redis
def test_decorator_over_redis():
    clear_backend_cache()
    release = threading.Event()

    @concurrency_limit(key="ip", max_concurrent=2, backend="redis")
    def view(_request):
        release.wait(timeout=5)
        return HttpResponse("ok")

    def call():
        return view(_req(ip="7.7.7.7")).status_code

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(call) for _ in range(3)]
            time.sleep(0.5)
            release.set()
            codes = sorted(f.result(timeout=5) for f in futures)
        assert codes == [200, 200, 429]
    finally:
        release.set()
        clear_backend_cache()
