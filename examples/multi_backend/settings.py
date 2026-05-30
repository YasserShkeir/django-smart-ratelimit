"""Multi-backend failover settings snippet.

Copy these into your project's settings.py. Defining RATELIMIT_BACKENDS makes
django-smart-ratelimit pick the multi-backend wrapper automatically; do not set
RATELIMIT_BACKEND yourself when using this.
"""

# Each entry is a dict with: name, backend (alias or dotted path), and config.
# Backends are tried in order according to RATELIMIT_MULTI_BACKEND_STRATEGY.
RATELIMIT_BACKENDS = [
    {
        "name": "primary_redis",
        "backend": "redis",
        "config": {
            "host": "redis-primary.example.com",
            "port": 6379,
            "db": 0,
        },
    },
    {
        # In-memory fallback so requests are still limited (per process) if
        # Redis is down. Swap for a second Redis instance in production if you
        # need shared state during failover.
        "name": "fallback_memory",
        "backend": "memory",
        "config": {},
    },
]

# How the wrapper chooses which backend to use. "first_healthy" (the default)
# uses the first backend that passes a health check and fails over to the next.
RATELIMIT_MULTI_BACKEND_STRATEGY = "first_healthy"
