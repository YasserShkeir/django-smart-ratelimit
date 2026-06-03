"""User-tier resolution and tier-aware rate adjustment (roadmap Phase 3).

Resolves the effective rate limit for a request by precedence:

1. an active per-user :class:`UserRateLimitOverride` (highest),
2. the user's :class:`UserTier` -- from an explicit assignment, else from the
   user's Django groups -- applied to the base rate (explicit per-scope limit, or
   the ``rate_multiplier``),
3. otherwise the base rate, unchanged.
"""

from typing import Any, Optional

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
