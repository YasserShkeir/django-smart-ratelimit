# Utilities

Helper functions available in `django_smart_ratelimit.utils` and re-exported from the
top-level `django_smart_ratelimit` package.

## is_ratelimited

Programmatically check if a request would be rate limited without using a decorator.

Signature:

```python
is_ratelimited(request, group=None, key="ip", rate="5/m", increment=True, backend=None) -> bool
```

Returns `True` when the request exceeds the limit, `False` otherwise.

```python
from django_smart_ratelimit import is_ratelimited

def my_custom_logic(request):
    limited = is_ratelimited(
        request,
        key="ip",
        rate="5/m",
        increment=True,  # Whether to count this check toward the limit
    )
    if limited:
        return HttpResponse("Stop!")
```

The `key` argument accepts the same values as the decorator, including the `RateLimitKey`
enum:

```python
from django_smart_ratelimit import is_ratelimited
from django_smart_ratelimit.enums import RateLimitKey

limited = is_ratelimited(request, key=RateLimitKey.USER_OR_IP, rate="5/m")
```

## generate_key

Helper to see what the key string looks like for a request. The `key` argument comes first,
followed by the `request`.

Signature:

```python
generate_key(key, request, *args, **kwargs) -> str
```

```python
from django_smart_ratelimit import generate_key
from django_smart_ratelimit.enums import RateLimitKey

key = generate_key("ip", request)
# Returns: "ip:127.0.0.1"

# RateLimitKey enum values are accepted interchangeably with their string values:
key = generate_key(RateLimitKey.USER, request)
# Returns: "user:42" for an authenticated user, or "ip:..." as a fallback
```
