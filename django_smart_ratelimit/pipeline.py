"""
Shared rate-limit evaluation pipeline.

This module centralizes the logic that is invariant between the sync decorator,
the async decorator, middleware, and the DRF throttle adapter. Historically that
logic was duplicated in several places, which meant bug fixes and new features
had to be applied three or four times in parallel. v3.0.0 consolidates it here.

The pipeline exposes two key helpers:

    * ``resolve_effective_rate(...)``  — turn a (key, rate, adaptive, cost)
      config into a concrete (limit, period, cost, generated_key) tuple,
      raising :class:`KeyGenerationError` instead of failing silently.

    * ``apply_policy_lists(...)`` — evaluate CIDR allow/deny policy for the
      request and return one of ``{"deny", "allow", "continue"}``.

    * ``handle_shadow_decision(...)`` — given an "actually would-have-been
      blocked" decision, either escalate it to a real block or downgrade it
      to an allow-with-log (shadow mode).

These helpers are intentionally side-effect light so they can be reused from
both sync and async call-sites without sync_to_async gymnastics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple, Union

from django.http import HttpRequest

from .adaptive import AdaptiveRateLimiter
from .backends.utils import parse_rate
from .exceptions import KeyGenerationError
from .key_functions import generate_key
from .observability import record_check

logger = logging.getLogger(__name__)


# Sentinel used by apply_policy_lists to indicate the request should bypass
# rate limiting entirely (matched an allow-list entry).
POLICY_ALLOW = "allow"
# Matched a deny-list entry — caller should return a block response immediately.
POLICY_DENY = "deny"
# No list hit — caller should proceed with normal rate-limit evaluation.
POLICY_CONTINUE = "continue"


@dataclass
class ResolvedLimit:
    """Fully resolved rate-limit parameters for a single request."""

    key: str
    limit: int
    period: int
    cost: int = 1
    # The original rate string after resolution (post-callable, pre-parse). Kept
    # around so observability spans and error messages can reference it.
    rate_string: str = ""


def _resolve_rate(
    rate: Union[str, Callable[..., str]],
    request: HttpRequest,
) -> str:
    """Resolve a rate that may be a string or a callable.

    The callable may accept either ``(self_or_none, request)`` (django-ratelimit
    compatibility) or ``(request,)`` or zero arguments. We try them in that
    order so existing user code keeps working.
    """
    if isinstance(rate, str):
        return rate

    if not callable(rate):
        raise TypeError(f"Rate must be str or callable, got {type(rate)!r}")

    try:
        return rate(None, request)
    except TypeError:
        pass
    try:
        return rate(request)
    except TypeError:
        pass
    return rate()


def _resolve_cost(
    cost: Union[int, Callable[[HttpRequest], int], None],
    request: HttpRequest,
) -> int:
    """Resolve a cost that may be an int or callable returning an int.

    Costs < 1 are clamped to 1 — a free request is indistinguishable from no
    request at all, and allowing cost=0 would let callers bypass limits.
    """
    if cost is None:
        return 1
    if callable(cost):
        try:
            value = cost(request)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("cost callable raised %s; falling back to 1", exc)
            return 1
    else:
        value = cost
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        logger.warning("cost resolved to non-int %r; falling back to 1", value)
        return 1
    return max(1, ivalue)


def _apply_adaptive(
    adaptive: Optional[Union[str, AdaptiveRateLimiter]], base_limit: int
) -> int:
    """Apply adaptive rate-limiting if configured. Mirrors decorator helper."""
    if adaptive is None:
        return base_limit

    limiter: Optional[AdaptiveRateLimiter]
    if isinstance(adaptive, str):
        from .adaptive import get_adaptive_limiter

        limiter = get_adaptive_limiter(adaptive)
        if limiter is None:
            logger.warning(
                "Adaptive rate limiter '%s' not found; using base limit %d",
                adaptive,
                base_limit,
            )
            return base_limit
    elif isinstance(adaptive, AdaptiveRateLimiter):
        limiter = adaptive
    else:
        logger.warning(
            "Invalid adaptive parameter type %s; using base limit %d",
            type(adaptive),
            base_limit,
        )
        return base_limit

    try:
        return limiter.get_effective_limit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Adaptive limiter failed: %s; using base limit %d", exc, base_limit
        )
        return base_limit


def resolve_effective_rate(
    *,
    key: Union[str, Callable[..., str]],
    rate: Union[str, Callable[..., str]],
    request: HttpRequest,
    args: Tuple[Any, ...] = (),
    kwargs: Optional[Dict[str, Any]] = None,
    adaptive: Optional[Union[str, AdaptiveRateLimiter]] = None,
    cost: Union[int, Callable[[HttpRequest], int], None] = 1,
    validate_key: bool = True,
) -> ResolvedLimit:
    """Resolve a rate-limit config to concrete (key, limit, period, cost).

    Raises
    ------
    KeyGenerationError
        If ``validate_key`` is True and the key function returns an empty
        string or ``None``. Prior to v3 these were silently treated as valid
        keys which caused the entire limiter to collapse onto the literal key
        ``""`` under load — a footgun that is now upgraded to a loud failure.

    ValueError / ImproperlyConfigured
        If the rate string cannot be parsed.
    """
    kwargs = kwargs or {}

    generated_key = generate_key(key, request, *args, **kwargs)
    if validate_key and not generated_key:
        raise KeyGenerationError(
            f"Key function {key!r} returned empty key for request {request!r}. "
            "An empty key would cause all requests to share the same bucket. "
            "Return a stable non-empty string, or raise an explicit exception "
            "to indicate rate limiting should be skipped."
        )

    rate_str = _resolve_rate(rate, request)
    limit, period = parse_rate(rate_str)
    limit = _apply_adaptive(adaptive, limit)
    cost_int = _resolve_cost(cost, request)

    return ResolvedLimit(
        key=generated_key,
        limit=limit,
        period=period,
        cost=cost_int,
        rate_string=rate_str,
    )


def apply_policy_lists(
    request: HttpRequest,
    *,
    allow_list: Any = None,
    deny_list: Any = None,
) -> str:
    """Evaluate allow/deny lists for a request.

    Inputs may be :class:`~django_smart_ratelimit.policy.IPList` instances,
    iterables of CIDR strings, file paths, or URLs — whatever
    :func:`~django_smart_ratelimit.policy.parse_ip_list` accepts.

    Returns one of ``POLICY_DENY``, ``POLICY_ALLOW`` or ``POLICY_CONTINUE``.
    Deny always takes precedence over allow (fail-closed for explicit blocks).
    """
    if allow_list is None and deny_list is None:
        return POLICY_CONTINUE

    # Lazy import so users who don't use policy lists don't pay the cost.
    from .policy import check_lists, parse_ip_list

    try:
        al = parse_ip_list(allow_list) if allow_list is not None else None
    except Exception as exc:
        logger.warning("Failed to parse allow_list (%s); skipping allow check", exc)
        al = None
    try:
        dl = parse_ip_list(deny_list) if deny_list is not None else None
    except Exception as exc:
        logger.warning("Failed to parse deny_list (%s); skipping deny check", exc)
        dl = None

    should_skip, reason = check_lists(request, allow_list=al, deny_list=dl)

    if reason == "deny_list":
        return POLICY_DENY
    if should_skip and reason == "allow_list":
        return POLICY_ALLOW
    return POLICY_CONTINUE


@dataclass
class ShadowDecision:
    """Outcome after optionally applying shadow mode."""

    # The decision the caller should honor (True = allow, False = block).
    allow: bool
    # Whether shadow mode converted a real block into an allow.
    shadowed: bool = False
    # Arbitrary metadata propagated for observability.
    extra: Dict[str, Any] = field(default_factory=dict)


def handle_shadow_decision(
    *,
    allowed: bool,
    shadow: bool,
    request: HttpRequest,
    key: str,
    limit: int,
    remaining: int,
    algorithm: str,
    backend: str,
    cost: int = 1,
) -> ShadowDecision:
    """Apply shadow mode to an underlying decision.

    When ``shadow=True`` and ``allowed=False``, the decision is flipped to
    allow and a structured log line + OTel event is emitted so operators can
    see what *would* have been blocked in production. This is the standard
    rollout strategy for a new limit: run it in shadow for a day, look at the
    logs, then turn enforcement on.
    """
    # Always record observability regardless of shadow state.
    try:
        record_check(
            key=key,
            limit=limit,
            remaining=remaining,
            algorithm=algorithm,
            backend=backend,
            allowed=allowed,
            shadow=shadow,
            cost=cost,
        )
    except Exception:  # pragma: no cover  # nosec B110
        # Observability must never break rate-limit enforcement.
        pass

    if allowed:
        return ShadowDecision(allow=True, shadowed=False)

    if shadow:
        logger.info(
            "SHADOW_RATE_LIMIT_BLOCK",
            extra={
                "event": "ratelimit.shadow.block",
                "key": key,
                "limit": limit,
                "remaining": remaining,
                "algorithm": algorithm,
                "backend": backend,
                "cost": cost,
                "path": getattr(request, "path", None),
                "method": getattr(request, "method", None),
            },
        )
        return ShadowDecision(allow=True, shadowed=True, extra={"shadow": True})

    return ShadowDecision(allow=False, shadowed=False)


__all__ = [
    "POLICY_ALLOW",
    "POLICY_DENY",
    "POLICY_CONTINUE",
    "ResolvedLimit",
    "ShadowDecision",
    "apply_policy_lists",
    "handle_shadow_decision",
    "resolve_effective_rate",
]
