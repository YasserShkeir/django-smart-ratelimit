"""Aggregation/reporting helpers over recorded RateLimitEvent rows (Phase 4)."""

import csv
import io
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)


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


def get_offender_detail(key: str, days: int = 7, recent: int = 50) -> Dict[str, Any]:
    """Detailed activity for a single offender ``key`` (roadmap 4.3.2).

    Returns totals (allowed/blocked/block-rate), first/last seen, the per-path
    blocked breakdown, and the most recent events for the window.
    """
    from .models import RateLimitEvent

    qs = RateLimitEvent.objects.filter(timestamp__gte=_cutoff(days), key=key)
    total = qs.count()
    blocked = qs.filter(allowed=False).count()
    timestamps = qs.order_by("timestamp").values_list("timestamp", flat=True)
    by_path = list(
        qs.filter(allowed=False)
        .values("path")
        .annotate(blocked_count=Count("id"))
        .order_by("-blocked_count")[:20]
    )
    recent_events = list(
        qs.order_by("-timestamp").values(
            "timestamp", "path", "method", "allowed", "count", "limit", "rule_name"
        )[:recent]
    )
    return {
        "key": key,
        "days": days,
        "total": total,
        "allowed": total - blocked,
        "blocked": blocked,
        "block_rate": (blocked / total) if total else 0.0,
        "first_seen": timestamps[0] if total else None,
        "last_seen": (
            qs.order_by("-timestamp").values_list("timestamp", flat=True)[0]
            if total
            else None
        ),
        "by_path": by_path,
        "recent_events": recent_events,
    }


def find_alertable_offenders(
    threshold: int, days: int = 1, limit: int = 100
) -> List[Dict[str, Any]]:
    """Offenders whose blocked-request count over the window is >= ``threshold``."""
    return [
        row
        for row in get_top_offenders(days=days, limit=limit)
        if row["blocked_count"] >= threshold
    ]


def send_offender_alerts(
    threshold: Optional[int] = None,
    days: int = 1,
    *,
    email_to: Optional[List[str]] = None,
    webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Find offenders over ``threshold`` and dispatch email / webhook alerts.

    Configuration falls back to settings when arguments are omitted:
    ``RATELIMIT_ALERT_THRESHOLD`` (required to do anything; default disabled),
    ``RATELIMIT_ALERT_EMAILS`` (list), and ``RATELIMIT_ALERT_WEBHOOK`` (URL).
    Dispatch is best-effort: a failing channel is logged and reported, never
    raised. Returns a summary dict (offenders found and per-channel status).
    """
    from django.conf import settings as django_settings

    if threshold is None:
        threshold = getattr(django_settings, "RATELIMIT_ALERT_THRESHOLD", None)
    if not threshold:
        return {"enabled": False, "offenders": [], "channels": {}}

    offenders = find_alertable_offenders(int(threshold), days=days)
    result: Dict[str, Any] = {
        "enabled": True,
        "threshold": int(threshold),
        "days": days,
        "offenders": offenders,
        "channels": {},
    }
    if not offenders:
        return result

    if email_to is None:
        email_to = getattr(django_settings, "RATELIMIT_ALERT_EMAILS", None)
    if webhook_url is None:
        webhook_url = getattr(django_settings, "RATELIMIT_ALERT_WEBHOOK", None)

    lines = [f"{o['key']}: {o['blocked_count']} blocked" for o in offenders]
    body = (
        f"{len(offenders)} rate-limit offender(s) exceeded {threshold} blocked "
        f"requests in the last {days} day(s):\n\n" + "\n".join(lines)
    )

    if email_to:
        try:
            from django.core.mail import send_mail

            send_mail(
                subject=f"[django-smart-ratelimit] {len(offenders)} offender(s) alert",
                message=body,
                from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=list(email_to),
                fail_silently=False,
            )
            result["channels"]["email"] = {"sent": True, "to": list(email_to)}
        except Exception as exc:  # pragma: no cover - depends on mail backend
            logger.warning("offender email alert failed: %s", exc)
            result["channels"]["email"] = {"sent": False, "error": str(exc)}

    if webhook_url:
        payload = {
            "threshold": int(threshold),
            "days": days,
            "offenders": offenders,
        }
        try:
            import json
            import urllib.request

            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload, default=str).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)  # nosec B310
            result["channels"]["webhook"] = {"sent": True, "url": webhook_url}
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("offender webhook alert failed: %s", exc)
            result["channels"]["webhook"] = {"sent": False, "error": str(exc)}

    return result
