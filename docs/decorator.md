# Decorator API

The primary way to use Django Smart Ratelimit is via the `@rate_limit` decorator (also available as `@ratelimit` for compatibility with other libraries).

## @rate_limit / @ratelimit

Applies rate limiting to a Django view (sync or async). Both names are identical - use whichever you prefer.

```python
from django_smart_ratelimit import rate_limit  # or: ratelimit

@rate_limit(key='ip', rate='5/m', block=True)
def my_view(request):
    ...
```
```

### Parameters

| Parameter            | Type                | Default          | Description                                                                                                                  |
| :------------------- | :------------------ | :--------------- | :--------------------------------------------------------------------------------------------------------------------------- |
| **key**              | `str` \| `Callable` | Required         | The key to limit by. Can be shortcut strings (`'ip'`, `'user'`) or a callable that accepts `request` (and optional `group`). |
| **rate**             | `str`               | Required         | The limit string (e.g., `'5/m'`, `'100/h'`).                                                                                 |
| **block**            | `bool`              | `False`          | If `True`, raises `429 Too Many Requests` when limit is exceeded. If `False`, just sets `request.limited = True`.            |
| **algorithm**        | `str`               | `'token_bucket'` | The algorithm to use: `'token_bucket'`, `'fixed_window'`, `'sliding_window'`.                                                |
| **backend**          | `str`               | `None`           | Override the default backend for this specific view (e.g., `'redis'`, `'memory'`).                                           |
| **skip_if**          | `Callable`          | `None`           | A function `(request) -> bool`. If it returns `True`, rate limiting is skipped.                                              |
| **algorithm_config** | `dict`              | `{}`             | Specific config for the algorithm (e.g., `{'bucket_size': 100}` for token buckets).                                          |

## @aratelimit

**Deprecated/Alias**: In v1.0+, `@rate_limit` automatically detects async views. You can use `@aratelimit` as an explicit alias if preferred.

## @ratelimit_batch

Applies multiple rate limits to a single view.

```python
from django_smart_ratelimit.decorator import ratelimit_batch

@ratelimit_batch([
    {"rate": "100/h", "key": "ip", "group": "global"},
    {"rate": "10/m", "key": "user", "group": "specific"},
], block=True)
def view(request): ...
```
