"""
Enum definitions for django-smart-ratelimit.

Provides type-safe enums for algorithms and key types, with IDE
autocomplete support. Compatible with Python 3.9+ by using a
backport pattern for StrEnum.
"""

import sys
from enum import Enum

# StrEnum backport for Python < 3.11
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:

    class StrEnum(str, Enum):
        """String enum backport for Python < 3.11."""

        def __str__(self) -> str:
            return self.value

        @staticmethod
        def _generate_next_value_(
            name: str, start: int, count: int, last_values: list
        ) -> str:
            return name.lower()


class Algorithm(StrEnum):
    """Rate limiting algorithm choices.

    Usage::

        from django_smart_ratelimit.enums import Algorithm

        @rate_limit(key="ip", rate="10/m", algorithm=Algorithm.SLIDING_WINDOW)
        def my_view(request):
            ...

        # In settings.py:
        RATELIMIT_ALGORITHM = Algorithm.TOKEN_BUCKET
    """

    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    TOKEN_BUCKET = "token_bucket"  # nosec B105
    LEAKY_BUCKET = "leaky_bucket"


class RateLimitKey(StrEnum):
    """Built-in rate limit key types.

    ``IP``, ``USER`` and ``USER_OR_IP`` are complete keys and can be used
    directly::

        from django_smart_ratelimit.enums import RateLimitKey

        @rate_limit(key=RateLimitKey.USER_OR_IP, rate="10/m")
        def my_view(request):
            ...

    ``HEADER`` and ``PARAM`` are *prefixes*: they require a sub-value naming the
    header or query parameter to key on. Compose them with that value::

        @rate_limit(key=f"{RateLimitKey.HEADER}:X-Api-Key", rate="100/h")
        @rate_limit(key=f"{RateLimitKey.PARAM}:tenant", rate="100/h")
    """

    IP = "ip"
    USER = "user"
    USER_OR_IP = "user_or_ip"
    HEADER = "header"
    PARAM = "param"
