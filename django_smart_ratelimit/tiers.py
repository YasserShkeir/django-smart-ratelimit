"""User-tier resolution and tier-aware rate adjustment (roadmap Phase 3).

Resolves the effective rate limit for a request by precedence:

1. an active per-user :class:`UserRateLimitOverride` (highest),
2. the user's :class:`UserTier` -- from an explicit assignment, else from the
   user's Django groups -- applied to the base rate (explicit per-scope limit, or
   the ``rate_multiplier``),
3. otherwise the base rate, unchanged.
"""

from datetime import timedelta
from typing import Any, Callable, Dict, Optional, Union

from django.utils import timezone


def get_user_tier(user: Any) -> Optional[Any]:
    """Return the effective :class:`UserTier` for a user, or ``None``.

    Honors an explicit (non-expired) assignment first, then falls back to the
    highest-priority tier mapped to one of the user's groups.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    from .models import UserTierAssignment

    try:
        assignment = user.ratelimit_tier
    except (UserTierAssignment.DoesNotExist, AttributeError):
        assignment = None

    if assignment is not None and not assignment.is_expired():
        return assignment.tier

    from .groups import get_tier_from_groups

    return get_tier_from_groups(user)


def apply_tier_to_rate(base_rate: str, tier: Optional[Any], scope: str = "") -> str:
    """Apply a tier to ``base_rate`` for the given scope.

    A matching ``explicit_limits[scope]`` wins outright; otherwise the base
    limit is scaled by ``rate_multiplier`` (rounded, min 1).
    """
    if tier is None:
        return base_rate

    explicit = getattr(tier, "explicit_limits", None) or {}
    if scope and scope in explicit:
        return str(explicit[scope])

    multiplier = float(getattr(tier, "rate_multiplier", 1.0) or 1.0)
    if multiplier == 1.0:
        return base_rate

    from .backends.utils import parse_rate

    try:
        limit, period = parse_rate(base_rate)
    except Exception:
        return base_rate
    new_limit = max(1, int(round(limit * multiplier)))
    return f"{new_limit}/{period}s"


def get_user_override(user: Any, scope: str = "") -> Optional[str]:
    """Return the rate from an active per-user override, or ``None``.

    A scope-specific override (``rule_name == scope``) wins over a blank
    (applies-to-all) override.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    from .models import UserRateLimitOverride

    now = timezone.now()
    overrides = list(
        UserRateLimitOverride.objects.filter(
            user=user, starts_at__lte=now, expires_at__gt=now
        )
    )
    if not overrides:
        return None

    if scope:
        for override in overrides:
            if override.rule_name == scope:
                return override.rate
    for override in overrides:
        if not override.rule_name:
            return override.rate
    return None


def resolve_effective_user_rate(request: Any, base_rate: str, scope: str = "") -> str:
    """Resolve the rate for ``request`` honoring overrides, then tiers, then base.

    ``scope`` lets a per-scope override / explicit tier limit be selected (e.g.
    the dynamic rule name or a logical endpoint name).
    """
    user = getattr(request, "user", None)

    override = get_user_override(user, scope)
    if override is not None:
        return override

    tier = get_user_tier(user)
    return apply_tier_to_rate(base_rate, tier, scope)


def tier_key(request: Any, *args: Any, **kwargs: Any) -> str:
    """Key function: bucket a request by the user's tier (``tier:<name>``).

    Returns ``tier:anonymous`` for unauthenticated requests and ``tier:default``
    for authenticated users without a resolved tier. Use as ``key=tier_key`` to
    give every user in the same tier a shared budget.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return "tier:anonymous"
    tier = get_user_tier(user)
    if tier is None:
        return "tier:default"
    return f"tier:{getattr(tier, 'name', 'default')}"


def create_user_override(
    user: Any,
    rate: str,
    *,
    scope: str = "",
    duration_seconds: Optional[int] = None,
    expires_at: Optional[Any] = None,
    reason: str = "",
    created_by: Any = None,
) -> Any:
    """Create and return a per-user :class:`UserRateLimitOverride` (roadmap 3.3.4).

    A programmatic alternative to the Django admin for granting a temporary
    custom rate. ``scope`` maps to the override's ``rule_name`` (blank applies to
    all). Provide exactly one of ``duration_seconds`` (relative to now) or
    ``expires_at`` (absolute); ``duration_seconds`` defaults to one hour if
    neither is given. ``rate`` is validated before the row is written.
    """
    from django.core.exceptions import ValidationError

    from .backends.utils import parse_rate

    try:
        parse_rate(rate)
    except Exception as exc:
        raise ValidationError(f"Invalid rate: {rate!r}") from exc

    from .models import UserRateLimitOverride

    now = timezone.now()
    if expires_at is None:
        expires_at = now + timedelta(seconds=duration_seconds or 3600)

    return UserRateLimitOverride.objects.create(
        user=user,
        rule_name=scope,
        rate=rate,
        reason=reason,
        created_by=created_by,
        starts_at=now,
        expires_at=expires_at,
    )


def tiered(
    rates: Dict[Any, str],
    by: Union[str, Callable[[Any], Any]],
    default: Optional[str] = None,
) -> Callable[..., str]:
    """Build a per-request ``rate`` that varies by plan/tier (roadmap #76).

    A lightweight, model-free alternative to ``RATELIMIT_USE_USER_TIERS``: pick
    the rate string by an attribute of the request. Pass the result as
    ``@rate_limit(rate=tiered(...))``::

        @rate_limit(key="user", rate=tiered(
            {"free": "100/h", "pro": "10000/h"}, by="user.plan", default="100/h"))
        def api(request): ...

    Args:
        rates: Mapping of tier value -> rate string. A ``"*"`` entry is the
            wildcard for any unlisted tier.
        by: How to read the tier from the request -- a callable ``(request) ->
            tier`` or a dotted attribute path (e.g. ``"user.plan"``).
        default: Rate used when the tier is missing/unlisted and no ``"*"`` entry
            exists. Provide this or a ``"*"`` entry.

    Returns:
        A callable ``(request, ...) -> rate_string`` for ``@rate_limit``.
    """

    def _resolve_tier(request: Any) -> Any:
        if callable(by):
            return by(request)
        obj: Any = request
        for part in by.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        return obj

    def _rate_for(request: Any, *args: Any, **kwargs: Any) -> str:
        tier = _resolve_tier(request)
        if tier is not None and tier in rates:
            return rates[tier]
        if "*" in rates:
            return rates["*"]
        if default is not None:
            return default
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            f"tiered(): no rate for tier {tier!r} and no '*'/default provided."
        )

    return _rate_for
