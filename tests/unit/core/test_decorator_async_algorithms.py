"""Tests for async decorator algorithm dispatch (v3.1.0).

token_bucket (and leaky_bucket on backends with native support) are now honored
on async views, instead of silently degrading to window counting.
"""

import logging

from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.decorator import _run_bucket_check

MEMORY = "django_smart_ratelimit.backends.memory.MemoryBackend"


def _req(ip="9.9.9.9"):
    req = RequestFactory().get("/")
    req.META["REMOTE_ADDR"] = ip
    return req


@override_settings(RATELIMIT_BACKEND=MEMORY)
async def test_async_token_bucket_uses_bucket_semantics():
    # rate is 2/m but the bucket holds 5 with no refill. Window counting would
    # block after 2; getting 5 through proves the token-bucket path was used.
    clear_backend_cache()
    try:

        @rate_limit(
            key="ip",
            rate="2/m",
            algorithm="token_bucket",
            algorithm_config={"bucket_size": 5, "refill_rate": 0},
            block=True,
        )
        async def view(request):
            return HttpResponse("ok")

        for i in range(5):
            resp = await view(_req())
            assert resp.status_code == 200, f"request {i + 1} should pass"
        # Bucket now empty (no refill) -> blocked.
        assert (await view(_req())).status_code == 429
    finally:
        clear_backend_cache()


@override_settings(RATELIMIT_BACKEND=MEMORY)
async def test_async_token_bucket_sets_headers():
    clear_backend_cache()
    try:

        @rate_limit(
            key="ip",
            rate="10/m",
            algorithm="token_bucket",
            algorithm_config={"bucket_size": 10, "refill_rate": 1},
            block=True,
        )
        async def view(request):
            return HttpResponse("ok")

        resp = await view(_req())
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
    finally:
        clear_backend_cache()


@override_settings(RATELIMIT_BACKEND=MEMORY)
async def test_async_leaky_bucket_falls_back_to_window(caplog):
    # Memory has no native leaky_bucket_check -> warn + standard window limiting.
    clear_backend_cache()
    try:

        @rate_limit(key="ip", rate="2/m", algorithm="leaky_bucket", block=True)
        async def view(request):
            return HttpResponse("ok")

        with caplog.at_level(logging.WARNING):
            assert (await view(_req())).status_code == 200
            assert (await view(_req())).status_code == 200
            # Window limit of 2 reached -> blocked.
            assert (await view(_req())).status_code == 429
        assert any("leaky_bucket" in r.message for r in caplog.records)
    finally:
        clear_backend_cache()


class _FakeBucketBackend:
    """Minimal backend exposing native bucket checks for _run_bucket_check."""

    def token_bucket_check(self, key, bucket_size, refill_rate, initial, requested):
        return True, {"tokens_remaining": 4, "bucket_size": bucket_size}

    def leaky_bucket_check(self, key, capacity, leak_rate, cost):
        return True, {"space_remaining": 7, "bucket_capacity": capacity}


def test_run_bucket_check_token():
    backend = _FakeBucketBackend()
    allowed, metadata, remaining = _run_bucket_check(
        "token_bucket", backend, "k", 10, 60, 1, None
    )
    assert allowed is True
    assert remaining == 4
    assert metadata["tokens_remaining"] == 4


def test_run_bucket_check_leaky():
    backend = _FakeBucketBackend()
    allowed, metadata, remaining = _run_bucket_check(
        "leaky_bucket", backend, "k", 10, 60, 1, None
    )
    assert allowed is True
    assert remaining == 7
    assert metadata["space_remaining"] == 7
