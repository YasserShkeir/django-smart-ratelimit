"""
Test settings for django-smart-ratelimit.

This file contains Django settings for running tests.
"""

import os

DEBUG = True

# Default to in-memory SQLite, but honor a DATABASE_URL (postgres://...) so CI
# can run the suite against a real PostgreSQL service -- needed to exercise the
# concurrency/atomicity behavior that SQLite (which serializes writers) cannot.
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
if _DATABASE_URL.startswith(("postgres://", "postgresql://")):
    from urllib.parse import urlparse as _urlparse

    _parsed = _urlparse(_DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _parsed.path.lstrip("/") or "test",
            "USER": _parsed.username or "",
            "PASSWORD": _parsed.password or "",
            "HOST": _parsed.hostname or "localhost",
            "PORT": str(_parsed.port or 5432),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "django_smart_ratelimit",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

SECRET_KEY = "test-secret-key-for-testing-only"

ROOT_URLCONF = "tests.urls"

USE_TZ = True

# Rate limiting settings
RATELIMIT_BACKEND = "redis"
RATELIMIT_REDIS = {
    "host": os.environ.get("REDIS_HOST", "localhost"),
    "port": int(os.environ.get("REDIS_PORT", "6379")),
    "db": int(os.environ.get("REDIS_DB", "0")),
}

# Memcached connection for the memcached backend tests (defaults to localhost;
# CI sets MEMCACHED_HOST/PORT when a service container is available).
RATELIMIT_MEMCACHED = {
    "HOST": os.environ.get("MEMCACHED_HOST", "localhost"),
    "PORT": int(os.environ.get("MEMCACHED_PORT", "11211")),
}

RATELIMIT_ALGORITHM = "sliding_window"
RATELIMIT_KEY_PREFIX = "test:ratelimit:"

# Test middleware configuration
RATELIMIT_MIDDLEWARE = {
    "DEFAULT_RATE": "100/m",
    "BACKEND": "redis",
    "BLOCK": True,
    "SKIP_PATHS": ["/admin/", "/health/"],
    "RATE_LIMITS": {
        "/api/": "1000/h",
        "/auth/": "5/m",
    },
}
