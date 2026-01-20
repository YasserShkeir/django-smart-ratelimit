"""Unit tests for adaptive rate limiting integration with decorator."""

from unittest.mock import MagicMock

import pytest

from django.http import HttpResponse
from django.test import RequestFactory

from django_smart_ratelimit.adaptive import (
    AdaptiveRateLimiter,
    register_adaptive_limiter,
    unregister_adaptive_limiter,
)
from django_smart_ratelimit.decorator import _apply_adaptive_limit, rate_limit


class TestApplyAdaptiveLimit:
    """Tests for _apply_adaptive_limit helper function."""

    def test_none_adaptive_returns_base_limit(self):
        """Test that None adaptive returns the base limit unchanged."""
        result = _apply_adaptive_limit(None, 100)
        assert result == 100

    def test_string_adaptive_looks_up_registered(self):
        """Test that string adaptive looks up registered limiter."""
        mock_indicator = MagicMock()
        mock_indicator.get_load.return_value = 0.0
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            min_limit=10,
            max_limit=200,
            indicators=[mock_indicator],
            update_interval=0,
        )

        register_adaptive_limiter("test_lookup", limiter)

        try:
            result = _apply_adaptive_limit("test_lookup", 100)
            # With 0 load, should return max_limit
            assert result == 200
        finally:
            unregister_adaptive_limiter("test_lookup")

    def test_string_adaptive_not_found_returns_base(self):
        """Test that unregistered string returns base limit."""
        result = _apply_adaptive_limit("nonexistent", 100)
        assert result == 100

    def test_instance_adaptive_used_directly(self):
        """Test that AdaptiveRateLimiter instance is used directly."""
        mock_indicator = MagicMock()
        mock_indicator.get_load.return_value = 1.0  # Max load
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            min_limit=10,
            max_limit=200,
            indicators=[mock_indicator],
            smoothing_factor=1.0,
            update_interval=0,
        )

        result = _apply_adaptive_limit(limiter, 100)
        # With max load, should return min_limit
        assert result == 10

    def test_invalid_type_returns_base_limit(self):
        """Test that invalid adaptive type returns base limit."""
        result = _apply_adaptive_limit(12345, 100)  # Invalid type
        assert result == 100

    def test_exception_handling_returns_base_limit(self):
        """Test that exceptions in limiter return base limit."""
        mock_limiter = MagicMock(spec=AdaptiveRateLimiter)
        mock_limiter.get_effective_limit.side_effect = RuntimeError("Test error")

        result = _apply_adaptive_limit(mock_limiter, 100)
        assert result == 100


@pytest.mark.django_db
class TestDecoratorWithAdaptive:
    """Tests for rate_limit decorator with adaptive parameter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()

    def test_decorator_with_registered_adaptive(self):
        """Test decorator using registered adaptive limiter."""
        # Create a limiter with very high limit (no rate limiting)
        mock_indicator = MagicMock()
        mock_indicator.get_load.return_value = 0.0  # Low load
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=1000,
            min_limit=100,
            max_limit=10000,  # Very high limit
            indicators=[mock_indicator],
            update_interval=0,
        )

        register_adaptive_limiter("decorator_test", limiter)

        try:

            @rate_limit(key="ip", rate="10/m", adaptive="decorator_test")
            def test_view(request):
                return HttpResponse("OK")

            request = self.factory.get("/test/")

            # Should not be rate limited with such high limit
            response = test_view(request)
            assert response.status_code == 200

        finally:
            unregister_adaptive_limiter("decorator_test")

    def test_decorator_with_instance_adaptive(self):
        """Test decorator using AdaptiveRateLimiter instance."""
        mock_indicator = MagicMock()
        mock_indicator.get_load.return_value = 0.0
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=1000,
            min_limit=100,
            max_limit=10000,
            indicators=[mock_indicator],
            update_interval=0,
        )

        @rate_limit(key="ip", rate="10/m", adaptive=limiter)
        def test_view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        response = test_view(request)
        assert response.status_code == 200

    def test_decorator_without_adaptive(self):
        """Test that decorator works normally without adaptive."""

        @rate_limit(key="ip", rate="1000/m")  # High limit
        def test_view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        response = test_view(request)
        assert response.status_code == 200

    def test_adaptive_limit_affects_rate_limiting(self):
        """Test that adaptive limit actually affects rate limiting behavior."""
        import uuid

        # Use unique key for this test to avoid interference from other tests
        unique_key = f"test_adaptive_limit_{uuid.uuid4().hex}"

        # Create a limiter that returns very low limit
        mock_indicator = MagicMock()
        mock_indicator.get_load.return_value = 1.0  # Max load
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            min_limit=1,  # Only 1 request allowed
            max_limit=1000,
            indicators=[mock_indicator],
            smoothing_factor=1.0,
            update_interval=0,
        )

        @rate_limit(key=unique_key, rate="100/m", adaptive=limiter)
        def test_view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")

        # First request should succeed
        response = test_view(request)
        assert (
            response.status_code == 200
        ), f"First request failed with {response.status_code}"

        # Second request should be rate limited (limit is 1)
        response = test_view(request)
        assert response.status_code == 429, f"Second request should be rate limited"

    def test_nonexistent_adaptive_uses_base_rate(self):
        """Test that nonexistent adaptive limiter uses base rate."""

        @rate_limit(key="ip", rate="1000/m", adaptive="nonexistent")
        def test_view(request):
            return HttpResponse("OK")

        request = self.factory.get("/test/")
        response = test_view(request)
        # Should work with base rate
        assert response.status_code == 200


class TestRatelimitAliasWithAdaptive:
    """Test that ratelimit alias supports adaptive parameter."""

    def test_ratelimit_alias_supports_adaptive(self):
        """Test that the ratelimit alias function accepts adaptive parameter."""
        from django_smart_ratelimit import ratelimit

        # Create limiter
        mock_indicator = MagicMock()
        mock_indicator.get_load.return_value = 0.0
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=100, indicators=[mock_indicator], update_interval=0
        )

        # This should not raise
        @ratelimit(key="ip", rate="10/m", adaptive=limiter)
        def test_view(request):
            return HttpResponse("OK")

        assert callable(test_view)
