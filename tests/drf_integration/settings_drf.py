"""
Test configuration for DRF integration tests.

This file provides Django settings optimized for testing DRF integration
with Django Smart Ratelimit.
"""

from tests.settings import *  # noqa: F403, F401

# Add DRF to installed apps if available
try:
    import rest_framework  # noqa: F401

    INSTALLED_APPS = INSTALLED_APPS + [  # noqa: F405
        "rest_framework",
    ]

    # DRF Configuration
    REST_FRAMEWORK = {
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework.authentication.SessionAuthentication",
            "rest_framework.authentication.TokenAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.AllowAny",
        ],
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.AnonRateThrottle",
            "rest_framework.throttling.UserRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {"anon": "100/hour", "user": "1000/hour"},
        "DEFAULT_RENDERER_CLASSES": [
            "rest_framework.renderers.JSONRenderer",
        ],
        "DEFAULT_PARSER_CLASSES": [
            "rest_framework.parsers.JSONParser",
        ],
        "TEST_REQUEST_DEFAULT_FORMAT": "json",
    }

    # Add DRF token authentication app
    INSTALLED_APPS = INSTALLED_APPS + [
        "rest_framework.authtoken",
    ]

    DRF_AVAILABLE = True

except ImportError:
    DRF_AVAILABLE = False

# Use memory backend for testing to avoid Redis dependency
RATELIMIT_BACKEND = "django_smart_ratelimit.backends.memory.MemoryBackend"
RATELIMIT_BACKEND_OPTIONS = {
    "MAX_ENTRIES": 1000,
    "CLEANUP_INTERVAL": 300,
}

# Enable debug mode for testing
DEBUG = True

# Test-specific cache configuration
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
    }
}

# Test database configuration
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}


# Disable migrations for faster testing
class DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = DisableMigrations()

# Test-specific logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django_smart_ratelimit": {
            "handlers": ["console"],
            "level": "DEBUG",
        },
    },
}

# Test-specific settings
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",  # Faster for testing
]

# Disable CSRF for testing
CSRF_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = False

# Test-specific security settings
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = False
SECURE_BROWSER_XSS_FILTER = False
