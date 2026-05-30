"""DRF throttling settings snippet.

Copy the REST_FRAMEWORK block into your project's settings.py. The throttle
classes share django-smart-ratelimit's backend, so RATELIMIT_BACKEND controls
where the counters are stored (defaults to in-memory if unset).
"""

# Store rate-limit counters in Redis so the limit is shared across workers.
# Omit this line to use the in-memory backend (fine for local development).
RATELIMIT_BACKEND = "redis"
RATELIMIT_REDIS = {"host": "localhost", "port": 6379, "db": 0}

REST_FRAMEWORK = {
    # Apply these throttles to every view by default. A view can override with
    # its own `throttle_classes` attribute.
    "DEFAULT_THROTTLE_CLASSES": [
        "django_smart_ratelimit.integrations.drf.UserRateLimitThrottle",
        "django_smart_ratelimit.integrations.drf.AnonRateLimitThrottle",
    ],
    # Rates are keyed by each throttle's `scope`.
    "DEFAULT_THROTTLE_RATES": {
        "user": "1000/hour",  # authenticated users, keyed on user id
        "anon": "100/hour",  # anonymous users, keyed on client IP
        "reports": "20/minute",  # used by the ScopedRateLimitThrottle view below
    },
}
