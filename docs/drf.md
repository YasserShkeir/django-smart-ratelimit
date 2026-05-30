# Django REST Framework

`django-smart-ratelimit` ships throttle classes that plug directly into DRF's
`throttle_classes` system. They use the same backends and algorithms as the
`@rate_limit` decorator, so you get sliding-window / token-bucket limiting,
weighted costs, and pluggable backends inside standard DRF views.

## Installation

The throttle classes live in `django_smart_ratelimit.integrations.drf`. DRF is
an optional dependency:

```bash
pip install "django-smart-ratelimit[drf]"
```

The module imports fine without DRF installed, but instantiating any throttle
raises a helpful `ImportError` telling you to install `djangorestframework`.

## The Four Throttle Classes

All four extend `SmartRateLimitThrottle` and implement DRF's `BaseThrottle`
interface (`allow_request`, `wait`).

| Class                      | Scope                       | Default key                              |
| -------------------------- | --------------------------- | ---------------------------------------- |
| `UserRateLimitThrottle`    | `"user"`                    | `user:<id>` if authenticated, else IP    |
| `AnonRateLimitThrottle`    | `"anon"`                    | client IP                                |
| `ScopedRateLimitThrottle`  | the view's `throttle_scope` | `user:<id>` if authenticated, else IP    |
| `SmartRateLimitThrottle`   | none (base class)           | `user:<id>` if authenticated, else IP    |

`SmartRateLimitThrottle` is the base you subclass for custom behavior. The other
three are ready-to-use specializations.

### UserRateLimitThrottle and AnonRateLimitThrottle

The classic DRF pairing: a generous limit for logged-in users and a tighter one
for anonymous traffic. Configure the rates through DRF's
`DEFAULT_THROTTLE_RATES`, keyed by each class's `scope`.

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "django_smart_ratelimit.integrations.drf.UserRateLimitThrottle",
        "django_smart_ratelimit.integrations.drf.AnonRateLimitThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "1000/hour",
        "anon": "100/hour",
    },
}
```

```python
# views.py
from rest_framework.response import Response
from rest_framework.views import APIView


class HelloView(APIView):
    # Inherits DEFAULT_THROTTLE_CLASSES, or set per view:
    # throttle_classes = [UserRateLimitThrottle, AnonRateLimitThrottle]

    def get(self, request):
        return Response({"message": "ok"})
```

`UserRateLimitThrottle` keys on `user:<id>` when the request is authenticated
and falls back to the client IP otherwise, so a single throttle class covers
both states. `AnonRateLimitThrottle` always keys on the IP address.

### ScopedRateLimitThrottle

Set a per-view limit without subclassing. Add `throttle_scope` to the view and
the throttle looks the rate up from `DEFAULT_THROTTLE_RATES`.

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_RATES": {
        "uploads": "20/minute",
        "search": "500/hour",
    },
}
```

```python
# views.py
from rest_framework.response import Response
from rest_framework.views import APIView

from django_smart_ratelimit.integrations.drf import ScopedRateLimitThrottle


class UploadView(APIView):
    throttle_classes = [ScopedRateLimitThrottle]
    throttle_scope = "uploads"

    def post(self, request):
        return Response({"status": "received"})
```

If the view has no `throttle_scope` attribute, the throttle logs a warning and
allows the request (it never silently blocks a misconfigured view).

## Rate Resolution

Each throttle resolves its rate in this order:

1. The class-level `rate` attribute, if set (e.g. `rate = "50/hour"`).
2. `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"][scope]`.

`rate` may also be a callable `(throttle, request) -> str` for dynamic limits:

```python
from django_smart_ratelimit.integrations.drf import SmartRateLimitThrottle


def staff_aware_rate(throttle, request):
    if request.user.is_authenticated and request.user.is_staff:
        return "5000/hour"
    return "500/hour"


class TieredThrottle(SmartRateLimitThrottle):
    scope = "tiered"
    rate = staff_aware_rate
```

If no rate can be resolved, the throttle logs a warning and **allows** the
request rather than crashing the view.

## Choosing an Algorithm

Set the `algorithm` attribute to `"sliding_window"` (default), `"fixed_window"`,
or `"token_bucket"`:

```python
class BurstyThrottle(SmartRateLimitThrottle):
    scope = "bursty"
    rate = "60/minute"
    algorithm = "token_bucket"
```

## Weighted Requests with get_cost

By default each request costs one token. Override `get_cost(request, view)` (or
set a callable `cost` attribute) to make expensive operations consume more of
the budget.

```python
from django_smart_ratelimit.integrations.drf import SmartRateLimitThrottle


class ExportThrottle(SmartRateLimitThrottle):
    scope = "export"
    rate = "100/hour"

    def get_cost(self, request, view):
        # A full export burns 10 tokens; everything else costs 1.
        return 10 if request.query_params.get("full") else 1
```

The throttle prefers backends whose `incr` accepts a cost argument and consumes
all the tokens in a single call. Backends that do not support a cost argument
fall back to repeated single-token increments, so weighted limiting still works
end to end.

## Custom Keys

Override `get_cache_key(request, view)` to control how requests are bucketed.
Return `None` to skip throttling for a request.

```python
from django_smart_ratelimit.integrations.drf import SmartRateLimitThrottle


class ApiKeyThrottle(SmartRateLimitThrottle):
    scope = "api_key"
    rate = "10000/day"

    def get_cache_key(self, request, view):
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return None  # No key header -> not throttled by this class
        return f"api_key:{api_key}"
```

You can also assign a plain `key_func` callable `(request, view) -> str | None`
on the class instead of subclassing:

```python
class HostThrottle(SmartRateLimitThrottle):
    scope = "host"
    rate = "1000/hour"
    key_func = lambda request, view: f"host:{request.get_host()}"
```

When both are present, `key_func` takes precedence over `get_cache_key`.

## Retry-After / wait()

When a request is throttled, DRF calls `wait()` to populate the `Retry-After`
header. The throttle stores the backend's reset time on every check and returns
the seconds remaining, so clients learn exactly when to retry.

## Fail-Open Behavior

If the backend raises while checking a limit, the throttle reads the backend's
`fail_open` attribute (default `True`) and allows the request, logging a
warning. Set the backend to fail closed if you would rather deny on backend
errors.

## See Also

- [Decorator](decorator.md) — the `@rate_limit` decorator for plain Django views.
- [Algorithms](algorithms.md) — sliding window, fixed window, token bucket.
- [Backends](backends.md) — Redis, MongoDB, database, memory, multi.
- [Observability](observability.md) — OpenTelemetry and Prometheus metrics.
