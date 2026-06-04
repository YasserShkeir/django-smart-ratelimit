"""Concurrency (in-flight) limiting (roadmap #76, Tier 1).

Caps the number of requests being processed *at the same time* for a key, rather
than the number of requests per time window. For example, "at most 5 simultaneous
exports per user". Backed by an atomic semaphore (a Redis sorted set, or the
in-memory backend); a slot whose request crashed before releasing is reclaimed
after ``ttl`` seconds, so the limiter self-heals.

Usage::

    from django_smart_ratelimit import concurrency_limit

    @concurrency_limit(key="user", max_concurrent=5)
    def export_view(request):
        ...

The key resolves exactly like ``@rate_limit``'s ``key`` (``"ip"``, ``"user"``,
a template such as ``"user:{user.id}"``, or a callable). Requires a backend with
semaphore support (Redis or memory); other backends raise at call time.
"""

import functools
import logging
import uuid
from typing import Any, Callable, Optional, Union

from asgiref.sync import iscoroutinefunction, sync_to_async

from django.core.exceptions import ImproperlyConfigured

from .backends import get_backend
from .decorator import _create_rate_limit_response, _get_request_from_args
from .key_functions import generate_key

logger = logging.getLogger(__name__)

_OVER_CAPACITY_MESSAGE = "Too many concurrent requests. Please retry shortly."


def _resolve_concurrency_key(
    key: Union[str, Callable], request: Any, args: Any, kwargs: Any
) -> str:
    """Resolve the concurrency key the same way the rate-limit decorator does."""
    generated = generate_key(key, request, *args, **kwargs)
    return f"concurrency:{generated}"


def _require_semaphore_backend(backend_instance: Any) -> None:
    if not hasattr(backend_instance, "concurrency_acquire"):
        raise ImproperlyConfigured(
            "concurrency_limit requires a backend with semaphore support "
            "(the redis or memory backend); "
            f"{type(backend_instance).__name__} does not provide it."
        )


def concurrency_limit(
    key: Union[str, Callable],
    max_concurrent: int,
    *,
    ttl: int = 60,
    backend: Optional[str] = None,
    block: bool = True,
    response_callback: Optional[Callable] = None,
) -> Callable:
    """Limit the number of simultaneous in-flight requests for ``key``.

    Args:
        key: Concurrency key or callable (resolved like ``@rate_limit``'s key).
        max_concurrent: Maximum requests allowed in flight at once.
        ttl: Seconds after which a held slot is assumed leaked and reclaimed
            (set it above your longest expected request duration).
        backend: Optional backend name override.
        block: When True (default), an over-capacity request gets a 429; when
            False, it is allowed through without holding a slot.
        response_callback: Optional ``(request) -> HttpResponse`` for the 429.
    """

    def decorator(func: Callable) -> Callable:
        if iscoroutinefunction(func):

            @functools.wraps(func)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                request = _get_request_from_args(*args, **kwargs)
                if request is None:
                    return await func(*args, **kwargs)

                limit_key = _resolve_concurrency_key(key, request, args, kwargs)
                backend_instance: Any = get_backend(backend)
                _require_semaphore_backend(backend_instance)
                member = uuid.uuid4().hex

                acquired = await sync_to_async(backend_instance.concurrency_acquire)(
                    limit_key, max_concurrent, ttl, member
                )
                if not acquired and block:
                    return _create_rate_limit_response(
                        _OVER_CAPACITY_MESSAGE,
                        request=request,
                        response_callback=response_callback,
                    )
                try:
                    return await func(*args, **kwargs)
                finally:
                    if acquired:
                        await sync_to_async(backend_instance.concurrency_release)(
                            limit_key, member
                        )

            return awrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _get_request_from_args(*args, **kwargs)
            if request is None:
                return func(*args, **kwargs)

            limit_key = _resolve_concurrency_key(key, request, args, kwargs)
            backend_instance: Any = get_backend(backend)
            _require_semaphore_backend(backend_instance)
            member = uuid.uuid4().hex

            acquired = backend_instance.concurrency_acquire(
                limit_key, max_concurrent, ttl, member
            )
            if not acquired and block:
                return _create_rate_limit_response(
                    _OVER_CAPACITY_MESSAGE,
                    request=request,
                    response_callback=response_callback,
                )
            try:
                return func(*args, **kwargs)
            finally:
                if acquired:
                    backend_instance.concurrency_release(limit_key, member)

        return wrapper

    return decorator
