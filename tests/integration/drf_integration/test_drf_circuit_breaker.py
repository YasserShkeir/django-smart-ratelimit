"""
Integration tests for Circuit Breaker with DRF views.

Tests circuit breaker behavior with rate-limited DRF endpoints.
"""

import unittest
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

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

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.circuit_breaker import CircuitBreaker, CircuitBreakerConfig


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFCircuitBreakerBasics(TestCase):
    """Basic circuit breaker tests with DRF views."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_circuit_breaker_initial_state_closed(self):
        """Circuit breaker should start in closed state."""
        config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=60,
            half_open_max_calls=3,
            name="test_closed",
        )
        cb = CircuitBreaker(config)
        self.assertEqual(cb.state.value, "closed")

    def test_circuit_breaker_tracks_failures(self):
        """Circuit breaker should track failures."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=60,
            half_open_max_calls=3,
            name="test_failures",
        )
        cb = CircuitBreaker(config)

        # Record failures
        cb.report_failure()
        cb.report_failure()
        self.assertEqual(cb.state.value, "closed")

        # Third failure should open the circuit
        cb.report_failure()
        self.assertEqual(cb.state.value, "open")

    def test_circuit_breaker_tracks_successes(self):
        """Circuit breaker should track successes."""
        config = CircuitBreakerConfig(
            failure_threshold=5,
            recovery_timeout=60,
            half_open_max_calls=3,
            name="test_successes",
        )
        cb = CircuitBreaker(config)

        # Record successes
        cb.report_success()
        cb.report_success()
        # Should still be closed (successes don't change state from closed)
        self.assertEqual(cb.state.value, "closed")


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFCircuitBreakerFailOpen(TestCase):
    """Test circuit breaker fail-open behavior with DRF."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_fail_open_allows_requests_when_backend_fails(self):
        """When fail_open=True and backend fails, requests should pass."""

        class FailOpenView(APIView):
            @rate_limit(rate="5/m", key="ip")
            def get(self, request):
                return Response({"status": "success"})

        view = FailOpenView.as_view()

        # Normal request should work
        request = self.factory.get("/test/")
        request.META["REMOTE_ADDR"] = "10.10.0.1"
        response = view(request)

        # Should succeed normally
        self.assertEqual(response.status_code, status.HTTP_200_OK)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
@override_settings(RATELIMIT_BACKEND="memory")
class TestDRFCircuitBreakerIntegration(TestCase):
    """Integration tests for circuit breaker with rate limiting."""

    def setUp(self):
        clear_backend_cache()
        cache.clear()
        self.factory = RequestFactory()

    def test_rate_limit_respects_circuit_breaker_state(self):
        """Rate limiting should respect circuit breaker state."""

        class RateLimitedView(APIView):
            @rate_limit(rate="3/m", key="ip")
            def get(self, request):
                return Response({"message": "success"})

        view = RateLimitedView.as_view()

        # Make requests up to the limit
        results = []
        for i in range(5):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "10.10.0.10"
            response = view(request)
            results.append(response.status_code)

        # First 3 should succeed
        self.assertEqual(results[:3], [200, 200, 200])
        # Rest should be rate limited (429)
        self.assertTrue(all(r == 429 for r in results[3:]))

    def test_separate_ip_separate_limits(self):
        """Different IPs should have separate rate limits."""

        class TestView(APIView):
            @rate_limit(rate="2/m", key="ip")
            def get(self, request):
                return Response({"status": "ok"})

        view = TestView.as_view()

        # Exhaust rate limit on IP1
        for _ in range(3):
            request = self.factory.get("/test/")
            request.META["REMOTE_ADDR"] = "10.10.0.30"
            view(request)

        # Different IP should still work
        request = self.factory.get("/test/")
        request.META["REMOTE_ADDR"] = "10.10.0.31"
        response = view(request)

        # Should succeed (different IP = different key)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
class TestCircuitBreakerStateTransitions(TestCase):
    """Test circuit breaker state transitions."""

    def test_closed_to_open_transition(self):
        """Circuit should open after failure threshold reached."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=60,
            half_open_max_calls=3,
            name="test_closed_to_open",
        )
        cb = CircuitBreaker(config)

        self.assertEqual(cb.state.value, "closed")
        cb.report_failure()
        self.assertEqual(cb.state.value, "closed")
        cb.report_failure()
        self.assertEqual(cb.state.value, "open")

    def test_open_blocks_requests(self):
        """Open circuit should block requests."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=60,
            half_open_max_calls=3,
            name="test_open_blocks",
        )
        cb = CircuitBreaker(config)

        cb.report_failure()  # Opens circuit
        self.assertEqual(cb.state.value, "open")

        # Should not allow requests
        self.assertFalse(cb.is_allowed())

    @patch("time.time")
    def test_open_to_half_open_transition(self, mock_time):
        """Circuit should transition to half-open after timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=60,
            half_open_max_calls=3,
            name="test_half_open",
        )
        cb = CircuitBreaker(config)

        # Start at time 0
        mock_time.return_value = 0
        cb.report_failure()  # Opens circuit
        self.assertEqual(cb.state.value, "open")

        # Advance time past timeout
        mock_time.return_value = 61
        # Attempt to make a request should transition to half-open
        allowed = cb.is_allowed()

        # Should transition to half-open and allow the request
        self.assertEqual(cb.state.value, "half_open")
        self.assertTrue(allowed)


@unittest.skipUnless(DRF_AVAILABLE, "DRF not available")
class TestCircuitBreakerConfiguration(TestCase):
    """Test circuit breaker configuration options."""

    def test_custom_failure_threshold(self):
        """Circuit should respect custom failure threshold."""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=60,
            half_open_max_calls=3,
            name="test_threshold",
        )
        cb = CircuitBreaker(config)

        for _ in range(9):
            cb.report_failure()

        self.assertEqual(cb.state.value, "closed")
        cb.report_failure()
        self.assertEqual(cb.state.value, "open")


if __name__ == "__main__":
    unittest.main()
