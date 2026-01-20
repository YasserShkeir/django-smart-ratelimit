import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-test-key-for-integration-testing"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_smart_ratelimit",
    "scenarios",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Global Rate Limit Middleware (conditionally enabled in tests via settings if needed, but added here for completeness)
]

if os.environ.get("RATELIMIT_DISABLE_MIDDLEWARE") != "true":
    MIDDLEWARE.append("django_smart_ratelimit.middleware.RateLimitMiddleware")

ROOT_URLCONF = "app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "app.wsgi.application"


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

# Support DATABASE_URL for PostgreSQL/MySQL testing
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Parse DATABASE_URL for PostgreSQL or MySQL
    # Format: postgres://user:password@host:port/dbname
    # Format: mysql://user:password@host:port/dbname
    import re

    match = re.match(
        r"(?P<engine>postgres|mysql)://(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)/(?P<name>.+)",
        DATABASE_URL,
    )
    if match:
        db_config = match.groupdict()
        engine = (
            "django.db.backends.postgresql"
            if db_config["engine"] == "postgres"
            else "django.db.backends.mysql"
        )
        DATABASES = {
            "default": {
                "ENGINE": engine,
                "NAME": db_config["name"],
                "USER": db_config["user"],
                "PASSWORD": db_config["password"],
                "HOST": db_config["host"],
                "PORT": db_config["port"],
            }
        }
    else:
        # Fallback to SQLite if URL parsing fails
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }
else:
    # Default to SQLite
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "static/"

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django Smart Ratelimit Configuration ---

RATELIMIT_ENABLE = True

# Dynamic Backend Selection via Environment Variable
# Options:
# - django_smart_ratelimit.backends.memory.MemoryBackend (Default)
# - django_smart_ratelimit.backends.redis_backend.RedisBackend
# - django_smart_ratelimit.backends.redis_backend.AsyncRedisBackend
# - django_smart_ratelimit.backends.mongodb.MongoDBBackend
# - django_smart_ratelimit.backends.multi.MultiBackend
RATELIMIT_BACKEND = os.environ.get(
    "TEST_BACKEND", "django_smart_ratelimit.backends.memory.MemoryBackend"
)

# Fail-Open Configuration
RATELIMIT_FAIL_OPEN = os.environ.get("TEST_FAIL_OPEN", "False") == "True"

# Redis Configuration (if used)
RATELIMIT_REDIS = {
    "host": os.environ.get("REDIS_HOST", "localhost"),
    "port": int(os.environ.get("REDIS_PORT", 6379)),
    "db": 0,
}

# MongoDB Configuration (if used)
RATELIMIT_MONGODB = {
    "host": os.environ.get("MONGODB_HOST", "localhost"),
    "port": int(os.environ.get("MONGODB_PORT", 27017)),
    "database": os.environ.get("MONGODB_DATABASE", "ratelimit"),
}

# Multi-Backend Configuration
if os.environ.get("RATELIMIT_DISABLE_MULTI_BACKEND") == "true":
    RATELIMIT_MULTI_BACKENDS = []
else:
    RATELIMIT_MULTI_BACKENDS = [
        {
            "name": "primary",
            "backend": "django_smart_ratelimit.backends.redis_backend.RedisBackend",
            "options": RATELIMIT_REDIS,
        },
        {
            "name": "secondary",
            "backend": "django_smart_ratelimit.backends.memory.MemoryBackend",
            "options": {},
        },
    ]

# Logging Configuration for Observability
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django_smart_ratelimit": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# Increase global middleware limit to prevent test interference
RATELIMIT_MIDDLEWARE = {
    "DEFAULT_RATE": "2000/m",
    "BLOCK": True,
    "SKIP_PATHS": ["/admin/"],
    "RATE_LIMITS": {
        "/middleware/async/": "5/m",
    },
}

# Circuit Breaker Configuration
RATELIMIT_CIRCUIT_BREAKER = {
    "failure_threshold": int(
        os.environ.get("RATELIMIT_CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5)
    ),
    "recovery_timeout": int(
        os.environ.get("RATELIMIT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT", 30)
    ),
}

# Window Alignment Configuration (for testing clock-aligned vs first-request aligned)
# Default: True (clock-aligned) - can be overridden via environment variable
RATELIMIT_ALIGN_WINDOW_TO_CLOCK = (
    os.environ.get("RATELIMIT_ALIGN_WINDOW_TO_CLOCK", "True") == "True"
)
