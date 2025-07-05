"""
Test settings for django-smart-ratelimit.

This file contains Django settings for running tests.
"""

import os

DEBUG = True

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
    "django_smart_ratelimit",
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
