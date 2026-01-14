# Deployment Guide

## Production Checklist

### 1. Use Redis

For any setup involving more than one worker process (e.g., Gunicorn, uWSGI) or multiple servers, you **must** use Redis. The Memory backend is process-local and will not enforce global limits correctly.

### 2. Configure Circuit Breakers

In production, external services (Redis) can fail. Ensure `RATELIMIT_FAIL_OPEN` or circuit breakers are configured to your risk tolerance.

- **Fail Open**: If Redis dies, traffic flows unrestricted. (Good for availability).
- **Fail Closed**: If Redis dies, traffic is blocked. (Good for strict security).

### 3. Cache Prefixing

If sharing a Redis instance with other applications, use the `RATELIMIT_CACHE_PREFIX` setting to avoid key collisions.

```python
# settings.py
RATELIMIT_REDIS = {
    # ...
    'prefix': 'myapp_rl:'
}
```

### 4. Monitoring

Use the management command `python manage.py ratelimit_health` in your Kubernetes probes or health check endpoints to verify the rate limiter is operational.

## Performance Tuning

- **Token Bucket**: Generally the most performant as it requires few operations.
- **Connection Pooling**: The Redis backend uses `django-redis` connection pooling if available.
