"""Aggregation/reporting helpers over recorded RateLimitEvent rows (Phase 4)."""

import csv
import io
from datetime import timedelta
from typing import Any, Dict, List

from django.db.models import Count, Q
from django.utils import timezone


def _cutoff(days: int) -> Any:
    return timezone.now() - timedelta(days=days)


def get_traffic_summary(days: int = 1) -> Dict[str, Any]:
    """Total / allowed / blocked counts and block rate over the last ``days``."""
    from .models import RateLimitEvent

    qs = RateLimitEvent.objects.filter(timestamp__gte=_cutoff(days))
    total = qs.count()
    blocked = qs.filter(allowed=False).count()
    return {
        "days": days,
        "total": total,
        "allowed": total - blocked,
        "blocked": blocked,
        "block_rate": (blocked / total) if total else 0.0,
    }


def get_top_offenders(days: int = 7, limit: int = 100) -> List[Dict[str, Any]]:
    """Keys with the most BLOCKED requests over the window, descending."""
    from .models import RateLimitEvent

    return list(
        RateLimitEvent.objects.filter(timestamp__gte=_cutoff(days), allowed=False)
        .values("key")
        .annotate(blocked_count=Count("id"))
        .order_by("-blocked_count")[:limit]
    )


def get_rule_hit_counts(days: int = 7, limit: int = 50) -> List[Dict[str, Any]]:
    """Per-rule total hits and blocked counts over the window."""
    from .models import RateLimitEvent

    return list(
        RateLimitEvent.objects.filter(timestamp__gte=_cutoff(days))
        .exclude(rule_name="")
        .values("rule_name")
        .annotate(
            hits=Count("id"),
            blocked=Count("id", filter=Q(allowed=False)),
        )
        .order_by("-hits")[:limit]
    )


def offenders_csv(days: int = 7, limit: int = 1000) -> str:
    """Render :func:`get_top_offenders` as a CSV string."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["key", "blocked_count"])
    for row in get_top_offenders(days=days, limit=limit):
        writer.writerow([row["key"], row["blocked_count"]])
    return buffer.getvalue()
