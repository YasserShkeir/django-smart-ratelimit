"""Shadow-mode rollout of a new rate limit.

With shadow=True the limit is checked and logged but NOT enforced: no request is
denied. Watch the logs for SHADOW_RATE_LIMIT_BLOCK to see what the limit would
reject, then remove shadow=True to turn enforcement on.
"""

from django.http import HttpRequest, JsonResponse

from django_smart_ratelimit import rate_limit


@rate_limit(key="ip", rate="10/m", shadow=True)
def search_view(request: HttpRequest) -> JsonResponse:
    # While shadow=True, callers over 10/min are NOT blocked; each one that
    # would have been blocked logs SHADOW_RATE_LIMIT_BLOCK at INFO level on the
    # "django_smart_ratelimit.pipeline" logger (fields in the record's `extra`).
    # Once the log volume looks acceptable, drop shadow=True to enforce.
    return JsonResponse({"results": []})
