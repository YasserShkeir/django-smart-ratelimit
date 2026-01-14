from unittest.mock import Mock

import pytest

from django.http import HttpResponse
from django.test import AsyncRequestFactory, RequestFactory, override_settings

from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.decorator import aratelimit, ratelimit_batch


@pytest.fixture(autouse=True)
def cleanup():
    clear_backend_cache()
    yield
    clear_backend_cache()


@override_settings(
    RATELIMIT_BACKEND="django_smart_ratelimit.backends.memory.MemoryBackend"
)
def test_ratelimit_batch():
    rf = RequestFactory()
    request = rf.get("/", REMOTE_ADDR="127.0.0.1")
    # Mock user for user key
    request.user = Mock()
    request.user.is_authenticated = True
    request.user.pk = 123

    @ratelimit_batch(
        [
            {"rate": "2/m", "key": "ip"},
            {"rate": "5/m", "key": lambda r, *a: f"user:123:{len(a)}"},
        ]
    )
    def my_view(request):
        return HttpResponse("OK")

    # 1. OK
    resp = my_view(request)
    assert resp.status_code == 200

    # 2. OK
    resp = my_view(request)
    assert resp.status_code == 200

    # 3. Blocked by 2/m (IP)
    resp = my_view(request)
    assert resp.status_code == 429


@pytest.mark.asyncio
@override_settings(
    RATELIMIT_BACKEND="django_smart_ratelimit.backends.memory.MemoryBackend"
)
async def test_aratelimit_memory_backend():
    """Test async decorator with default memory backend (via wrapper)."""
    rf = AsyncRequestFactory()
    request = rf.get("/", REMOTE_ADDR="127.0.0.1")

    @aratelimit(rate="1/m", key="ip", block=True)
    async def my_view(request):
        return HttpResponse("OK")

    # First request
    resp = await my_view(request)
    assert resp.status_code == 200

    # Second request
    resp = await my_view(request)
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_aratelimit_config():
    """Test async decorator configuration."""
    rf = AsyncRequestFactory()
    request = rf.post("/", REMOTE_ADDR="127.0.0.1")

    # Only applies to GET
    @aratelimit(rate="1/m", key="ip", method="GET")
    async def my_view(request):
        return HttpResponse("OK")

    # POST should be ignored (allowed)
    resp = await my_view(request)
    assert resp.status_code == 200

    # Second POST (still allowed)
    resp = await my_view(request)
    assert resp.status_code == 200
