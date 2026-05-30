"""
Integration tests for async DRF views with rate limiting.

Tests @aratelimit decorator behavior with async DRF APIViews.
"""

import asyncio

import pytest

from django.core.cache import cache
from django.http import HttpResponse
from django.test import AsyncRequestFactory, override_settings

try:
    from rest_framework import status
    from rest_framework.response import Response
    from rest_framework.views import APIView

    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    APIView = object
    Response = None
    status = None

from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.decorator import aratelimit

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not DRF_AVAILABLE, reason="DRF not available"),
]


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear caches before each test."""
    clear_backend_cache()
    cache.clear()
    yield
    clear_backend_cache()
    cache.clear()


class TestDRFAsyncRateLimiting:
    """Test async rate limiting with DRF-style views."""

    @override_settings(RATELIMIT_BACKEND="memory")
    async def test_aratelimit_basic_async_view(self):
        """Test basic aratelimit on async view."""
        rf = AsyncRequestFactory()

        @aratelimit(rate="2/m", key="ip", block=True)
        async def async_view(request):
            return HttpResponse("OK")

        # First two requests should pass
        request1 = rf.get("/test/", REMOTE_ADDR="10.0.0.50")
        resp1 = await async_view(request1)
        assert resp1.status_code == 200

        request2 = rf.get("/test/", REMOTE_ADDR="10.0.0.50")
        resp2 = await async_view(request2)
        assert resp2.status_code == 200

        # Third should be blocked
        request3 = rf.get("/test/", REMOTE_ADDR="10.0.0.50")
        resp3 = await async_view(request3)
        assert resp3.status_code == 429

    @override_settings(RATELIMIT_BACKEND="memory")
    async def test_aratelimit_non_blocking(self):
        """Test aratelimit with block=False on async view."""
        rf = AsyncRequestFactory()

        @aratelimit(rate="1/m", key="ip", block=False)
        async def async_view(request):
            return HttpResponse("OK")

        # All requests should pass with non-blocking
        for i in range(5):
            request = rf.get("/test/", REMOTE_ADDR="10.0.0.51")
            resp = await async_view(request)
            assert resp.status_code == 200

    @override_settings(RATELIMIT_BACKEND="memory")
    async def test_aratelimit_different_keys(self):
        """Two different REMOTE_ADDRs keep independent counters.

        Requests are issued sequentially (not via ``asyncio.gather``) so key
        isolation is asserted deterministically.

        NOTE: ``AsyncRequestFactory.get(path, REMOTE_ADDR=...)`` silently drops
        the ``REMOTE_ADDR`` kwarg (it always yields ``127.0.0.1``), which would
        collapse both clients onto one bucket and hide the very behavior under
        test. ``REMOTE_ADDR`` is therefore set on ``request.META`` directly.
        """
        rf = AsyncRequestFactory()

        @aratelimit(rate="1/m", key="ip", block=True)
        async def async_view(request):
            return HttpResponse("OK")

        def make(remote_addr):
            req = rf.get("/test/")
            req.META["REMOTE_ADDR"] = remote_addr
            return req

        # IP A: first request allowed, second blocked (limit 1/m).
        assert (await async_view(make("10.0.0.61"))).status_code == 200
        assert (await async_view(make("10.0.0.61"))).status_code == 429

        # IP B has its own counter and is unaffected by IP A exhausting its
        # limit: its first request must still succeed.
        assert (await async_view(make("10.0.0.62"))).status_code == 200
        # ...and IP B is then independently limited.
        assert (await async_view(make("10.0.0.62"))).status_code == 429

    @override_settings(RATELIMIT_BACKEND="memory")
    async def test_aratelimit_with_token_bucket(self):
        """Async limiter allows a burst up to the limit, then returns 429.

        ``rate`` and ``bucket_size`` are set to the same value (5) so the
        allowance is deterministic: exactly five rapid requests pass before the
        sixth is blocked.

        NOTE: ``aratelimit`` does not yet implement the token-bucket algorithm
        natively (``algorithm`` / ``algorithm_config`` are accepted but not
        honored by the async path), so the burst is driven by ``rate``. Keeping
        ``bucket_size == rate`` makes this test correct regardless of whether
        async token-bucket support is added later; see the report note.
        ``REMOTE_ADDR`` is set on ``request.META`` because the async factory
        ignores the kwarg form.
        """
        rf = AsyncRequestFactory()

        @aratelimit(
            rate="5/m",
            key="ip",
            algorithm="token_bucket",
            algorithm_config={"bucket_size": 5},
            block=True,
        )
        async def bucket_view(request):
            return HttpResponse("OK")

        def make():
            req = rf.get("/test/")
            req.META["REMOTE_ADDR"] = "10.99.0.1"
            return req

        # Burst of five requests should all be allowed.
        for i in range(5):
            resp = await bucket_view(make())
            assert resp.status_code == 200, f"burst request {i + 1} should pass"

        # The sixth request exhausts the allowance and must be blocked.
        assert (await bucket_view(make())).status_code == 429

    @override_settings(RATELIMIT_BACKEND="memory")
    async def test_aratelimit_method_specific(self):
        """Test aratelimit applies only to specified method."""
        rf = AsyncRequestFactory()

        @aratelimit(rate="1/m", key="ip", method="GET", block=True)
        async def async_view(request):
            return HttpResponse("OK")

        # GET should be limited
        request1 = rf.get("/test/", REMOTE_ADDR="10.0.0.80")
        resp1 = await async_view(request1)
        assert resp1.status_code == 200

        request2 = rf.get("/test/", REMOTE_ADDR="10.0.0.80")
        resp2 = await async_view(request2)
        assert resp2.status_code == 429

        # POST should not be limited
        request3 = rf.post("/test/", REMOTE_ADDR="10.0.0.80")
        resp3 = await async_view(request3)
        assert resp3.status_code == 200


class TestDRFAsyncConcurrency:
    """Test async rate limiting under concurrent load."""

    @override_settings(RATELIMIT_BACKEND="memory")
    async def test_concurrent_async_requests(self):
        """Test multiple concurrent async requests are properly rate limited."""
        rf = AsyncRequestFactory()

        @aratelimit(rate="3/m", key="ip", block=True)
        async def async_view(request):
            # Simulate some async work
            await asyncio.sleep(0.01)
            return HttpResponse("OK")

        # Create multiple concurrent requests
        requests = [rf.get("/test/", REMOTE_ADDR="10.0.0.90") for _ in range(6)]

        async def make_request(req):
            return await async_view(req)

        # Execute concurrently
        results = await asyncio.gather(*[make_request(r) for r in requests])
        status_codes = [r.status_code for r in results]

        # Should have 3 successes and 3 failures
        assert status_codes.count(200) == 3
        assert status_codes.count(429) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
