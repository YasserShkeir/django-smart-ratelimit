# Deployment Guide

## Production Checklist

### 1. Use Redis

For any setup involving more than one worker process (e.g., Gunicorn, uWSGI) or multiple servers, you **must** use Redis. The memory backend is process-local and will not enforce global limits correctly.

```python
# settings.py
RATELIMIT_BACKEND = "redis"
RATELIMIT_REDIS = {
    "host": "127.0.0.1",
    "port": 6379,
    "db": 0,
}
# Or point at a single connection URL instead of host/port/db:
# RATELIMIT_REDIS = {"url": "redis://127.0.0.1:6379/0"}
```

Note: the setting is `RATELIMIT_BACKEND` (not `RATELIMIT_DEFAULT_BACKEND`), and there is no
`RATELIMIT_REDIS_URL` setting. Pass a URL via `RATELIMIT_REDIS = {"url": "..."}`.

### 2. Configure failure behavior

In production, external services (Redis) can fail. Configure `RATELIMIT_FAIL_OPEN` and, optionally, circuit breakers to your risk tolerance.

- **Fail open** (`RATELIMIT_FAIL_OPEN = True`): if the backend is unreachable, requests are allowed through. Good for availability.
- **Fail closed** (`RATELIMIT_FAIL_OPEN = False`, the default): if the backend is unreachable, requests are blocked. Good for strict security.

```python
# settings.py
RATELIMIT_FAIL_OPEN = True  # default is False (fail closed)
```

Circuit-breaker behavior is configured with `RATELIMIT_CIRCUIT_BREAKER` (a dict), and its
shared state can be stored via `RATELIMIT_CIRCUIT_BREAKER_STORAGE` /
`RATELIMIT_CIRCUIT_BREAKER_REDIS_URL`.

### 3. Key prefixing

If you share a Redis instance with other applications, set `RATELIMIT_KEY_PREFIX` to avoid key collisions. This prefix is applied to every rate-limit key across all backends. The default is `"ratelimit:"`.

```python
# settings.py
RATELIMIT_KEY_PREFIX = "myapp_rl:"
```

### 4. Trusted proxies and client IP extraction

IP-based keys and the CIDR allow/deny lists derive the client IP from request headers,
preferring proxy headers in this order before falling back to the socket address:

1. `CF-Connecting-IP` (Cloudflare)
2. `X-Forwarded-For` (first/left-most entry when comma-separated)
3. `X-Real-IP` (nginx)
4. `REMOTE_ADDR` (direct connection)

This affects the `"ip"` and `"user_or_ip"` keys (`RateLimitKey.IP`, `RateLimitKey.USER_OR_IP`)
and the `allow_list` / `deny_list` arguments of the `rate_limit` decorator.

**These headers are trusted as-is.** The library does not currently validate proxy trust,
and any client can set `X-Forwarded-For` or `CF-Connecting-IP` on a request. If your app is
reachable directly (no header-sanitizing proxy in front), a client can spoof its IP to:

- match an `allow_list` entry and bypass rate limiting, or
- evade a `deny_list` entry, or
- pollute the keyspace by forging a different IP on every request.

Only deploy IP keys or CIDR allow/deny lists behind a reverse proxy you control. That proxy
**must**:

- **Overwrite** the forwarded header with the real peer address (do not append).
- **Strip** any client-supplied `X-Forwarded-For`, `X-Real-IP`, and `CF-Connecting-IP`
  values on inbound requests so they cannot reach Django.

There is no Django `TRUSTED_PROXIES` setting in this library; proxy trust is enforced at the
edge (your nginx / load balancer / CDN), not in application settings.

Example: nginx terminating TLS in front of the app. `proxy_set_header` replaces the value
the upstream sees, so any client-supplied header is discarded:

```nginx
location / {
    proxy_pass http://app_upstream;
    # Replace, not append: the client cannot inject these.
    proxy_set_header X-Real-IP        $remote_addr;
    proxy_set_header X-Forwarded-For  $remote_addr;
    # If you are NOT behind Cloudflare, also clear CF-Connecting-IP so a
    # client cannot forge it (this header is preferred first).
    proxy_set_header CF-Connecting-IP "";
}
```

If you sit behind Cloudflare, restrict the origin to Cloudflare's IP ranges and let
Cloudflare set `CF-Connecting-IP`; do not accept it from arbitrary sources.

### 5. Monitoring

Use the management command `python manage.py ratelimit_health` in your Kubernetes probes or
health-check endpoints to verify the rate limiter is operational (add `--json` for
machine-readable output, `--verbose` for per-backend detail). Use
`python manage.py ratelimit_cleanup` to prune expired entries on backends that need it.

## Performance Tuning

- **Algorithm choice**: `token_bucket` (`Algorithm.TOKEN_BUCKET`) is generally efficient and
  smooths bursts. The default is `sliding_window` (`Algorithm.SLIDING_WINDOW`). Algorithm
  selection is honored by the synchronous decorator; on async views it currently logs a
  warning and falls back to window counting.
- **Connection pooling**: the Redis backend reuses connection pools across requests.
