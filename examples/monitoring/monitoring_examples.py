#!/usr/bin/env python3
"""
Monitoring and Health Check Examples

This demonstrates how to monitor rate limiting backends,
implement health checks, and track rate limiting metrics.
"""

import logging
import time
from typing import Any, Dict

from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.utils import timezone

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import get_backend

# Configure logging
logger = logging.getLogger(__name__)


# Example 1: Backend health check endpoint
def backend_health_check(_request: HttpRequest) -> JsonResponse:
    """
    Health check endpoint for rate limiting backends.

    This endpoint checks the health of all configured backends
    and returns their status.
    """
    backend = get_backend()
    health_data: Dict[str, Any] = {
        "timestamp": timezone.now().isoformat(),
        "backend_type": type(backend).__name__,
        "status": "healthy",
    }

    try:
        # Test backend with a health check key
        test_key = f"health_check_{int(time.time())}"

        # Test basic operations
        count = backend.incr(test_key, 60)
        assert count == 1, f"Expected count 1, got {count}"

        retrieved_count = backend.get_count(test_key)
        assert retrieved_count == 1, f"Expected count 1, got {retrieved_count}"

        reset_time = backend.get_reset_time(test_key)
        assert reset_time is not None, "Expected reset time"

        # Clean up test key
        backend.reset(test_key)

        # Multi-backend specific checks
        if hasattr(backend, "get_backend_status"):
            backend_status = backend.get_backend_status()
            if hasattr(backend, "get_stats"):
                stats = backend.get_stats()
            else:
                stats = {}

            health_data.update(
                {
                    "multi_backend": True,
                    "backend_status": backend_status,
                    "total_backends": stats.get("total_backends", 0),
                    "healthy_backends": stats.get("healthy_backends", 0),
                    "fallback_strategy": stats.get("fallback_strategy", "unknown"),
                }
            )
        else:
            health_data["multi_backend"] = False

    except Exception as e:
        logger.error(f"Backend health check failed: {e}")
        health_data.update({"status": "unhealthy", "error": str(e)})

        return JsonResponse(health_data, status=503)

    return JsonResponse(health_data)


# Example 2: Rate limiting metrics endpoint
def rate_limit_metrics(_request: HttpRequest) -> JsonResponse:
    """
    Metrics endpoint for rate limiting statistics.

    This endpoint provides metrics about rate limiting activity.
    """
    backend = get_backend()
    metrics_data = {
        "timestamp": timezone.now().isoformat(),
        "backend_type": type(backend).__name__,
    }

    try:
        # Get backend-specific metrics
        if hasattr(backend, "get_stats"):
            stats = backend.get_stats()
            metrics_data.update(stats)

        # Get cached metrics (accumulated over time)
        metrics_cache_key = "rate_limit_metrics"
        cached_metrics = cache.get(metrics_cache_key, {})

        metrics_data.update(
            {
                "total_requests": cached_metrics.get("total_requests", 0),
                "blocked_requests": cached_metrics.get("blocked_requests", 0),
                "blocked_percentage": (
                    cached_metrics.get("blocked_requests", 0)
                    / max(cached_metrics.get("total_requests", 1), 1)
                    * 100
                ),
                "active_keys": cached_metrics.get("active_keys", 0),
                "uptime_seconds": cached_metrics.get("uptime_seconds", 0),
            }
        )

    except Exception as e:
        logger.error(f"Failed to get rate limit metrics: {e}")
        metrics_data.update({"error": str(e)})

        return JsonResponse(metrics_data, status=500)

    return JsonResponse(metrics_data)


# Example 3: Rate limit status for a specific key
def rate_limit_status(_request: HttpRequest) -> JsonResponse:
    """
    Get rate limit status for a specific key.

    This endpoint shows the current rate limit status for a key.
    """
    key = _request.GET.get("key")
    if not key:
        return JsonResponse({"error": "Key parameter required"}, status=400)

    backend = get_backend()

    try:
        status_data = {
            "key": key,
            "timestamp": timezone.now().isoformat(),
            "current_count": backend.get_count(key),
            "reset_time": backend.get_reset_time(key),
            "backend_type": type(backend).__name__,
        }

        # Calculate time until reset
        reset_time = backend.get_reset_time(key)
        if reset_time:
            current_time = int(time.time())
            time_until_reset = max(0, reset_time - current_time)
            status_data["time_until_reset_seconds"] = time_until_reset

        return JsonResponse(status_data)

    except Exception as e:
        logger.error(f"Failed to get rate limit status for key {key}: {e}")
        return JsonResponse({"error": str(e)}, status=500)


# Example 4: Monitoring decorator with metrics collection
def monitoring_key_function(_request: HttpRequest) -> str:
    """Key function that includes monitoring metadata."""
    ip = _request.META.get("REMOTE_ADDR", "unknown")
    endpoint = _request.path
    return f"monitor:{endpoint}:ip:{ip}"


@rate_limit(key=monitoring_key_function, rate="100/h")
def monitored_api(_request: HttpRequest) -> JsonResponse:
    """
    API endpoint with built-in monitoring.

    This endpoint collects metrics about rate limiting activity.
    """
    # Update metrics in cache
    metrics_cache_key = "rate_limit_metrics"
    cached_metrics = cache.get(metrics_cache_key, {})

    # Increment total requests
    cached_metrics["total_requests"] = cached_metrics.get("total_requests", 0) + 1

    # Track endpoint-specific metrics
    endpoint_metrics_key = f"endpoint_metrics:{_request.path}"
    endpoint_metrics = cache.get(endpoint_metrics_key, {})
    endpoint_metrics["requests"] = endpoint_metrics.get("requests", 0) + 1
    endpoint_metrics["last_request"] = timezone.now().isoformat()

    # Update cache
    cache.set(metrics_cache_key, cached_metrics, timeout=86400)  # 24 hours
    cache.set(endpoint_metrics_key, endpoint_metrics, timeout=86400)

    return JsonResponse(
        {
            "monitored_data": "Data from monitored endpoint",
            "request_count": endpoint_metrics.get("requests", 0),
            "rate_limit": "100 requests per hour",
        }
    )


# Example 5: Rate limiting with alerting
def alerting_key_function(_request: HttpRequest) -> str:
    """Key function that triggers alerts on high usage."""
    ip = _request.META.get("REMOTE_ADDR", "unknown")
    return f"alert:ip:{ip}"


@rate_limit(key=alerting_key_function, rate="50/h")
def alerting_api(_request: HttpRequest) -> JsonResponse:
    """
    API endpoint with rate limiting alerts.

    This endpoint triggers alerts when rate limits are approached.
    """
    backend = get_backend()
    key = alerting_key_function(_request)

    try:
        current_count = backend.get_count(key)
        rate_limit = 50  # requests per hour

        # Check if we're approaching the limit
        if current_count >= rate_limit * 0.8:  # 80% of limit
            # Log warning
            logger.warning(
                f"Rate limit warning: {key} at {current_count}/{rate_limit} requests"
            )

            # Could trigger external alerting here
            # send_alert(f"Rate limit warning for {key}")

        if current_count >= rate_limit * 0.9:  # 90% of limit
            # Log critical warning
            logger.critical(
                f"Rate limit critical: {key} at {current_count}/{rate_limit} requests"
            )

            # Could trigger urgent alerting here
            # send_urgent_alert(f"Rate limit critical for {key}")

    except Exception as e:
        logger.error(f"Failed to check rate limit for alerting: {e}")

    return JsonResponse(
        {
            "alerting_data": "Data from alerting endpoint",
            "rate_limit": "50 requests per hour with alerting",
        }
    )


# Example 6: Performance monitoring
def performance_monitoring_key(_request: HttpRequest) -> str:
    """Key function for performance monitoring."""
    ip = _request.META.get("REMOTE_ADDR", "unknown")
    return f"perf:ip:{ip}"


@rate_limit(key=performance_monitoring_key, rate="200/h")
def performance_monitored_api(_request: HttpRequest) -> JsonResponse:
    """
    API endpoint with performance monitoring.

    This endpoint tracks performance metrics for rate limiting.
    """
    start_time = time.time()

    try:
        backend = get_backend()
        key = performance_monitoring_key(_request)

        # Measure rate limit check time
        check_start = time.time()
        current_count = backend.get_count(key)
        check_duration = time.time() - check_start

        # Log performance metrics
        logger.info(f"Rate limit check took {check_duration:.3f}s for key {key}")

        # Store performance metrics
        perf_metrics_key = "rate_limit_performance"
        perf_metrics = cache.get(perf_metrics_key, [])
        perf_metrics.append(
            {
                "timestamp": timezone.now().isoformat(),
                "check_duration": check_duration,
                "key": key,
                "backend_type": type(backend).__name__,
            }
        )

        # Keep only last 100 measurements
        if len(perf_metrics) > 100:
            perf_metrics = perf_metrics[-100:]

        cache.set(perf_metrics_key, perf_metrics, timeout=3600)  # 1 hour

        total_duration = time.time() - start_time

        return JsonResponse(
            {
                "performance_data": "Performance monitored data",
                "check_duration_ms": check_duration * 1000,
                "total_duration_ms": total_duration * 1000,
                "current_count": current_count,
                "rate_limit": "200 requests per hour",
            }
        )

    except Exception as e:
        logger.error(f"Performance monitoring failed: {e}")
        return JsonResponse({"error": str(e)}, status=500)


# Example 7: Dashboard data endpoint
def dashboard_data(_request: HttpRequest) -> JsonResponse:
    """
    Dashboard data endpoint for rate limiting visualization.

    This endpoint provides data for rate limiting dashboards.
    """
    try:
        backend = get_backend()

        # Collect dashboard data
        dashboard_data: Dict[str, Any] = {
            "timestamp": timezone.now().isoformat(),
            "backend_info": {"type": type(backend).__name__, "healthy": True},
        }

        # Get metrics from cache
        metrics_cache_key = "rate_limit_metrics"
        cached_metrics = cache.get(metrics_cache_key, {})

        dashboard_data.update(
            {
                "total_requests": cached_metrics.get("total_requests", 0),
                "blocked_requests": cached_metrics.get("blocked_requests", 0),
                "success_rate": (
                    (
                        cached_metrics.get("total_requests", 0)
                        - cached_metrics.get("blocked_requests", 0)
                    )
                    / max(cached_metrics.get("total_requests", 1), 1)
                    * 100
                ),
            }
        )

        # Get performance metrics
        perf_metrics_key = "rate_limit_performance"
        perf_metrics = cache.get(perf_metrics_key, [])

        if perf_metrics:
            avg_check_duration = sum(m["check_duration"] for m in perf_metrics) / len(
                perf_metrics
            )
            dashboard_data["average_check_duration_ms"] = avg_check_duration * 1000

        # Multi-backend specific data
        if hasattr(backend, "get_backend_status"):
            backend_status = backend.get_backend_status()
            if hasattr(backend, "get_stats"):
                stats = backend.get_stats()
            else:
                stats = {}

            dashboard_data.update(
                {
                    "multi_backend": True,
                    "backend_status": str(backend_status),
                    "backend_stats": stats,
                }
            )

        return JsonResponse(dashboard_data)

    except Exception as e:
        logger.error(f"Dashboard data collection failed: {e}")
        return JsonResponse({"error": str(e)}, status=500)


# Django URLs configuration example
"""
# urls.py

from django.urls import path
from . import monitoring_examples

urlpatterns = [
    # Monitoring endpoints
    path('api/health/', monitoring_examples.backend_health_check, name='backend_health'),
    path('api/metrics/', monitoring_examples.rate_limit_metrics, name='rate_limit_metrics'),
    path('api/status/', monitoring_examples.rate_limit_status, name='rate_limit_status'),
    path('api/dashboard/', monitoring_examples.dashboard_data, name='dashboard_data'),

    # Monitored API endpoints
    path('api/monitored/', monitoring_examples.monitored_api, name='monitored_api'),
    path('api/alerting/', monitoring_examples.alerting_api, name='alerting_api'),
    path('api/performance/', monitoring_examples.performance_monitored_api, name='performance_api'),
]
"""

# Django settings configuration example
"""
# settings.py

# Logging configuration for rate limiting
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'rate_limit_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'rate_limit.log',
        },
        'rate_limit_console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django_smart_ratelimit': {
            'handlers': ['rate_limit_file', 'rate_limit_console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

# Cache configuration for metrics
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Rate limiting monitoring configuration
RATELIMIT_MONITORING = {
    'ENABLED': True,
    'METRICS_CACHE_TIMEOUT': 86400,  # 24 hours
    'PERFORMANCE_CACHE_TIMEOUT': 3600,  # 1 hour
    'ALERT_THRESHOLD': 0.8,  # Alert at 80% of limit
    'CRITICAL_THRESHOLD': 0.9,  # Critical alert at 90% of limit
}
"""

if __name__ == "__main__":
    print("Monitoring and Health Check Examples")
    print("=" * 40)
    print("This file demonstrates monitoring and health check patterns.")
    print("Configure logging and caching for production monitoring.")
    print("Set up external alerting services for production deployments.")
