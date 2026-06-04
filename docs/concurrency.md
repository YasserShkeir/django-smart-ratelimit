# Concurrency Limiting

Rate limiting caps requests *per time window*. **Concurrency limiting** caps how
many requests are being processed **at the same time** for a key — for example,
"at most 5 simultaneous exports per user". It's the right tool for protecting
expensive, long-running endpoints from pile-ups.

```python
from django_smart_ratelimit import concurrency_limit

@concurrency_limit(key="user", max_concurrent=5)
def export_view(request):
    ...  # at most 5 of these run concurrently per user
```

When the limit is reached, additional requests get a `429` until an in-flight
request finishes and frees a slot.

## How it works

Each in-flight request takes a slot from an **atomic semaphore** (a Redis sorted
set, or the in-memory backend) on entry and releases it on exit. If a request
crashes before releasing, its slot is reclaimed after `ttl` seconds, so the
limiter self-heals rather than deadlocking.

## Arguments

| Argument | Default | Description |
| --- | --- | --- |
| `key` | — | Concurrency key. Resolves exactly like `@rate_limit`'s `key`: `"ip"`, `"user"`, a template such as `"user:{user.id}"`, or a callable. |
| `max_concurrent` | — | Maximum requests allowed in flight at once. |
| `ttl` | `60` | Seconds after which a held slot is assumed leaked and reclaimed. Set it above your longest expected request duration. |
| `backend` | `None` | Backend name override (defaults to the configured backend). |
| `block` | `True` | When `True`, an over-capacity request gets a `429`. When `False`, it runs anyway without holding a slot. |
| `response_callback` | `None` | Optional `(request) -> HttpResponse` for the over-capacity response. |

## Examples

```python
# Per-IP cap on a heavy report endpoint, with a generous hold time.
@concurrency_limit(key="ip", max_concurrent=3, ttl=300)
def report(request):
    ...

# A callable key, and observe-only mode (never blocks, just frees slots).
@concurrency_limit(key=lambda r: f"team:{r.user.team_id}", max_concurrent=10, block=False)
def bulk_import(request):
    ...

# Async views are supported too.
@concurrency_limit(key="user", max_concurrent=2)
async def async_export(request):
    ...
```

## Backends

Concurrency limiting needs a backend with semaphore support:

- **Redis** (recommended for production) — atomic and shared across processes and
  hosts. Use this for any multi-process / multi-host deployment.
- **Memory** — works in a single process; fine for development. (It is not shared
  across processes, so it does not enforce a global limit in a multi-worker
  deployment.)

Other backends raise `ImproperlyConfigured` when a concurrency-limited view is
called. This is independent of `RATELIMIT_BACKEND` for rate limiting — you can
pass `backend="redis"` to `@concurrency_limit` specifically.
