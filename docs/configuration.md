# Configuration

This page provides a complete reference of all Django Smart Ratelimit settings.

## Core Settings

```python
# Enable/disable rate limiting globally (default: True)
RATELIMIT_ENABLE = True

# Default algorithm for rate limiting (default: 'sliding_window')
# Options: 'sliding_window', 'fixed_window', 'token_bucket', 'leaky_bucket'
RATELIMIT_ALGORITHM = 'sliding_window'

# Default rate limit when not specified in decorator (default: '100/m')
RATELIMIT_DEFAULT_LIMIT = '100/m'

# Key prefix for all rate limit cache keys (default: 'ratelimit:')
RATELIMIT_KEY_PREFIX = 'ratelimit:'
```

## Backend Configuration

### Redis (Recommended)

```python
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
}
```

> **Async Support**: When using `RATELIMIT_BACKEND = 'redis'`, the library automatically uses `AsyncRedisBackend` for asynchronous views (`async def`). No separate configuration is required.

### MongoDB

```python
RATELIMIT_BACKEND = 'mongodb'
RATELIMIT_MONGODB = {
    'uri': 'mongodb://localhost:27017',
    'database': 'ratelimit',
    'collection': 'ratelimits',
}
```

### Memory Backend

```python
RATELIMIT_BACKEND = 'memory'

# Maximum number of keys to store (default: 10000)
RATELIMIT_MEMORY_MAX_KEYS = 10000

# Cleanup interval in seconds (default: 300)
RATELIMIT_MEMORY_CLEANUP_INTERVAL = 300
```

> **Note**: The memory backend stores data in process memory and does not share state across workers. Best for development or single-process deployments.

### Multi-Backend with Failover

```python
RATELIMIT_BACKENDS = [
    {
        'name': 'primary_redis',
        'backend': 'redis',
        'config': {'host': 'redis-primary.example.com'}
    },
    {
        'name': 'fallback_memory',
        'backend': 'memory',
        'config': {}
    }
]

# Strategy for selecting backend (default: 'first_healthy')
RATELIMIT_MULTI_BACKEND_STRATEGY = 'first_healthy'
```

## Window Alignment Configuration

Controls how time windows are calculated for rate limiting.

```python
# Align windows to clock boundaries (default: True)
RATELIMIT_ALIGN_WINDOW_TO_CLOCK = True
```

### Clock-Aligned Windows (Default)

When `RATELIMIT_ALIGN_WINDOW_TO_CLOCK = True`:

- A `60/m` rate limit window starts at `:00` seconds (e.g., 12:00:00, 12:01:00)
- All users share the same window boundaries
- `X-RateLimit-Reset` headers show predictable clock-aligned times
- **Best for**: Most use cases, predictable reset times, consistent user experience

### First-Request-Aligned Windows

When `RATELIMIT_ALIGN_WINDOW_TO_CLOCK = False`:

- A `60/m` rate limit window starts when each user's first request arrives
- Each user has independent window boundaries
- `X-RateLimit-Reset` headers show the time since first request
- **Best for**: APIs where you want users to get their full quota regardless of when they start

### Example

With a `5/m` limit and clock alignment enabled:

- User A's first request at 12:00:30 → window is 12:00:00-12:01:00 (30s remaining)
- User B's first request at 12:00:45 → same window 12:00:00-12:01:00 (15s remaining)

With clock alignment disabled:

- User A's first request at 12:00:30 → window is 12:00:30-12:01:30 (60s remaining)
- User B's first request at 12:00:45 → window is 12:00:45-12:01:45 (60s remaining)

## Circuit Breaker Configuration

Protects your application when backends are unhealthy.

```python
# settings.py
RATELIMIT_CIRCUIT_BREAKER = {
    'failure_threshold': 5,        # Open circuit after 5 failures
    'recovery_timeout': 60,        # Wait 60 seconds before testing recovery
    'reset_timeout': 300,          # Reset after 5 minutes of success
    'half_open_max_calls': 1,      # Test with 1 call in half-open state
}

# Storage for circuit breaker state (default: 'memory')
RATELIMIT_CIRCUIT_BREAKER_STORAGE = 'memory'

# Redis URL for distributed circuit breaker state (optional)
RATELIMIT_CIRCUIT_BREAKER_REDIS_URL = 'redis://localhost:6379/1'
```

## Health Check Configuration

```python
# How often to check backend health in seconds (default: 30)
RATELIMIT_HEALTH_CHECK_INTERVAL = 30

# Timeout for health check operations in seconds (default: 5)
RATELIMIT_HEALTH_CHECK_TIMEOUT = 5
```

## Error Handling Configuration

```python
# Fail open on backend errors (default: False)
# If True, requests are allowed when the backend fails
RATELIMIT_FAIL_OPEN = True

# Log exceptions (default: True)
RATELIMIT_LOG_EXCEPTIONS = True

# Custom exception handler
# Path to a function that takes (request, exception) and returns a response or None
RATELIMIT_EXCEPTION_HANDLER = 'myproject.utils.custom_ratelimit_handler'
```

## Performance & Metrics

```python
# Enable metrics collection (default: False)
RATELIMIT_COLLECT_METRICS = True
```

## Middleware Configuration

```python
# Configure middleware behavior
RATELIMIT_MIDDLEWARE = {
    'enabled': True,
    'excluded_paths': ['/health/', '/metrics/'],
}
```

## Custom Configuration

You can add custom configuration values using the `RATELIMIT_CONFIG_` prefix:

```python
# These become accessible as config.custom_configs['mykey']
RATELIMIT_CONFIG_MYKEY = 'custom_value'
RATELIMIT_CONFIG_API_TIER = 'premium'
```
