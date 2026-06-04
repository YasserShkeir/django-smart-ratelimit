"""Quota management: cumulative, long-horizon usage limits (roadmap #76).

Unlike rate limiting (requests per short window), a *quota* tracks total usage
over a long period that resets on a calendar boundary, e.g. "10,000 requests per
month per API key". Usage is stored in the :class:`Quota` model (so it survives
restarts and is visible in the admin), making the database the natural backing
store.

Usage::

    from django_smart_ratelimit import quota

    @quota(key="user", limit=10000, period="month")
    def api_view(request):
        ...

Periods: ``"day"``, ``"week"`` (Monday-aligned), ``"month"``, ``"year"`` (all
calendar-aligned), or ``"<N>d"`` / an int for a rolling N-day window from the
period start. Requires ``django_smart_ratelimit`` in ``INSTALLED_APPS`` and the
migrations applied.
"""

import functools
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Tuple, Union

from asgiref.sync import iscoroutinefunction, sync_to_async

from django.utils import timezone

from .decorator import _create_rate_limit_response, _get_request_from_args
from .key_functions import generate_key

logger = logging.getLogger(__name__)

_OVER_QUOTA_MESSAGE = "Quota exceeded. Try again after it resets."


def _add_month(dt: datetime) -> datetime:
    """Return ``dt`` advanced by one calendar month (day pinned to 1)."""
    year, month = dt.year + (dt.month // 12), (dt.month % 12) + 1
    return dt.replace(year=year, month=month, day=1)


def _period_bounds(period: Union[str, int], now: datetime) -> Tuple[datetime, datetime]:
    """Return ``(period_start, reset_at)`` for the period containing ``now``.

    Named periods are calendar-aligned; an int or ``"<N>d"`` is a rolling N-day
    window anchored at the start of today.
    """
    local = timezone.localtime(now)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "day":
        return midnight, midnight + timedelta(days=1)
    if period == "week":
        start = midnight - timedelta(days=local.weekday())
        return start, start + timedelta(days=7)
    if period == "month":
        start = midnight.replace(day=1)
        return start, _add_month(start)
    if period == "year":
        start = midnight.replace(month=1, day=1)
        return start, start.replace(year=start.year + 1)

    # Rolling N-day window: "30d", "7d", or an int number of days.
    if isinstance(period, str):
        days = int(period[:-1] if period.endswith("d") else period)
    else:
        days = int(period)
    if days <= 0:
        raise ValueError(f"Invalid quota period: {period!r}")
    return midnight, midnight + timedelta(days=days)


def consume_quota(
    key: str,
    limit: int,
    period: Union[str, int],
    scope: str = "",
    cost: int = 1,
) -> Tuple[bool, Dict[str, Any]]:
    """Atomically consume ``cost`` from the quota for ``key`` (roadmap #76).

    Resets the counter when the period has rolled over, then allows and charges
    the request if it fits under ``limit``. Returns ``(allowed, info)`` where
    ``info`` has ``used``, ``limit``, ``remaining``, ``reset_at``, ``period``.
    The usage is not charged when the request is denied.
    """
    from django.db import transaction

    from .models import Quota

    now = timezone.now()
    with transaction.atomic():
        row, created = Quota.objects.select_for_update().get_or_create(
            key=key,
            scope=scope,
            defaults={
                "used": 0,
                "limit": limit,
                "period": str(period),
                "period_start": _period_bounds(period, now)[0],
                "reset_at": _period_bounds(period, now)[1],
            },
        )
        # Roll over if the window elapsed, or if the period/limit was reconfigured.
        if not created and (now >= row.reset_at or row.period != str(period)):
            row.period_start, row.reset_at = _period_bounds(period, now)
            row.used = 0
            row.period = str(period)
        row.limit = limit

        allowed = row.used + cost <= limit
        if allowed:
            row.used += cost
        row.save()
        info = {
            "used": row.used,
            "limit": limit,
            "remaining": max(0, limit - row.used),
            "reset_at": row.reset_at,
            "period": str(period),
        }
    return allowed, info


def get_quota_usage(key: str, scope: str = "") -> Optional[Dict[str, Any]]:
    """Return current usage for ``key`` (introspection), or ``None`` if unused."""
    from .models import Quota

    try:
        row = Quota.objects.get(key=key, scope=scope)
    except Quota.DoesNotExist:
        return None
    now = timezone.now()
    used = 0 if now >= row.reset_at else row.used
    return {
        "used": used,
        "limit": row.limit,
        "remaining": max(0, row.limit - used),
        "reset_at": row.reset_at,
        "period": row.period,
    }


def reset_quota(key: str, scope: str = "") -> None:
    """Delete the stored quota usage for ``key`` (next request starts fresh)."""
    from .models import Quota

    Quota.objects.filter(key=key, scope=scope).delete()


def quota(
    key: Union[str, Callable],
    limit: int,
    period: Union[str, int] = "month",
    *,
    scope: str = "",
    cost: Union[int, Callable[..., int]] = 1,
    block: bool = True,
    response_callback: Optional[Callable] = None,
) -> Callable:
    """Enforce a cumulative usage quota for ``key`` (roadmap #76).

    Args:
        key: Quota key or callable (resolved like ``@rate_limit``'s key).
        limit: Total units allowed per period.
        period: ``"day"`` / ``"week"`` / ``"month"`` / ``"year"`` / ``"<N>d"``.
        scope: Namespaces independent quotas for the same key.
        cost: Units charged per request (int or ``(request) -> int``).
        block: When True, an over-quota request gets a 429; else it passes.
        response_callback: Optional ``(request) -> HttpResponse`` for the 429.
    """

    def _resolve(request: Any, args: Any, kwargs: Any) -> Tuple[str, int]:
        generated = generate_key(key, request, *args, **kwargs)
        req_cost = cost(request) if callable(cost) else cost
        return f"quota:{generated}", int(req_cost)

    def decorator(func: Callable) -> Callable:
        if iscoroutinefunction(func):

            @functools.wraps(func)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                request = _get_request_from_args(*args, **kwargs)
                if request is None:
                    return await func(*args, **kwargs)
                quota_key, req_cost = _resolve(request, args, kwargs)
                allowed, _ = await sync_to_async(consume_quota)(
                    quota_key, limit, period, scope, req_cost
                )
                if not allowed and block:
                    return _create_rate_limit_response(
                        _OVER_QUOTA_MESSAGE,
                        request=request,
                        response_callback=response_callback,
                    )
                return await func(*args, **kwargs)

            return awrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _get_request_from_args(*args, **kwargs)
            if request is None:
                return func(*args, **kwargs)
            quota_key, req_cost = _resolve(request, args, kwargs)
            allowed, _ = consume_quota(quota_key, limit, period, scope, req_cost)
            if not allowed and block:
                return _create_rate_limit_response(
                    _OVER_QUOTA_MESSAGE,
                    request=request,
                    response_callback=response_callback,
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator
