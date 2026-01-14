"""
Views for Django Smart Ratelimit.
"""

from django.http import HttpRequest, JsonResponse

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
