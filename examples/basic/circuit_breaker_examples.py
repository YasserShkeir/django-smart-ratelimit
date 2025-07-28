"""
Circuit Breaker Pattern Example for Django Smart Ratelimit.

This example demonstrates how to use circuit breakers to protect your
application from backend failures.
"""

import time

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from django_smart_ratelimit import (
    CircuitBreakerError,
    circuit_breaker,
    get_backend,
    rate_limit,
)


# Example 1: Basic Circuit Breaker with Rate Limiting
@rate_limit(key="ip", rate="100/h")
def api_with_circuit_breaker(request):
    """
    API endpoint with both rate limiting and circuit breaker protection.

    The rate limiting backend has circuit breaker enabled by default.
    """
    try:
        # Your normal business logic here
        data = process_api_request(request)
        return JsonResponse(
            {"status": "success", "data": data, "circuit_breaker": "closed"}
        )
    except CircuitBreakerError:
        # Circuit breaker is open - backend is failing
        return JsonResponse(
            {
                "error": "Service temporarily unavailable",
                "message": "Backend service is recovering. Please try again later.",
                "circuit_breaker": "open",
                "retry_after": 60,
            },
            status=503,
        )


# Example 2: Manual Circuit Breaker Usage
@circuit_breaker(name="external_service", failure_threshold=3)
def call_external_service(api_key):
    """
    Function protected by circuit breaker for external service calls.
    """
    import requests

    response = requests.get(
        "https://api.example.com/data",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


@require_http_methods(["GET"])
def external_data_view(request):
    """
    View that calls external service with circuit breaker protection.
    """
    api_key = request.GET.get("api_key")
    if not api_key:
        return JsonResponse({"error": "API key required"}, status=400)

    try:
        data = call_external_service(api_key)
        return JsonResponse(
            {"status": "success", "data": data, "source": "external_api"}
        )
    except CircuitBreakerError:
        # Circuit breaker is protecting the external service
        cached_data = get_cached_external_data()
        return JsonResponse(
            {
                "status": "degraded",
                "data": cached_data,
                "source": "cache",
                "message": "Using cached data due to external service issues",
            }
        )
    except Exception as e:
        return JsonResponse(
            {"error": "External service error", "message": str(e)}, status=502
        )


# Example 3: Backend Health Monitoring
def backend_health_view(request):
    """
    View to check backend health and circuit breaker status.
    """
    backend = get_backend()
    health_status = backend.get_backend_health_status()

    # Get detailed circuit breaker status if available
    circuit_breaker_details = None
    if health_status.get("circuit_breaker_enabled"):
        cb_status = backend.get_circuit_breaker_status()
        if cb_status:
            circuit_breaker_details = {
                "state": cb_status["state"],
                "failure_count": cb_status["failure_count"],
                "failure_threshold": cb_status["failure_threshold"],
                "stats": cb_status["stats"],
            }

    return JsonResponse(
        {
            "backend_health": health_status,
            "circuit_breaker": circuit_breaker_details,
            "timestamp": int(time.time()),
        }
    )


# Example 4: Custom Circuit Breaker Configuration
def create_custom_backend():
    """
    Create a backend with custom circuit breaker configuration.
    """
    from django_smart_ratelimit import MemoryBackend

    # Custom configuration for sensitive operations
    sensitive_config = {
        "failure_threshold": 2,  # Open after just 2 failures
        "recovery_timeout": 30,  # Quick recovery attempts
        "reset_timeout": 180,  # Reset after 3 minutes of success
    }

    backend = MemoryBackend(
        enable_circuit_breaker=True, circuit_breaker_config=sensitive_config
    )

    return backend


# Example 5: Graceful Degradation Pattern
@rate_limit(key="user", rate="50/h", block=False)
def user_dashboard(request):
    """
    User dashboard with graceful degradation when rate limiting fails.
    """
    user_id = request.user.id

    try:
        # Try to get real-time data
        dashboard_data = get_realtime_dashboard_data(user_id)
        data_source = "realtime"
    except CircuitBreakerError:
        # Circuit breaker is open, use cached data
        dashboard_data = get_cached_dashboard_data(user_id)
        data_source = "cache"
    except Exception:
        # Other errors, use minimal data
        dashboard_data = get_minimal_dashboard_data(user_id)
        data_source = "minimal"

    return JsonResponse(
        {"data": dashboard_data, "source": data_source, "user_id": user_id}
    )


# Example 6: Circuit Breaker Status for Monitoring
def monitoring_endpoint(request):
    """
    Monitoring endpoint for circuit breaker status.
    """
    from django_smart_ratelimit import circuit_breaker_registry

    # Get all circuit breaker statuses
    all_statuses = circuit_breaker_registry.get_all_status()

    summary = {
        "total_breakers": len(all_statuses),
        "healthy_breakers": sum(
            1 for status in all_statuses.values() if status["state"] == "closed"
        ),
        "failing_breakers": sum(
            1 for status in all_statuses.values() if status["state"] == "open"
        ),
        "testing_breakers": sum(
            1 for status in all_statuses.values() if status["state"] == "half_open"
        ),
        "breakers": all_statuses,
    }

    # Return appropriate HTTP status
    if summary["failing_breakers"] > 0:
        status_code = 503  # Service Unavailable
    elif summary["testing_breakers"] > 0:
        status_code = 200  # OK but some are testing
    else:
        status_code = 200  # All OK

    return JsonResponse(summary, status=status_code)


# Helper Functions
def process_api_request(request):
    """Simulate API request processing."""
    import random
    import time

    # Simulate processing time
    time.sleep(0.1)

    # Simulate occasional failures (for demonstration)
    if random.random() < 0.05:  # 5% failure rate
        raise Exception("Simulated backend failure")

    return {
        "request_id": f"req_{int(time.time())}",
        "data": f"Processed for {request.META.get('REMOTE_ADDR', 'unknown')}",
    }


def get_cached_external_data():
    """Get cached data as fallback."""
    return {
        "cached": True,
        "data": "This is cached data from when the external service was working",
        "cache_timestamp": int(time.time()) - 300,  # 5 minutes ago
    }


def get_realtime_dashboard_data(user_id):
    """Get real-time dashboard data."""
    return {
        "user_id": user_id,
        "realtime_stats": "Current data from backend",
        "timestamp": int(time.time()),
    }


def get_cached_dashboard_data(user_id):
    """Get cached dashboard data."""
    return {
        "user_id": user_id,
        "cached_stats": "Cached data from recent backend call",
        "timestamp": int(time.time()) - 60,  # 1 minute ago
    }


def get_minimal_dashboard_data(user_id):
    """Get minimal dashboard data."""
    return {
        "user_id": user_id,
        "minimal_stats": "Basic user information",
        "timestamp": int(time.time()),
    }


# Django URLs Configuration Example
"""
# urls.py
from django.urls import path
from . import circuit_breaker_examples

urlpatterns = [
    path('api/data/', circuit_breaker_examples.api_with_circuit_breaker, name='api_data'),
    path('api/external/', circuit_breaker_examples.external_data_view, name='external_data'),
    path('health/', circuit_breaker_examples.backend_health_view, name='backend_health'),
    path('dashboard/', circuit_breaker_examples.user_dashboard, name='user_dashboard'),
    path('monitoring/', circuit_breaker_examples.monitoring_endpoint, name='monitoring'),
]
"""

# Settings Configuration Example
"""
# settings.py

# Global circuit breaker configuration
RATELIMIT_CIRCUIT_BREAKER = {
    'failure_threshold': 5,
    'recovery_timeout': 60,
    'reset_timeout': 300,
    'half_open_max_calls': 1,
    'exponential_backoff_multiplier': 2.0,
    'exponential_backoff_max': 300,
}

# Backend configuration with circuit breaker
RATELIMIT_BACKEND = 'redis'  # Circuit breaker enabled by default

# Multi-backend with custom circuit breaker settings
RATELIMIT_BACKENDS = [
    {
        'type': 'django_smart_ratelimit.backends.redis_backend.RedisBackend',
        'name': 'primary_redis',
        'options': {
            'enable_circuit_breaker': True,
            'circuit_breaker_config': {
                'failure_threshold': 5,
                'recovery_timeout': 60,
            }
        }
    },
    {
        'type': 'django_smart_ratelimit.backends.memory.MemoryBackend',
        'name': 'fallback_memory',
        'options': {
            'enable_circuit_breaker': True,
            'circuit_breaker_config': {
                'failure_threshold': 10,  # More tolerant for fallback
                'recovery_timeout': 30,
            }
        }
    }
]
"""
