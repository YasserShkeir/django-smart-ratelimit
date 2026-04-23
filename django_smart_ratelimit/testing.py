"""
Pytest testing utilities for django-smart-ratelimit.

This module provides pytest fixtures and assertion helpers to simplify testing
of rate-limited Django views and functions. It reduces boilerplate by handling
backend setup, mocking, and time control.

Example usage:

    from django_smart_ratelimit.testing import (
        assert_rate_limited,
        assert_not_rate_limited,
        RateLimitClient,
    )

    def test_rate_limit_exhaustion(client, ratelimit_memory_backend):
        '''Test that rate limit is enforced after N requests.'''
        # ratelimit_memory_backend fixture auto-wires memory backend
        rate_limit_client = RateLimitClient(client)
        responses, final_response = rate_limit_client.exhaust_limit(
            "/api/endpoint/", limit=5
        )

        assert len(responses) == 5
        assert_rate_limited(final_response, expected_limit=5)
        assert_remaining(final_response, expected=0)
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore[assignment]


def _get_pytest() -> Any:
    """Get pytest module or raise helpful error if not installed."""
    if pytest is None:
        raise ImportError(
            "pytest is required for django_smart_ratelimit.testing fixtures. "
            "Install with: pip install 'django-smart-ratelimit[dev]'"
        )
    return pytest


# Pytest Fixtures (conditional on pytest being available)


if pytest is not None:

    @pytest.fixture
    def ratelimit_memory_backend(monkeypatch: Any) -> Any:
        """
        Fixture that swaps the rate limiter backend to use MemoryBackend.

        Automatically patches `get_backend()` to return a fresh MemoryBackend
        for each test, clearing state between tests.

        Usage:
            def test_my_view(client, ratelimit_memory_backend):
                # Backend is already wired; just use your view
                response = client.get("/api/endpoint/")
                assert response.status_code == 200

        Returns:
            MemoryBackend: A fresh memory backend instance for the test.
        """
        from django_smart_ratelimit.backends.memory import MemoryBackend

        backend = MemoryBackend()

        def mock_get_backend(backend_name: Optional[str] = None) -> Any:
            return backend

        monkeypatch.setattr(
            "django_smart_ratelimit.backends.get_backend", mock_get_backend
        )
        monkeypatch.setattr(
            "django_smart_ratelimit.decorator.get_backend", mock_get_backend
        )

        yield backend

        # Cleanup: clear and shutdown backend
        backend.clear_all()
        if hasattr(backend, "shutdown"):
            backend.shutdown()

    @pytest.fixture
    def disable_ratelimit(settings: Any) -> None:
        """
        Fixture that disables rate limiting globally for the test.

        Sets RATELIMIT_ENABLE = False, allowing all requests through
        without rate limit checks.

        Usage:
            def test_with_ratelimit_disabled(client, disable_ratelimit):
                # All requests pass; no rate limiting
                for _ in range(100):
                    response = client.get("/api/endpoint/")
                    assert response.status_code == 200
        """
        settings.RATELIMIT_ENABLE = False

    @pytest.fixture
    def ratelimit_redis_backend(monkeypatch: Any) -> Any:
        """
        Fixture that uses a real Redis backend if available.

        Skips the test with a clear message if Redis is unavailable or
        not configured. Generates a unique key namespace per test to avoid
        cross-test pollution.

        Usage:
            def test_redis_backend(client, ratelimit_redis_backend):
                # Backend is wired; uses actual Redis
                response = client.get("/api/endpoint/")
                assert response.status_code == 200

        Returns:
            RedisBackend: A Redis backend instance.

        Raises:
            pytest.skip: If Redis is unavailable.
        """
        from django_smart_ratelimit.backends import get_backend

        try:
            # Try to get or create a Redis backend
            backend = get_backend("redis")

            # Test connectivity
            if hasattr(backend, "health_check"):
                health = backend.health_check()
                if health.get("status") != "healthy":
                    pytest.skip("Redis backend unhealthy")

            # Generate unique namespace per test
            test_id = id(backend)
            if hasattr(backend, "_key_prefix"):
                backend._key_prefix = f"test_{test_id}_"

            yield backend

            # Cleanup
            if hasattr(backend, "clear_all"):
                backend.clear_all()

        except Exception as e:
            pytest.skip(f"Redis backend unavailable: {e}")

    @pytest.fixture
    def frozen_ratelimit_time(monkeypatch: Any) -> Any:
        """
        Fixture for simulated time advancement in rate limit tests.

        Patches `time.time()` in rate limiter modules to allow
        deterministic time control without waiting for real time to pass.

        Usage:
            def test_rate_limit_reset(client, ratelimit_memory_backend, frozen_ratelimit_time):
                # Exhaust limit at t=0
                client.get("/api/endpoint/")
                client.get("/api/endpoint/")
                response = client.get("/api/endpoint/")
                assert response.status_code == 429

                # Advance time by 61 seconds (past default 60s period)
                frozen_ratelimit_time.advance(61)

                # Now we have quota again
                response = client.get("/api/endpoint/")
                assert response.status_code == 200

        Returns:
            FrozenTime: A context manager / object for time control.
        """

        class FrozenTime:
            """Simulate time advancement for rate limit tests."""

            def __init__(self, monkeypatch: Any) -> None:
                self.monkeypatch = monkeypatch
                self.current_time = time.time()
                self._patch_time()

            def _patch_time(self) -> None:
                """Patch time.time() across rate limiter modules."""

                def mock_time() -> float:
                    return self.current_time

                self.monkeypatch.setattr("time.time", mock_time)
                self.monkeypatch.setattr(
                    "django_smart_ratelimit.backends.utils.get_current_timestamp",
                    mock_time,
                )
                self.monkeypatch.setattr(
                    "django_smart_ratelimit.decorator.time.time",
                    mock_time,
                )

            def advance(self, seconds: float) -> None:
                """Advance simulated time by N seconds.

                Args:
                    seconds: Number of seconds to advance.
                """
                self.current_time += seconds

            def set_time(self, timestamp: float) -> None:
                """Set simulated time to an absolute timestamp.

                Args:
                    timestamp: Unix timestamp to set.
                """
                self.current_time = timestamp

            def __enter__(self) -> FrozenTime:
                """Context manager entry."""
                return self

            def __exit__(self, *args: Any) -> None:
                """Context manager exit."""

        return FrozenTime(monkeypatch)


# Assertion Helpers (plain functions, always available)


def assert_rate_limited(
    response: Any,
    *,
    expected_limit: Optional[int] = None,
    expected_remaining: Optional[int] = None,
) -> None:
    """
    Assert that a response is rate-limited (status 429).

    Validates response status and optional X-RateLimit-* headers.

    Args:
        response: Django test client response.
        expected_limit: If provided, assert X-RateLimit-Limit == this value.
        expected_remaining: If provided, assert X-RateLimit-Remaining == this value.

    Raises:
        AssertionError: If response is not 429 or headers don't match.

    Example:
        response = client.get("/api/endpoint/")
        assert_rate_limited(response, expected_limit=10, expected_remaining=0)
    """
    assert (  # nosec B101
        response.status_code == 429
    ), f"Expected status 429, got {response.status_code}"

    headers = read_rate_limit_headers(response)

    if expected_limit is not None:
        actual = headers.get("limit")
        assert (
            actual == expected_limit
        ), f"Expected X-RateLimit-Limit={expected_limit}, got {actual}"  # nosec B101

    if expected_remaining is not None:
        actual = headers.get("remaining")
        assert (
            actual == expected_remaining
        ), (  # nosec B101
            f"Expected X-RateLimit-Remaining={expected_remaining}, got {actual}"
        )


def assert_not_rate_limited(response: Any) -> None:
    """
    Assert that a response is NOT rate-limited (status != 429).

    Validates that X-RateLimit-Remaining header is present.

    Args:
        response: Django test client response.

    Raises:
        AssertionError: If response is 429 or missing X-RateLimit-Remaining.

    Example:
        response = client.get("/api/endpoint/")
        assert_not_rate_limited(response)
    """
    assert (  # nosec B101
        response.status_code != 429
    ), "Expected status != 429, but got 429 (rate limited)"

    headers = read_rate_limit_headers(response)
    assert (
        headers.get("remaining") is not None
    ), (  # nosec B101
        "X-RateLimit-Remaining header missing from non-rate-limited response"
    )


def assert_remaining(response: Any, expected: int) -> None:
    """
    Assert that X-RateLimit-Remaining equals expected value.

    Args:
        response: Django test client response.
        expected: Expected remaining requests.

    Raises:
        AssertionError: If header doesn't match.

    Example:
        response = client.get("/api/endpoint/")
        assert_remaining(response, 9)
    """
    headers = read_rate_limit_headers(response)
    actual = headers.get("remaining")
    assert (
        actual == expected
    ), f"Expected X-RateLimit-Remaining={expected}, got {actual}"  # nosec B101


def assert_retry_after(response: Any, expected: int, tolerance: int = 1) -> None:
    """
    Assert that Retry-After header is within tolerance.

    Useful for testing that Retry-After is reasonable when rate-limited.

    Args:
        response: Django test client response.
        expected: Expected Retry-After seconds.
        tolerance: Allow +/- this many seconds.

    Raises:
        AssertionError: If header is outside tolerance.

    Example:
        response = client.get("/api/endpoint/")  # triggers 429
        assert_retry_after(response, expected=60, tolerance=5)
    """
    retry_after_header = response.get("Retry-After")
    assert retry_after_header is not None, "Retry-After header missing"  # nosec B101

    try:
        actual = int(retry_after_header)
    except (ValueError, TypeError):
        raise AssertionError(f"Retry-After header not an integer: {retry_after_header}")

    diff = abs(actual - expected)
    assert diff <= tolerance, (  # nosec B101
        f"Expected Retry-After ~{expected}s (tolerance {tolerance}), "
        f"got {actual}s (diff: {diff}s)"
    )


def read_rate_limit_headers(response: Any) -> Dict[str, Optional[int]]:
    """
    Extract all X-RateLimit-* headers from response.

    Returns a dict mapping canonical names to integers:
    - "limit" -> X-RateLimit-Limit
    - "remaining" -> X-RateLimit-Remaining
    - "reset" -> X-RateLimit-Reset

    Args:
        response: Django test client response.

    Returns:
        Dictionary of rate limit headers {name: value or None}.

    Example:
        headers = read_rate_limit_headers(response)
        assert headers["limit"] == 10
        assert headers["remaining"] == 5
    """
    result: Dict[str, Optional[int]] = {
        "limit": None,
        "remaining": None,
        "reset": None,
    }

    # Django test responses: use response.get() or response[header_name]
    # Or use response.headers for test client >= Django 3.2
    try:
        # Django test client response supports dict-like access
        for header_key in (
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ):
            val = response.get(header_key)
            if val is not None:
                try:
                    int_val = int(val)
                    key = header_key.split("-")[-1].lower()
                    result[key] = int_val
                except (ValueError, TypeError):
                    pass
    except Exception:  # nosec B110
        # Fallback: try response.__getitem__ or response.headers attribute
        pass

    return result


# Helper Utilities


class RateLimitClient:
    """
    Helper to exhaust rate limits by making requests until hitting 429.

    Wraps a Django test client and provides methods to programmatically
    exhaust a rate limit, useful for testing behavior when limits are hit.

    Example:
        def test_exhaust_limit(client, ratelimit_memory_backend):
            rate_limit_client = RateLimitClient(client)
            responses, final = rate_limit_client.exhaust_limit(
                "/api/endpoint/", limit=5
            )
            assert len(responses) == 5
            assert_rate_limited(final, expected_limit=5, expected_remaining=0)
    """

    def __init__(self, client: Any) -> None:
        """
        Initialize with a Django test client.

        Args:
            client: Django test.Client instance.
        """
        self.client = client
        self.responses: list[Any] = []

    def exhaust_limit(
        self,
        path: str,
        limit: int = 10,
        method: str = "GET",
        **kwargs: Any,
    ) -> Tuple[list[Any], Any]:
        """
        Make requests until rate limit is hit, then one more to trigger 429.

        Args:
            path: URL path (e.g., "/api/endpoint/").
            limit: Expected rate limit value (used to determine how many
                   requests to make).
            method: HTTP method (GET, POST, etc.). Defaults to GET.
            **kwargs: Additional arguments for client.get/post/etc.

        Returns:
            Tuple of (successful_responses, exceeded_response) where:
            - successful_responses: List of responses before hitting limit
            - exceeded_response: The 429 response (or last response if limit
                                not triggered)

        Example:
            responses, rate_limited = client.exhaust_limit(
                "/api/endpoint/", limit=5
            )
            assert len(responses) == 5
            assert rate_limited.status_code == 429
        """
        client_method = getattr(self.client, method.lower())
        responses = []

        # Make limit+1 requests (limit should pass, +1 should fail)
        for i in range(limit + 1):
            response = client_method(path, **kwargs)
            responses.append(response)

            if response.status_code == 429:
                # Hit the limit
                return responses[:-1], response

        # If we didn't hit 429, return all but last
        return responses[:-1], responses[-1]

    def clear_responses(self) -> None:
        """Clear the stored responses list."""
        self.responses = []


def clear_rate_limit_cache(key_pattern: str = "*") -> None:
    """
    Clear rate limit entries matching a pattern from the active backend.

    Gets the active backend and clears matching keys. Useful for cleaning
    up between test runs or isolating specific test data.

    Args:
        key_pattern: Pattern to match. "*" (default) clears all.
                    Supports simple glob patterns like "user_*".

    Example:
        # Clear all rate limits
        clear_rate_limit_cache()

        # Clear only user-related limits
        clear_rate_limit_cache("user_*")

    Note:
        Requires that a backend is available (e.g., via ratelimit_memory_backend
        fixture). This is primarily for test cleanup.
    """
    try:
        from django_smart_ratelimit.backends import get_backend

        backend = get_backend()

        if key_pattern == "*":
            # Clear all
            if hasattr(backend, "clear_all"):
                backend.clear_all()
            else:
                # Fallback: try to enumerate and delete
                if hasattr(backend, "_data"):
                    backend._data.clear()
                if hasattr(backend, "_token_buckets"):
                    backend._token_buckets.clear()
                if hasattr(backend, "_storage"):
                    backend._storage.clear()
        else:
            # Pattern-based deletion (limited support for memory backend)
            if hasattr(backend, "_data"):
                import fnmatch

                keys_to_delete = [
                    k for k in backend._data.keys() if fnmatch.fnmatch(k, key_pattern)
                ]
                for k in keys_to_delete:
                    backend.reset(k)

    except Exception:  # nosec B110
        # If backend isn't available, fail silently (likely wrong test setup)
        pass
