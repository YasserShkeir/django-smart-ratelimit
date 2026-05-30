"""Logging settings snippet for shadow-mode rollout.

Copy the LOGGING block into your project's settings.py so the shadow log line
(emitted at INFO on the "django_smart_ratelimit.pipeline" logger) is visible.
"""

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        # Surface SHADOW_RATE_LIMIT_BLOCK records. The structured fields live in
        # each record's `extra`; route this logger to a JSON handler in
        # production to capture them (event, key, limit, remaining, path, ...).
        "django_smart_ratelimit.pipeline": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
