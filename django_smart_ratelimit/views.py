"""
Views for Django Smart Ratelimit.
"""

from django.http import HttpRequest, JsonResponse

# HttpResponseBase lives in django.http.response in all supported versions;
# django.http only re-exports it on newer Django (not 3.2).
from django.http.response import HttpResponseBase

from .config import get_settings
from .performance import get_metrics


def ratelimit_metrics_view(request: HttpRequest) -> JsonResponse:
    """
    Endpoint for rate limit metrics.
    Only available if RATELIMIT_COLLECT_METRICS is True.
    """
    if not get_settings().collect_metrics:
        return JsonResponse({"error": "Metrics collection disabled"}, status=404)

    stats = get_metrics().get_stats()
    return JsonResponse(stats)


from typing import Any  # noqa: E402

from django.http import HttpResponse  # noqa: E402
from django.views.generic import TemplateView  # noqa: E402


def _staff_required(request: HttpRequest) -> bool:
    """True if the request is from an authenticated staff user."""
    user = getattr(request, "user", None)
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_staff", False)
    )


def _days_param(request: HttpRequest, default: int = 7) -> int:
    """Parse a clamped ``?days=`` query parameter (1..365)."""
    try:
        days = int(request.GET.get("days", default))
    except (TypeError, ValueError):
        days = default
    return max(1, min(days, 365))


class RateLimitDashboardView(TemplateView):
    """Staff-only dashboard summarizing rate-limit traffic and offenders.

    Requires ``RATELIMIT_LOG_EVENTS = True`` to have data. Wire it up with::

        path("ratelimit/", include("django_smart_ratelimit.urls"))
    """

    template_name = "django_smart_ratelimit/dashboard.html"

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """Restrict the dashboard to authenticated staff users."""
        if not _staff_required(request):
            return HttpResponse("Forbidden", status=403)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict:
        """Populate dashboard metrics for the requested window."""
        from .analytics import (
            get_rule_hit_counts,
            get_top_offenders,
            get_traffic_summary,
        )

        days = _days_param(self.request)
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "days": days,
                "today": get_traffic_summary(days=1),
                "window": get_traffic_summary(days=days),
                "top_offenders": get_top_offenders(days=days, limit=20),
                "rule_hits": get_rule_hit_counts(days=days, limit=20),
            }
        )
        return context


def offenders_csv_view(request: HttpRequest) -> HttpResponse:
    """Staff-only CSV export of the top offenders for the requested window."""
    if not _staff_required(request):
        return HttpResponse("Forbidden", status=403)

    from .analytics import offenders_csv

    days = _days_param(request)
    payload = offenders_csv(days=days, limit=1000)
    response = HttpResponse(payload, content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="ratelimit_offenders.csv"'
    return response


def offender_detail_view(request: HttpRequest) -> HttpResponse:
    """Staff-only JSON drill-down for one offender ``?key=`` (roadmap 4.3.2).

    Returns totals, first/last seen, the per-path blocked breakdown, and recent
    events for the key over the requested ``?days=`` window.
    """
    if not _staff_required(request):
        return HttpResponse("Forbidden", status=403)

    key = request.GET.get("key", "")
    if not key:
        return JsonResponse({"error": "missing ?key= parameter"}, status=400)

    from .analytics import get_offender_detail

    days = _days_param(request)
    return JsonResponse(get_offender_detail(key, days=days))
