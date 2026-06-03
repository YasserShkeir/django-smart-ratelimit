"""Django-group-based tier resolution and a group key function (Phase 3)."""

from typing import Any, Optional


def get_tier_from_groups(user: Any) -> Optional[Any]:
    """Return the highest-priority :class:`UserTier` mapped to a user's groups.

    Looks up :class:`GroupRateLimit` rows for the user's groups and returns the
    tier of the highest-priority one, or ``None`` if no group maps to a tier.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    from .models import GroupRateLimit

    configs = (
        GroupRateLimit.objects.filter(group__in=user.groups.all(), tier__isnull=False)
        .select_related("tier")
        .order_by("-tier__priority")
    )
    first = configs.first()
    return first.tier if first is not None else None


def group_key(request: Any, *args: Any, **kwargs: Any) -> str:
    """Key function: bucket a request by the user's (sorted) group names."""
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        names = sorted(user.groups.values_list("name", flat=True))
        if names:
            return f"group:{','.join(names)}"
    return "group:anonymous"
