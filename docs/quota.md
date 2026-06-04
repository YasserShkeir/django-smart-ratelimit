# Quota Management

Rate limiting controls a *short-term* request rate (e.g. "100/minute").
**Quotas** track *cumulative usage* over a long period that resets on a calendar
boundary — for example, "10,000 requests per month per API key". Usage is stored
in the database (the `Quota` model), so it survives restarts and is visible and
adjustable in the Django admin.

```python
from django_smart_ratelimit import quota

@quota(key="user", limit=10000, period="month")
def api_view(request):
    ...
```

When the quota is exhausted, further requests get a `429` until the period
resets.

## Setup

Quotas use the database, so add the app and run migrations:

```python
INSTALLED_APPS = [..., "django_smart_ratelimit"]
```

```bash
python manage.py migrate
```

## Periods

| `period` | Resets at |
| --- | --- |
| `"day"` | midnight (start of the next day) |
| `"week"` | next Monday 00:00 |
| `"month"` | the 1st of next month 00:00 |
| `"year"` | next Jan 1 00:00 |
| `"30d"` / `7` (int) | a rolling N-day window from the period start |

Named periods are **calendar-aligned** — "month" means the quota resets on the
1st, matching how "10,000/month" is usually billed.

## Arguments

| Argument | Default | Description |
| --- | --- | --- |
| `key` | — | Quota key. Resolves like `@rate_limit`'s `key` (`"ip"`, `"user"`, a template, or a callable). |
| `limit` | — | Total units allowed per period. |
| `period` | `"month"` | See the table above. |
| `scope` | `""` | Namespaces independent quotas for the same key (e.g. `"exports"` vs `"uploads"`). |
| `cost` | `1` | Units charged per request — an int or `(request) -> int`. |
| `block` | `True` | When `True`, an over-quota request gets a `429`; when `False`, it passes (usage is still tracked). |
| `response_callback` | `None` | Optional `(request) -> HttpResponse` for the over-quota response. |

## Usage introspection

```python
from django_smart_ratelimit import get_quota_usage, consume_quota, reset_quota

# Inspect without consuming:
get_quota_usage("user:42")
# -> {"used": 8123, "limit": 10000, "remaining": 1877, "reset_at": ..., "period": "month"}

# Charge programmatically (e.g. from a background job):
allowed, info = consume_quota("user:42", limit=10000, period="month", cost=5)

# Clear a key's usage:
reset_quota("user:42")
```

## Examples

```python
# Separate monthly quotas per scope for the same user.
@quota(key="user", limit=1000, period="month", scope="exports")
def export(request): ...

@quota(key="user", limit=50, period="day", scope="uploads")
def upload(request): ...

# Weight expensive requests.
@quota(key="api_key:{request.api_key}", limit=100000, period="month",
       cost=lambda r: 10 if r.path.startswith("/heavy") else 1)
def api(request): ...

# Async views are supported.
@quota(key="user", limit=10000, period="month")
async def async_api(request): ...
```

Combine a quota with `@rate_limit` to enforce both a burst rate and a long-term
budget on the same endpoint.
