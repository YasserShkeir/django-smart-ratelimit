"""DRF views throttled by django-smart-ratelimit.

Requires djangorestframework: pip install "django-smart-ratelimit[drf]"
"""

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from django_smart_ratelimit.integrations.drf import (
    AnonRateLimitThrottle,
    ScopedRateLimitThrottle,
    UserRateLimitThrottle,
)


class HelloView(APIView):
    """Throttled by the user/anon classes.

    With DEFAULT_THROTTLE_CLASSES set (see settings.py) you can omit the
    explicit `throttle_classes`; it is shown here to be self-contained.
    """

    throttle_classes = [UserRateLimitThrottle, AnonRateLimitThrottle]

    def get(self, request: Request) -> Response:
        return Response({"message": "ok"})


class ReportsView(APIView):
    """Per-view limit via `throttle_scope`, no subclassing needed.

    The rate is looked up from DEFAULT_THROTTLE_RATES["reports"].
    """

    throttle_classes = [ScopedRateLimitThrottle]
    throttle_scope = "reports"

    def get(self, request: Request) -> Response:
        return Response({"reports": []})
