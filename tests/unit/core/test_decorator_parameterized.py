"""Parameterized tests for decorator."""

from unittest.mock import Mock, patch

import pytest

from django.http import HttpResponse

from django_smart_ratelimit import rate_limit


@pytest.mark.parametrize(
    "algorithm", ["fixed_window", "sliding_window", "token_bucket"]
)
@patch("django_smart_ratelimit.decorator.get_backend")
def test_decorator_algorithm_selection(mock_get_backend, algorithm, request_factory):
    """Test decorator with different algorithms."""
    mock_backend = Mock()
    mock_backend.incr.return_value = 1
    mock_backend.increment.return_value = (1, 9)
    mock_backend.config = {}
    mock_get_backend.return_value = mock_backend

    @rate_limit(key="test", rate="10/m", algorithm=algorithm)
    def test_view(request):
        return HttpResponse("Success")

    request = request_factory.get("/")
    response = test_view(request)

    assert response.status_code == 200
    # Verify algorithm was set on backend config
    assert mock_backend.config["algorithm"] == algorithm


@pytest.mark.parametrize(
    "key_type, rate, block, algorithm",
    [
        ("ip", "10/s", True, "fixed_window"),
        ("user", "100/m", False, "sliding_window"),
        ("api_key", "1000/h", True, "token_bucket"),
        ("custom", "50/m", False, "fixed_window"),
    ],
)
@patch("django_smart_ratelimit.decorator.get_backend")
def test_decorator_parameter_combinations(
    mock_get_backend, key_type, rate, block, algorithm, request_factory
):
    """Test various combinations of decorator parameters."""
    mock_backend = Mock()
    mock_backend.incr.return_value = 1
    mock_backend.increment.return_value = (1, 9)
    mock_backend.config = {}
    mock_get_backend.return_value = mock_backend

    # Create appropriate key function based on type
    if key_type == "ip":
        key = "ip"
    elif key_type == "user":
        key = "user"
    elif key_type == "api_key":
        key = (
            lambda req, *args, **kwargs: f"api_key:{getattr(req, 'api_key', 'default')}"
        )
    else:
        key = "custom_key"

    @rate_limit(key=key, rate=rate, block=block, algorithm=algorithm)
    def test_view(request):
        return HttpResponse("Success")

    request = request_factory.get("/")
    response = test_view(request)

    assert response.status_code == 200
