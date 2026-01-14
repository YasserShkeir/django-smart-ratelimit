# Installation

## Requirements

- Python 3.9+
- Django 3.2+
- Redis (Recommended for production)
    - For **Async** support: `redis-py` >= 4.2.0 is required.

## Basic Installation

Install using pip:

```bash
pip install django-smart-ratelimit
```

To install with Redis support (recommended):

```bash
pip install "django-smart-ratelimit[redis]"
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

```python
# Use Redis (Recommended)
RATELIMIT_BACKEND = 'django_smart_ratelimit.backends.RedisBackend'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
}

# OR Use Memory (Development only)
# RATELIMIT_BACKEND = 'django_smart_ratelimit.backends.MemoryBackend'
```

See [Configuration](configuration.md) for more advanced options including Database and Multi-backend setups.
