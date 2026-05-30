# Decorator API

The primary way to use Django Smart Ratelimit is via the `@rate_limit` decorator (also available as `@ratelimit` for compatibility with other libraries).

## @rate_limit / @ratelimit

Applies rate limiting to a Django view (sync or async). Both names are identical - use whichever you prefer.

```python
from django_smart_ratelimit import rate_limit  # or: ratelimit

@rate_limit(key="ip", rate="5/m", block=True)
def my_view(request):
    ...
```

Keys and algorithms can be passed as plain strings or via the type-safe enums
(`RateLimitKey`, `Algorithm`). The enums are `StrEnum` members, so they are
interchangeable with the equivalent strings everywhere:

```python
from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.enums import Algorithm, RateLimitKey

@rate_limit(key=RateLimitKey.IP, rate="5/m", algorithm=Algorithm.SLIDING_WINDOW)
def my_view(request):
    ...
```

### Parameters

| Parameter            | Type                       | Default            | Description                                                                                                                                                                          |
| :------------------- | :------------------------- | :----------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **key**              | `str` \| `Callable`        | Required           | The key to limit by. Accepts shortcut strings (`"ip"`, `"user"`, `"user_or_ip"`), prefixed strings (`"header:X-Api-Key"`, `"param:tenant"`), a `RateLimitKey` enum, or a callable that returns a key. |
| **rate**             | `str`                      | `None`             | The limit string (e.g., `"5/m"`, `"100/h"`). When `None`, the `RATELIMIT_DEFAULT_LIMIT` setting is used (`"100/m"` by default).                                                       |
| **block**            | `bool`                     | `True`             | If `True`, returns a `429 Too Many Requests` response when the limit is exceeded. If `False`, the request proceeds and `request.rate_limit_exceeded` is set to `True`.                |
| **backend**          | `str`                      | `None`             | Override the default backend for this view (e.g., `"redis"`, `"memory"`, `"database"`). When `None`, the configured default backend is used.                                         |
| **skip_if**          | `Callable`                 | `None`             | A function `(request) -> bool`. If it returns `True`, rate limiting is skipped for that request.                                                                                      |
| **algorithm**        | `str` \| `Algorithm`       | `None`             | The algorithm to use: `"sliding_window"` (effective default), `"fixed_window"`, `"token_bucket"`, `"leaky_bucket"`. See the note below on async and backend limitations.             |
| **algorithm_config** | `dict`                     | `None`             | Algorithm-specific config (e.g., `{"bucket_size": 20}` for token bucket).                                                                                                            |
| **settings**         | `object`                   | `None`             | Optional settings object for dependency injection / testing. Normally left unset so global Django settings are used.                                                                 |
| **adaptive**         | `str` \| `AdaptiveRateLimiter` | `None`         | Name of a registered `AdaptiveRateLimiter` or an instance. When set, the limit is adjusted dynamically by system load and the `rate` limit value is replaced by the adaptive limiter. |
| **response_callback** | `Callable`                | `None`             | Callable `(request) -> HttpResponse` that builds the 429 response. Overrides the global `RATELIMIT_RESPONSE_HANDLER` setting.                                                        |
| **cost**             | `int` \| `Callable`        | `1`                | New in v3.0.0. Cost of each request. Accepts an int or a callable `(request) -> int`. Used for weighted limits where expensive operations consume more of the budget.                |
| **shadow**           | `bool`                     | `False`            | New in v3.0.0. When `True`, decisions are evaluated and logged (including OTel events) but never enforced. Use it to observe what would be blocked before turning on enforcement.    |
| **allow_list**       | `IPList` \| iterable \| `str` | `None`          | New in v3.0.0. CIDR allow-list of IPs that bypass rate limiting entirely. Accepts an `IPList`, an iterable of CIDRs, a file path, or a URL.                                          |
| **deny_list**        | `IPList` \| iterable \| `str` | `None`          | New in v3.0.0. CIDR deny-list of IPs blocked before rate limiting runs. Takes precedence over `allow_list`.                                                                          |

### Key shortcuts and the `RateLimitKey` enum

`RateLimitKey.IP`, `RateLimitKey.USER`, and `RateLimitKey.USER_OR_IP` are
complete keys and can be passed directly. `RateLimitKey.HEADER` and
`RateLimitKey.PARAM` are prefixes that need a sub-value naming the header or
query parameter to key on:

```python
from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.enums import RateLimitKey

@rate_limit(key=RateLimitKey.USER_OR_IP, rate="10/m")
def view_a(request):
    ...

@rate_limit(key=f"{RateLimitKey.HEADER}:X-Api-Key", rate="100/h")
def view_b(request):
    ...

@rate_limit(key=f"{RateLimitKey.PARAM}:tenant", rate="100/h")
def view_c(request):
    ...
```

The string equivalents (`"ip"`, `"user"`, `"user_or_ip"`, `"header:X-Api-Key"`,
`"param:tenant"`) work identically.

### Algorithms and the `Algorithm` enum

| String             | Enum                       |
| :----------------- | :------------------------- |
| `"sliding_window"` | `Algorithm.SLIDING_WINDOW` |
| `"fixed_window"`   | `Algorithm.FIXED_WINDOW`   |
| `"token_bucket"`   | `Algorithm.TOKEN_BUCKET`   |
| `"leaky_bucket"`   | `Algorithm.LEAKY_BUCKET`   |

When `algorithm` is left as `None`, standard window limiting is applied
(sliding window in practice).

Limitations to be aware of:

- `token_bucket` and `leaky_bucket` are honored on **sync** views and on
  **async** `async def` views decorated with `@rate_limit` (as of v3.1.0 the
  async path runs the algorithm check off the event loop). The standalone
  `@aratelimit` decorator still applies window counting only.
- `leaky_bucket` via the decorator requires a backend with native leaky-bucket
  support. The **database** backend provides this. On other backends the
  decorator logs a warning and falls back to standard window limiting, so do not
  assume identical leaky-bucket behavior on every backend.

### Examples

```python
from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.adaptive import create_adaptive_limiter
from django_smart_ratelimit.enums import Algorithm, RateLimitKey

# Token bucket with burst capability (sync view only)
@rate_limit(
    key="api_key:{_request.api_key}",
    rate="10/m",
    algorithm=Algorithm.TOKEN_BUCKET,
    algorithm_config={"bucket_size": 20},
)
def api_view(request):
    ...

# Adaptive rate limiting based on system load
create_adaptive_limiter("api", base_limit=100, min_limit=10, max_limit=200)

@rate_limit(key=RateLimitKey.IP, rate="100/m", adaptive="api")
def adaptive_view(request):
    ...

# Shadow mode for safe rollout (v3.0.0): logged but not enforced
@rate_limit(key=RateLimitKey.IP, rate="10/m", shadow=True)
def shadow_view(request):
    ...

# Cost-based weighted limiting (v3.0.0)
@rate_limit(
    key=RateLimitKey.USER,
    rate="100/m",
    cost=lambda req: 5 if req.path.startswith("/export") else 1,
)
def weighted_view(request):
    ...
```

## @aratelimit

`@aratelimit` is a dedicated async decorator with its own, smaller signature:

```python
def aratelimit(key="ip", rate=None, method=None, block=True, backend=None, **kwargs)
```

It is importable from the package root:

```python
from django_smart_ratelimit import aratelimit

@aratelimit(key="ip", rate="5/m")
async def my_async_view(request):
    ...
```

`@rate_limit` also detects `async def` views automatically and applies its async
path, so most async views can use `@rate_limit` directly — including
`token_bucket` / `leaky_bucket`, which are honored on the async path as of
v3.1.0. The standalone `@aratelimit` decorator applies window counting only.

## @ratelimit_batch

Applies multiple rate limits to a single view. Imported from
`django_smart_ratelimit.decorator`:

```python
from django_smart_ratelimit.decorator import ratelimit_batch

@ratelimit_batch([
    {"rate": "100/h", "key": "ip", "group": "global"},
    {"rate": "10/m", "key": "user", "group": "specific"},
], block=True)
def view(request):
    ...
```

Each entry must contain `rate` and `key`; `group` is optional and namespaces the
limit. An optional `method` (string or list) restricts an entry to specific HTTP
methods. With `block=True`, the request is rejected if any limit is exceeded.
