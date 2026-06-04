# Installation

## Requirements

- Python 3.9 - 3.13
- Django 3.2 - 5.1
- Redis (recommended for production)
    - For async support, `redis-py` >= 4.2.0 is required.

The only hard dependencies are `Django>=3.2` and `asgiref>=3.6.0`. Everything else
(Redis, MongoDB, JWT, DRF, Prometheus, OpenTelemetry) is an optional extra.

## Basic Installation

Install using pip:

```bash
pip install django-smart-ratelimit
```

To install with Redis support (recommended):

```bash
pip install "django-smart-ratelimit[redis]"
```

### Optional Extras

Install only the backends and integrations you need:

| Extra | Installs | Use for |
| --- | --- | --- |
| `redis` | `redis`, `hiredis` | Redis backend (recommended for production) |
| `mongodb` | `pymongo` | MongoDB backend |
| `memcached` | `pymemcache` | Memcached backend (fixed-window) |
| `jwt` | `PyJWT` | JWT-based rate limit keys |
| `drf` | `djangorestframework` | DRF throttle adapter (new in v3.0.0) |
| `prometheus` | `prometheus-client` | Prometheus metrics |
| `opentelemetry` | `opentelemetry-api`, `opentelemetry-sdk` | OpenTelemetry tracing |
| `all` | all of the above | Install everything |

```bash
# A single extra
pip install "django-smart-ratelimit[drf]"

# Several at once
pip install "django-smart-ratelimit[redis,prometheus]"

# Everything
pip install "django-smart-ratelimit[all]"
```

## Django Configuration

Add to `INSTALLED_APPS` in `settings.py`:

```python
INSTALLED_APPS = [
    # ...
    'django_smart_ratelimit',
]
```

## Middleware Setup

Add the middleware to your `MIDDLEWARE` setting. It should handle rate limiting before the view is executed but after authentication if you strictly need access to the user object (though the decorator handles this too).

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # ...
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_smart_ratelimit.middleware.RateLimitMiddleware',  # Add this
]
```

## Basic Settings

In your `settings.py`, configure the backend:

`RATELIMIT_BACKEND` accepts a short name (`"redis"`, `"memory"`, `"mongodb"`,
`"database"`, `"multi"`) or a dotted path to a backend class. When unset, the
in-memory backend is used.

```python
# Use Redis (recommended)
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
}
# Alternatively, configure Redis with a URL:
# RATELIMIT_REDIS = {'url': 'redis://localhost:6379/0'}

# OR use the in-memory backend (development only)
# RATELIMIT_BACKEND = 'memory'
```

See [Configuration](configuration.md) for more advanced options including Database and Multi-backend setups.
