# Analytics & Monitoring

`django-smart-ratelimit` can record every rate-limit decision the middleware
makes and report on it: a traffic summary, the top offenders, per-rule hit
counts, a staff-only dashboard, a CSV export, an offender drill-down, and
threshold-based email/webhook alerting.

Everything here is built on a single Django model, `RateLimitEvent`, that the
middleware writes one row per request to. Logging is **opt-in** and **off by
default** because it can generate a lot of rows on a busy site.

## Enabling Event Logging

Set `RATELIMIT_LOG_EVENTS = True` and make sure the `RateLimitMiddleware` is
installed. Each request the middleware checks then produces one `RateLimitEvent`
row.

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django_smart_ratelimit",
]

MIDDLEWARE = [
    # ...
    "django_smart_ratelimit.middleware.RateLimitMiddleware",
]

RATELIMIT_LOG_EVENTS = True
```

Because `RateLimitEvent` is a database model, run migrations once before
enabling it:

```bash
python manage.py migrate django_smart_ratelimit
```

Only requests that flow through `RateLimitMiddleware` are logged. Decorator-only
rate limits do not write events.

### Best-effort by design

Event logging is wrapped so it can **never break a request**. If the write
fails (database down, migrations missing, etc.) the middleware swallows the
error and the request proceeds normally — you simply get no event row for that
request. Treat the event log as best-effort reporting data, not an audit trail.

## The RateLimitEvent model

```python
from django_smart_ratelimit.models import RateLimitEvent
```

Each row records the outcome of one rate-limit check:

| Field        | Meaning                                                       |
| ------------ | ------------------------------------------------------------- |
| `timestamp`  | When the event was recorded (`auto_now_add`, indexed).        |
| `key`        | The rate-limit key (e.g. `ip:203.0.113.5`, `user:42`).        |
| `rule_name`  | Rule name, recovered from a `rule:<name>:...` key (or `""`).  |
| `path`       | Request path.                                                 |
| `method`     | HTTP method.                                                  |
| `allowed`    | `True` if allowed, `False` if blocked.                        |
| `count`      | Request count in the window at decision time.                 |
| `limit`      | The configured limit.                                         |
| `ip_address` | `REMOTE_ADDR`, if available.                                  |
| `user_id`    | The authenticated user's PK, or `None`.                       |

Rows are ordered newest-first and indexed on `timestamp`, `(key, timestamp)`,
and `(allowed, timestamp)` for time-range, per-key, and blocked-only reporting.
The model is registered read-only in the Django admin.

## Wiring up the URLs

The dashboard, CSV export, and offender-detail endpoint ship as a URLconf.
Include it from your project's `urls.py`:

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    # ...
    path("ratelimit/", include("django_smart_ratelimit.urls")),
]
```

That mounts three views (all gated to authenticated staff users):

| URL                                   | Name             | Returns                          |
| ------------------------------------- | ---------------- | -------------------------------- |
| `ratelimit/dashboard/`                | `dashboard`      | HTML dashboard                   |
| `ratelimit/dashboard/offenders.csv`   | `offenders-csv`  | CSV download of top offenders    |
| `ratelimit/dashboard/offender/`       | `offender-detail`| JSON drill-down for one `key`    |

All three accept an optional `?days=` query parameter (clamped to `1..365`,
default `7`).

## The dashboard

`ratelimit/dashboard/` renders a staff-only summary for the requested window.
Non-staff and anonymous requests get a `403 Forbidden`.

```text
GET /ratelimit/dashboard/?days=30
```

The view (`RateLimitDashboardView`) populates its template context with:

- `today` — `get_traffic_summary(days=1)`
- `window` — `get_traffic_summary(days=days)`
- `top_offenders` — `get_top_offenders(days=days, limit=20)`
- `rule_hits` — `get_rule_hit_counts(days=days, limit=20)`

It renders `django_smart_ratelimit/dashboard.html`. Override that template in
your own templates directory if you want to restyle it.

### CSV export

`ratelimit/dashboard/offenders.csv` streams the top offenders (up to 1000) as a
CSV attachment for the requested window:

```text
GET /ratelimit/dashboard/offenders.csv?days=30
```

```csv
key,blocked_count
ip:203.0.113.5,412
user:42,87
```

### Offender detail (JSON)

`ratelimit/dashboard/offender/?key=<key>` returns a JSON drill-down for a single
key. The `key` parameter is required; omitting it returns `400`.

```text
GET /ratelimit/dashboard/offender/?key=ip:203.0.113.5&days=7
```

```json
{
  "key": "ip:203.0.113.5",
  "days": 7,
  "total": 530,
  "allowed": 118,
  "blocked": 412,
  "block_rate": 0.777,
  "first_seen": "2026-05-01T08:14:02Z",
  "last_seen": "2026-05-07T22:41:55Z",
  "by_path": [{"path": "/api/login", "blocked_count": 300}],
  "recent_events": [
    {
      "timestamp": "2026-05-07T22:41:55Z",
      "path": "/api/login",
      "method": "POST",
      "allowed": false,
      "count": 11,
      "limit": 10,
      "rule_name": "login"
    }
  ]
}
```

## Aggregation functions

The dashboard and exports are thin wrappers over functions in
`django_smart_ratelimit.analytics`. You can call them directly from your own
code, shell, or reporting jobs:

```python
from django_smart_ratelimit.analytics import (
    get_traffic_summary,
    get_top_offenders,
    get_rule_hit_counts,
    offenders_csv,
    get_offender_detail,
)

# Total / allowed / blocked counts and block rate over the last N days.
get_traffic_summary(days=1)
# {"days": 1, "total": 5, "allowed": 2, "blocked": 3, "block_rate": 0.6}

# Keys with the most BLOCKED requests, descending.
get_top_offenders(days=7, limit=100)
# [{"key": "ip:203.0.113.5", "blocked_count": 412}, ...]

# Per-rule total hits and blocked counts (rows with a rule_name only).
get_rule_hit_counts(days=7, limit=50)
# [{"rule_name": "login", "hits": 900, "blocked": 412}, ...]

# Top offenders rendered as a CSV string.
offenders_csv(days=7, limit=1000)

# Full drill-down for one key (the JSON the offender-detail view returns).
get_offender_detail("ip:203.0.113.5", days=7, recent=50)
```

All windows are relative to "now": `days=7` means events with a `timestamp`
within the last 7 days. Events outside the window are ignored.

## Threshold alerting

The library can find offenders whose blocked-request count over a window crosses
a threshold and dispatch alerts by email and/or webhook.

### Settings

```python
# settings.py
RATELIMIT_ALERT_THRESHOLD = 100          # min blocked requests to alert on
RATELIMIT_ALERT_EMAILS = ["ops@example.com"]
RATELIMIT_ALERT_WEBHOOK = "https://hooks.example.com/ratelimit"
```

`RATELIMIT_ALERT_THRESHOLD` gates everything: with no threshold set (and no
`--threshold` passed) alerting is disabled and nothing is sent. Email uses
Django's configured mail backend (and `DEFAULT_FROM_EMAIL`); the webhook
receives a `POST` with a JSON body.

Alert dispatch is **best-effort**: a failing channel is logged and reported in
the result, never raised.

### The `ratelimit_alerts` command (cron)

Run the check on a schedule (cron or Celery beat). It defaults to the
look-back window of 1 day and reads the threshold/channels from settings when
the flags are omitted:

```bash
# Use RATELIMIT_ALERT_THRESHOLD and the configured channels, last 1 day.
python manage.py ratelimit_alerts

# Explicit threshold and window.
python manage.py ratelimit_alerts --threshold 100 --days 1

# Preview matching offenders without sending anything.
python manage.py ratelimit_alerts --threshold 100 --dry-run
```

Example crontab entry (every 5 minutes):

```cron
*/5 * * * * /path/to/venv/bin/python /path/to/manage.py ratelimit_alerts >> /var/log/ratelimit_alerts.log 2>&1
```

### Programmatic API

The same logic is available as functions:

```python
from django_smart_ratelimit.analytics import (
    find_alertable_offenders,
    send_offender_alerts,
)

# Offenders whose blocked count over the window is >= threshold.
find_alertable_offenders(threshold=100, days=1, limit=100)
# [{"key": "ip:203.0.113.5", "blocked_count": 412}]

# Find offenders over the threshold and dispatch alerts. Arguments fall back
# to RATELIMIT_ALERT_THRESHOLD / RATELIMIT_ALERT_EMAILS / RATELIMIT_ALERT_WEBHOOK.
result = send_offender_alerts(threshold=100, days=1)
# {
#   "enabled": True,
#   "threshold": 100,
#   "days": 1,
#   "offenders": [...],
#   "channels": {"email": {"sent": True, "to": ["ops@example.com"]}},
# }
```

When alerting is disabled (no threshold), `send_offender_alerts()` returns
`{"enabled": False, "offenders": [], "channels": {}}` without doing any work.
You can also override the channels per call with the `email_to` and
`webhook_url` keyword arguments.

## Retention / cleanup

One row per request adds up fast, so prune old events on a schedule.
`RateLimitEvent.cleanup_old()` deletes events older than a cutoff (in batches)
and returns the number deleted:

```python
from django_smart_ratelimit.models import RateLimitEvent

# Delete events older than 30 days (the default).
deleted = RateLimitEvent.cleanup_old(older_than_days=30)

# Shorter retention, smaller delete batches.
RateLimitEvent.cleanup_old(older_than_days=7, batch_size=500)
```

Schedule it from cron or Celery beat, for example via a tiny management command
or a `manage.py shell -c` invocation:

```cron
0 3 * * * /path/to/venv/bin/python /path/to/manage.py shell -c "from django_smart_ratelimit.models import RateLimitEvent; RateLimitEvent.cleanup_old(older_than_days=30)"
```

> **Note:** the `ratelimit_cleanup` management command prunes the rate-limit
> *state* tables (counters, sliding-window entries, token/leaky buckets) — it
> does **not** touch `RateLimitEvent`. Use `RateLimitEvent.cleanup_old()` to
> prune the analytics log.

## See Also

- [Observability](observability.md) — OpenTelemetry and Prometheus integrations
  for real-time metrics (complementary to this historical event log).
- [Configuration](configuration.md) — all `RATELIMIT_*` settings.
- [Deployment](deployment.md) — running scheduled jobs in production.
