"""
OpenTelemetry observability integration for Django Smart Ratelimit.

This package provides OpenTelemetry instrumentation for rate limiting operations,
including spans and metrics collection.

Usage:
    1. Install optional dependencies:
        pip install django-smart-ratelimit[opentelemetry]

    2. Initialize at application startup (e.g., in Django AppConfig.ready()):
        from django_smart_ratelimit.observability import instrument_rate_limit
        instrument_rate_limit()

    3. The library will emit spans for each rate-limit check and record metrics
       for allowed/denied requests, token consumption, and backend performance.

Example:
    In your Django app config:

        from django.apps import AppConfig
        from django_smart_ratelimit.observability import instrument_rate_limit

        class MyAppConfig(AppConfig):
            name = 'myapp'

            def ready(self):
                instrument_rate_limit()
"""

from .otel import (
    RateLimitMeter,
    RateLimitTracer,
    instrument_rate_limit,
    record_check,
    record_rate_limit_decision,
)

__all__ = [
    "instrument_rate_limit",
    "record_check",
    "record_rate_limit_decision",
    "RateLimitTracer",
    "RateLimitMeter",
]
