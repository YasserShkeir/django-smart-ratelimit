from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from django_smart_ratelimit import ratelimit
from django_smart_ratelimit.backends import get_backend
from django_smart_ratelimit.decorator import aratelimit, ratelimit_batch
from django_smart_ratelimit.utils import get_ip_key


def mk_key(scope):
    return lambda request, *args, **kwargs: f"{scope}:{get_ip_key(request)}"


# --- A. Algorithms & Basic Rates ---


@ratelimit_batch(
    [
        {"key": "ip", "rate": "5/m", "group": "batch_ip"},
        {"key": "user", "rate": "10/h", "group": "batch_user"},
    ]
)
def batch_demo(request):
    return JsonResponse({"status": "ok", "batch": True})


@ratelimit(key=mk_key("algo_fixed"), rate="5/m", algorithm="fixed_window")
def algo_fixed(request):
    return JsonResponse({"status": "ok", "algo": "fixed_window"})


@ratelimit(key=mk_key("algo_sliding"), rate="5/m", algorithm="sliding_window")
def algo_sliding(request):
    return JsonResponse({"status": "ok", "algo": "sliding_window"})


@ratelimit(key=mk_key("algo_token"), rate="5/m", algorithm="token_bucket")
def algo_token(request):
    return JsonResponse({"status": "ok", "algo": "token_bucket"})


@ratelimit(key=mk_key("algo_seconds"), rate="1/s")
def algo_seconds(request):
    return JsonResponse({"status": "ok", "rate": "1/s"})


@ratelimit(key=mk_key("algo_hours"), rate="10/h")
def algo_hours(request):
    return JsonResponse({"status": "ok", "rate": "10/h"})


@aratelimit(key=mk_key("algo_async"), rate="5/m", algorithm="sliding_window")
async def algo_async(request):
    return JsonResponse({"status": "ok", "algo": "async_sliding_window"})


# Async view for Middleware testing (No decorator)
async def middleware_async(request):
    return JsonResponse({"status": "ok", "source": "middleware_async"})


# --- B. Keys & Identification ---


@ratelimit(key="ip", rate="5/m")
def key_ip(request):
    return JsonResponse({"status": "ok", "key": "ip"})


@ratelimit(key="user", rate="5/m")
def key_user(request):
    return JsonResponse({"status": "ok", "key": "user", "user": str(request.user)})


@ratelimit(key="user_or_ip", rate="5/m")
def key_user_or_ip(request):
    return JsonResponse({"status": "ok", "key": "user_or_ip"})


@ratelimit(key="header:x-api-key", rate="5/m")
def key_header(request):
    return JsonResponse({"status": "ok", "key": "header"})


@ratelimit(key="get:tenant_id", rate="5/m")
def key_param(request):
    return JsonResponse({"status": "ok", "key": "param"})


def custom_key_func(request, *args, **kwargs):
    return "custom_key_123"


@ratelimit(key=custom_key_func, rate="5/m")
def key_custom(request):
    return JsonResponse({"status": "ok", "key": "custom"})


# --- C. Advanced Decorator Options ---


@ratelimit(key=mk_key("opt_block_false"), rate="5/m", block=False)
def opt_block_false(request):
    # Check if request was limited but allowed
    was_limited = getattr(request, "rate_limit_exceeded", False)
    return JsonResponse({"status": "ok", "limited": was_limited})


@ratelimit(key=mk_key("shared_group"), rate="5/m")
def opt_group_a(request):
    return JsonResponse({"status": "ok", "group": "a"})


@ratelimit(key=mk_key("shared_group"), rate="5/m")
def opt_group_b(request):
    return JsonResponse({"status": "ok", "group": "b"})


@csrf_exempt
@ratelimit(key=mk_key("opt_methods"), rate="5/m", skip_if=lambda r: r.method != "POST")
def opt_methods(request):
    return JsonResponse({"status": "ok", "method": request.method})


def is_admin(request):
    return request.user.is_staff


@ratelimit(key=mk_key("opt_skip"), rate="5/m", skip_if=is_admin)
def opt_skip(request):
    return JsonResponse({"status": "ok", "skipped": is_admin(request)})


# --- D. Framework Integration ---


class DRFAPIView(APIView):
    @method_decorator(ratelimit(key=mk_key("drf_apiview"), rate="5/m"))
    def get(self, request):
        return Response({"status": "ok", "type": "APIView"})


class DRFViewSet(ViewSet):
    @method_decorator(ratelimit(key=mk_key("drf_viewset"), rate="5/m"))
    def list(self, request):
        return Response({"status": "ok", "type": "ViewSet", "action": "list"})

    @action(detail=False, methods=["get"])
    @method_decorator(ratelimit(key=mk_key("drf_viewset_custom"), rate="2/m"))
    def custom_action(self, request):
        return Response({"status": "ok", "type": "ViewSet", "action": "custom"})


def middleware_global(request):
    # This view relies on global middleware configuration
    return JsonResponse({"status": "ok", "type": "middleware"})


# --- E. Infrastructure & Resilience ---
# These views are identical in logic but are used to test different backend configs
# The actual backend switching happens via settings/env vars, but we provide
# distinct endpoints to keep test logs clean.


@ratelimit(key=mk_key("infra_redis"), rate="100/m")
def infra_redis(request):
    return JsonResponse({"status": "ok", "infra": "redis"})


@ratelimit(key=mk_key("infra_mongodb"), rate="100/m")
def infra_mongodb(request):
    return JsonResponse({"status": "ok", "infra": "mongodb"})


@ratelimit(key=mk_key("infra_multi"), rate="100/m")
def infra_multi(request):
    return JsonResponse({"status": "ok", "infra": "multi"})


@ratelimit(key=mk_key("infra_fail_open"), rate="100/m")
def infra_fail_open(request):
    return JsonResponse({"status": "ok", "infra": "fail_open"})


@ratelimit(key=mk_key("infra_fail_closed"), rate="100/m")
def infra_fail_closed(request):
    return JsonResponse({"status": "ok", "infra": "fail_closed"})


def infra_cb_status(request):
    backend = get_backend()
    # Ensure checking the right backend if multi is active?
    # In these tests, we usually have one main backend active per container.
    status = backend.get_backend_health_status()
    # Add explicit state for easier parsing
    if "circuit_breaker" in status:
        status["cb_state"] = status["circuit_breaker"].get("state")
    return JsonResponse(status)


# --- F. Real World Scenarios ---


def get_tier_rate(grupo, request):
    # Simulate tiered access based on header
    tier = request.headers.get("X-User-Tier", "basic")
    if tier == "premium":
        return "20/m"
    return "5/m"


@ratelimit(key=mk_key("tiering"), rate=get_tier_rate)
def real_world_tiering(request):
    tier = request.headers.get("X-User-Tier", "basic")
    return JsonResponse({"status": "ok", "tier": tier})


@csrf_exempt
@ratelimit(key=mk_key("login_brute"), rate="5/m", block=True)
def real_world_login(request):
    # Simulate login check - always fail to force retry
    return JsonResponse({"status": "failed", "msg": "Bad credentials"}, status=401)


@ratelimit(key=mk_key("expensive_search"), rate="5/m")
def real_world_search(request):
    # Slower endpoint (simulated)
    return JsonResponse({"status": "ok", "results": [1, 2, 3]})


@ratelimit(key=mk_key("cheap_dashboard"), rate="100/m")
def real_world_dashboard(request):
    # Fast endpoint
    return JsonResponse({"status": "ok", "dashboard": "data"})


# --- G. Window Alignment Testing ---


@ratelimit(key=mk_key("window_align_test"), rate="3/m", algorithm="fixed_window")
def window_alignment_test(request):
    """
    Test endpoint for window alignment feature.

    This view is used to verify that:
    1. Clock-aligned mode: Windows reset at clock boundaries (e.g., :00, :01)
    2. First-request aligned mode: Windows reset relative to first request

    The response includes timing information for verification.
    """
    import time

    from django_smart_ratelimit.config import get_settings

    settings = get_settings()
    current_time = time.time()

    # Calculate what the reset time should be based on alignment mode
    if settings.align_window_to_clock:
        # Clock-aligned: bucket start is floored to 60 seconds
        bucket_start = int(current_time // 60) * 60
        expected_reset = bucket_start + 60
        mode = "clock_aligned"
    else:
        # First-request aligned: reset is current_time + period
        expected_reset = int(current_time + 60)
        mode = "first_request_aligned"

    return JsonResponse(
        {
            "status": "ok",
            "alignment_mode": mode,
            "align_window_to_clock": settings.align_window_to_clock,
            "current_time": int(current_time),
            "expected_reset_approx": expected_reset,
            "algorithm": "fixed_window",
            "rate": "3/m",
        }
    )
