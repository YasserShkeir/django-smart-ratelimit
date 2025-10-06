"""
Consolidated Test Utilities for Rate Limiting Tests

This module provides streamlined test utilities that eliminate duplication
across the test suite while providing comprehensive testing capabilities.
"""

from contextlib import contextmanager
from typing import Any, Callable, Dict, List
from unittest.mock import Mock, patch

import pytest

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from django_smart_ratelimit import rate_limit
from tests.utils import create_test_user


class RateLimitTestCase(TestCase):
    """
    Enhanced base test case for rate limiting tests.

    Provides common patterns and utilities to eliminate code duplication
    across all rate limiting test files.
    """

    def setUp(self):
        """Set up common test fixtures."""
        super().setUp()
        self.user = create_test_user()
        self.factory = RequestFactory()

    def create_rate_limited_view(
        self,
        key: str = "test",
        rate: str = "10/m",
        block: bool = True,
        backend: str = None,
        skip_if: Callable = None,
        algorithm: str = None,
        algorithm_config: Dict = None,
    ):
        """
        Factory method to create rate limited views with specified parameters.

        This eliminates the need to define similar views in every test.
        """

        @rate_limit(
            key=key,
            rate=rate,
            block=block,
            backend=backend,
            skip_if=skip_if,
            algorithm=algorithm,
            algorithm_config=algorithm_config,
        )
        def test_view(request):
            return HttpResponse("Success")

        return test_view

    def assert_rate_limit_behavior(
        self,
        view_func: Callable,
        request,
        expected_status: int,
        should_call_backend: bool = True,
        backend_call_count: int = 1,
    ):
        """
        Assert expected rate limiting behavior.

        This consolidates common assertion patterns.
        """
        response = view_func(request)
        self.assertEqual(response.status_code, expected_status)

        if should_call_backend:
            # Additional backend call assertions can be added here
            pass

        return response

    def create_mock_backend(self, incr_return_value: int = 1, **kwargs):
        """
        Create a properly configured mock backend.

        This eliminates repeated mock backend setup.
        """
        mock_backend = Mock()
        mock_backend.incr.return_value = incr_return_value
        mock_backend.get_count.return_value = incr_return_value
        mock_backend.get_reset_time.return_value = 3600
        mock_backend.config = {}

        # Apply any additional configuration
        for attr, value in kwargs.items():
            setattr(mock_backend, attr, value)

        return mock_backend

    @pytest.fixture
    def parameterized_decorator_test(self):
        """
        Fixture for parameterized decorator tests.

        This allows running the same test logic with different parameter combinations.
        """

        def run_test(test_params: List[Dict[str, Any]], test_func: Callable):
            """Run test function with each parameter combination."""
            for params in test_params:
                with self.subTest(**params):
                    test_func(**params)

        return run_test


class DecoratorTestParameterSets:
    """
    Centralized parameter sets for decorator testing.

    This eliminates duplicate parameter definitions across test files.
    """

    RATE_FORMATS = [
        {"rate": "10/s", "expected_period": 1},
        {"rate": "100/m", "expected_period": 60},
        {"rate": "1000/h", "expected_period": 3600},
        {"rate": "10000/d", "expected_period": 86400},
    ]

    KEY_TYPES = [
        {"key_type": "string", "key": "test_key"},
        {"key_type": "ip", "key": "ip"},
        {"key_type": "user", "key": "user"},
        {"key_type": "callable", "key": lambda req: f"custom:{req.user.id}"},
    ]

    BLOCK_BEHAVIORS = [
        {"block": True, "expected_status_on_exceed": 429},
        {"block": False, "expected_status_on_exceed": 200},
    ]

    ALGORITHMS = [
        {"algorithm": "fixed_window"},
        {"algorithm": "sliding_window"},
        {"algorithm": "token_bucket"},
    ]

    BACKEND_TYPES = [
        {"backend": None},  # Default
        {"backend": "memory"},
        {"backend": "redis"},
        {"backend": "database"},
    ]

    COMPREHENSIVE_COMBINATIONS = [
        # Core functionality combinations
        {"key": "ip", "rate": "10/m", "block": True, "algorithm": "fixed_window"},
        {"key": "user", "rate": "100/h", "block": False, "algorithm": "sliding_window"},
        {
            "key": lambda req: f"api:{getattr(req, 'api_key', 'default')}",
            "rate": "1000/h",
            "block": True,
            "algorithm": "token_bucket",
        },
        # Edge cases
        {
            "key": "test",
            "rate": "1/s",
            "block": True,
            "algorithm": "fixed_window",
        },  # Very restrictive
        {
            "key": "test",
            "rate": "10000/d",
            "block": False,
            "algorithm": "sliding_window",
        },  # Very permissive
    ]


class MockBackendManager:
    """
    Centralized mock backend management.

    This provides consistent mocking across all tests that need backend mocking.
    """

    @staticmethod
    @contextmanager
    def mock_backend(backend_type: str = "default", **config):
        """
        Context manager for mocking different backend types.

        Args:
            backend_type: Type of backend to mock ('redis', 'database', 'memory', etc.)
            **config: Additional configuration for the mock
        """
        if backend_type == "redis":
            with patch(
                "django_smart_ratelimit.backends.redis_backend.redis"
            ) as mock_redis:
                mock_client = Mock()
                mock_redis.Redis.return_value = mock_client
                mock_client.ping.return_value = True
                mock_client.script_load.return_value = "script_sha"
                mock_client.evalsha.return_value = config.get("incr_return", 1)
                mock_client.ttl.return_value = config.get("ttl_return", 60)

                with patch(
                    "django_smart_ratelimit.decorator.get_backend"
                ) as mock_get_backend:
                    mock_backend = Mock()
                    mock_backend.incr.return_value = config.get("incr_return", 1)
                    mock_get_backend.return_value = mock_backend
                    yield mock_backend
        else:
            # Default mock backend
            with patch(
                "django_smart_ratelimit.decorator.get_backend"
            ) as mock_get_backend:
                mock_backend = Mock()
                mock_backend.incr.return_value = config.get("incr_return", 1)
                mock_backend.get_count.return_value = config.get("count_return", 1)
                mock_backend.get_reset_time.return_value = config.get(
                    "reset_time", 3600
                )
                mock_backend.config = {}
                mock_get_backend.return_value = mock_backend
                yield mock_backend


class RateLimitAssertions:
    """
    Centralized assertion helpers for rate limiting tests.

    This provides consistent assertion patterns across all test files.
    """

    @staticmethod
    def assert_rate_limit_headers(response, limit: int = None, remaining: int = None):
        """Assert that rate limit headers are present and correct."""
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

        if limit is not None:
            assert response.headers["X-RateLimit-Limit"] == str(limit)
        if remaining is not None:
            assert response.headers["X-RateLimit-Remaining"] == str(remaining)

    @staticmethod
    def assert_backend_called_correctly(
        mock_backend, expected_calls: int = 1, key_pattern: str = None
    ):
        """Assert that backend was called correctly."""
        assert mock_backend.incr.call_count == expected_calls

        if key_pattern:
            # Check that the key matches expected pattern
            call_args = mock_backend.incr.call_args[0]
            assert key_pattern in call_args[0]

    @staticmethod
    def assert_rate_limited_response(response, expected_status: int = 429):
        """Assert that response indicates rate limiting."""
        assert response.status_code == expected_status
        if expected_status == 429:
            from django.http import HttpResponseTooManyRequests

            assert isinstance(response, HttpResponseTooManyRequests)

    @staticmethod
    def assert_successful_response(response, expected_content: str = "Success"):
        """Assert that response is successful."""
        assert response.status_code == 200
        if expected_content:
            assert response.content.decode() == expected_content


def create_test_scenarios():
    """
    Create comprehensive test scenarios for different decorator configurations.

    This provides a centralized way to generate test scenarios that cover
    all important combinations without duplication.
    """
    scenarios = []

    # Basic functionality scenarios
    basic_scenarios = [
        {
            "name": "within_limit_success",
            "config": {"key": "test", "rate": "10/m", "block": True},
            "mock_incr_return": 5,
            "expected_status": 200,
            "should_have_headers": True,
        },
        {
            "name": "exceed_limit_blocked",
            "config": {"key": "test", "rate": "10/m", "block": True},
            "mock_incr_return": 11,
            "expected_status": 429,
            "should_have_headers": False,
        },
        {
            "name": "exceed_limit_not_blocked",
            "config": {"key": "test", "rate": "10/m", "block": False},
            "mock_incr_return": 11,
            "expected_status": 200,
            "should_have_headers": True,
        },
    ]

    # Key type scenarios
    key_scenarios = [
        {
            "name": "ip_key",
            "config": {"key": "ip", "rate": "10/m"},
            "request_setup": lambda req: setattr(
                req, "META", {"REMOTE_ADDR": "192.168.1.1"}
            ),
            "expected_key_pattern": "ip:192.168.1.1",
        },
        {
            "name": "user_key",
            "config": {"key": "user", "rate": "10/m"},
            "request_setup": lambda req: setattr(req, "user", create_test_user()),
            "expected_key_pattern": "user:",
        },
    ]

    # Algorithm scenarios
    algorithm_scenarios = [
        {
            "name": "fixed_window",
            "config": {"key": "test", "rate": "10/m", "algorithm": "fixed_window"},
            "expected_algorithm": "fixed_window",
        },
        {
            "name": "sliding_window",
            "config": {"key": "test", "rate": "10/m", "algorithm": "sliding_window"},
            "expected_algorithm": "sliding_window",
        },
        {
            "name": "token_bucket",
            "config": {
                "key": "test",
                "rate": "10/m",
                "algorithm": "token_bucket",
                "algorithm_config": {"bucket_size": 20},
            },
            "expected_algorithm": "token_bucket",
        },
    ]

    scenarios.extend(basic_scenarios)
    scenarios.extend(key_scenarios)
    scenarios.extend(algorithm_scenarios)

    return scenarios
