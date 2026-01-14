# Utilities

Helper functions available in `django_smart_ratelimit.utils`.

## is_ratelimited

Programmatically check if a request would be rate limited without using a decorator.

```python
from django_smart_ratelimit import is_ratelimited

def my_custom_logic(request):
    limited = is_ratelimited(
        request,
        key='ip',
        rate='5/m',
        increment=True  # Whether to count this check
    )
    if limited:
        return HttpResponse("Stop!")
```

## generate_key

Helper to see what the key string looks like for a request.

```python
from django_smart_ratelimit.utils import generate_key

key = generate_key(request, key='ip')
# Returns: "ip:127.0.0.1"
```
