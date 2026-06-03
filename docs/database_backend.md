# Database Backend

The database backend stores rate-limit state in your SQL database using
Django's ORM, so you can rate limit without running Redis. It works on
PostgreSQL, MySQL, and SQLite, and uses database-level locking to keep the
sliding-window algorithm correct under concurrency.

It is implemented by `django_smart_ratelimit.backends.database.DatabaseBackend`
and registered under the short name `database`.

## When to Use It

Prefer the database backend when:

- You do not want to operate a separate Redis/memcached service, and your
  database already has spare capacity.
- Your traffic is low-to-moderate and you value operational simplicity over
  raw throughput.
- You want rate-limit state to live in the same transactional store as the
  rest of your data.

Prefer Redis (`RATELIMIT_BACKEND = "redis"`) when:

- You have high request volume. The sliding-window algorithm writes one row
  per request (`RateLimitEntry`), which is expensive on a SQL database.
- Latency matters and you want to keep this load off your primary database.

For high-throughput sliding-window limiting, Redis is the recommended backend.

## Setup

### 1. Add the app and run migrations

The backend's tables ship as migrations in the `django_smart_ratelimit` app,
so it must be in `INSTALLED_APPS`:

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django_smart_ratelimit",
]
```

```bash
python manage.py migrate
```

This creates four tables:

- `ratelimit_counter` (`RateLimitCounter`) — fixed-window counters.
- `ratelimit_entry` (`RateLimitEntry`) — one row per request, for sliding window.
- `ratelimit_token_bucket` (`RateLimitTokenBucket`) — token-bucket state.
- `ratelimit_leaky_bucket` (`RateLimitLeakyBucket`) — leaky-bucket state.

### 2. Select the backend

```python
# settings.py
RATELIMIT_BACKEND = "database"
```

The decorator and middleware now use the database backend automatically. No
other code changes are required.

## Choosing an Algorithm

The backend supports four algorithms:

- `fixed_window` — counts requests in a clock-aligned window
  (`RateLimitCounter`).
- `sliding_window` — counts requests in a rolling window by storing a row per
  request (`RateLimitEntry`).
- `token_bucket` — token-bucket limiting (`RateLimitTokenBucket`), via
  `token_bucket_check()`.
- `leaky_bucket` — leaky-bucket limiting (`RateLimitLeakyBucket`), via
  `leaky_bucket_check()`.

The algorithm used for `incr()` / `check_rate_limit()` (what the decorator and
middleware call) is `fixed_window` or `sliding_window`. Pass the algorithm to
the backend through `RATELIMIT_BACKEND_CONFIG`:

```python
# settings.py
RATELIMIT_BACKEND = "database"
RATELIMIT_BACKEND_CONFIG = {
    "algorithm": "sliding_window",  # or "fixed_window"
}
```

Other keys accepted by `RATELIMIT_BACKEND_CONFIG` (forwarded to
`DatabaseBackend.__init__`):

```python
RATELIMIT_BACKEND_CONFIG = {
    "algorithm": "fixed_window",
    "fail_open": False,             # allow requests if the DB errors
    "cleanup_interval": 300,        # seconds between background cleanup runs
    "batch_cleanup_size": 1000,     # rows deleted per cleanup batch
    "enable_background_cleanup": True,
}
```

## Concurrency and Atomicity

Fixed-window counters and the token/leaky buckets use
`select_for_update()` inside a transaction, so concurrent increments for the
same key are serialized by row locks.

The sliding-window algorithm needs extra care: its "insert a row, then count
the rows in the window" sequence is not atomic under `READ COMMITTED` (the
PostgreSQL and MySQL/InnoDB default), where two in-flight transactions can each
miss the other's not-yet-committed insert and both be admitted. To make it
atomic, the backend takes a per-key lock before the insert-and-count:

- **PostgreSQL** — a transaction-scoped advisory lock
  (`pg_advisory_xact_lock`), released automatically on commit or rollback.
- **MySQL** — a session-scoped named lock (`GET_LOCK` / `RELEASE_LOCK`),
  acquired around the transaction and released explicitly.
- **SQLite** — already serializes writers, so no extra lock is needed.

This matters for security-sensitive limits (for example, login throttling),
where a bypass would let the limit be exceeded by the number of concurrent
requests.

## Cleaning Up Expired Rows

Expired counters and entries (and stale buckets) accumulate over time. There
are two ways to remove them.

### Background cleanup (automatic)

By default the backend starts a daemon thread that calls `cleanup_expired()`
every `cleanup_interval` seconds (300 by default). This is convenient for
single-process deployments but is per-process and best-effort. For anything
beyond development, run the management command on a schedule instead and turn
the thread off:

```python
RATELIMIT_BACKEND_CONFIG = {
    "algorithm": "sliding_window",
    "enable_background_cleanup": False,
}
```

### `ratelimit_cleanup` management command

The `ratelimit_cleanup` command deletes, in batches: expired counters
(by `window_end`), expired sliding-window entries (by `expires_at`), and stale
token/leaky buckets (not updated within `--stale-days`).

```bash
# Delete all expired/stale records
python manage.py ratelimit_cleanup

# Preview without deleting anything
python manage.py ratelimit_cleanup --dry-run

# Smaller batches to reduce lock contention on a large table
python manage.py ratelimit_cleanup --batch-size=500

# Treat buckets unused for 14 days as stale (default: 7)
python manage.py ratelimit_cleanup --stale-days=14

# Machine-readable output for monitoring
python manage.py ratelimit_cleanup --json

# Detailed per-batch progress
python manage.py ratelimit_cleanup --verbose
```

`--batch-size` must be a positive integer; the command errors otherwise.

#### Scheduling it

Run it periodically. With cron, for example every five minutes:

```cron
*/5 * * * * cd /path/to/project && /path/to/venv/bin/python manage.py ratelimit_cleanup >> /var/log/ratelimit_cleanup.log 2>&1
```

With Celery beat:

```python
# settings.py
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "ratelimit-cleanup": {
        "task": "myapp.tasks.ratelimit_cleanup",
        "schedule": crontab(minute="*/5"),
    },
}
```

```python
# myapp/tasks.py
from celery import shared_task
from django.core.management import call_command


@shared_task
def ratelimit_cleanup():
    call_command("ratelimit_cleanup", batch_size=1000)
```

## Inspecting State

`DatabaseBackend` exposes helpers for monitoring and health checks:

```python
from django_smart_ratelimit.backends.factory import BackendFactory

backend = BackendFactory.create_backend("database")

backend.get_stats()      # active record counts, algorithm, database vendor, last cleanup
backend.health_check()   # {"status": "healthy"|"unhealthy", "response_time": ..., ...}
```

You can also query the models directly, for example to read the current count
for a key:

```python
from django_smart_ratelimit.models import RateLimitCounter, RateLimitEntry
```
