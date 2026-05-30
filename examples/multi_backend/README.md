# Multi-backend failover

Configure `RATELIMIT_BACKENDS` so rate limiting keeps working when the primary
store is unreachable. When `RATELIMIT_BACKENDS` (or `RATELIMIT_MULTI_BACKENDS`)
is set, the library automatically selects the multi-backend wrapper — you do not
set `RATELIMIT_BACKEND` to `"multi"` yourself.

Requires (for the Redis primary): `pip install "django-smart-ratelimit[redis]"`

- `settings.py` — a primary Redis backend with an in-memory fallback.

See [`docs/backends.md`](../../docs/backends.md) and
[`docs/configuration.md`](../../docs/configuration.md) for the full reference.
