# Backend Configuration Guide

Django Smart Ratelimit supports multiple backends for storing rate limiting data. Each backend has different characteristics and use cases.

## Backend Types Overview

| Backend           | Use Case          | Performance | Persistence | Multi-Server |
| ----------------- | ----------------- | ----------- | ----------- | ------------ |
| **Redis**         | Production        | Excellent   | Yes         | Yes          |
| **Database**      | Small scale       | Good        | Yes         | Yes          |
| **Memory**        | Development       | Excellent   | No          | No           |
| **Multi-Backend** | High availability | Excellent   | Yes         | Yes          |

## Redis Backend (Recommended)

The Redis backend is recommended for production use due to its high performance and atomic operations.

### Basic Configuration

```python
# settings.py
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
    'password': None,
}
```

### Advanced Redis Configuration

```python
# settings.py
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
    'password': 'your-redis-password',
    'socket_timeout': 0.1,
    'socket_connect_timeout': 0.1,
    'socket_keepalive': True,
    'socket_keepalive_options': {},
    'connection_pool_kwargs': {
        'max_connections': 50,
        'retry_on_timeout': True,
    },
    'key_prefix': 'ratelimit:',
}
```

### Redis Cluster Configuration

```python
# settings.py
RATELIMIT_REDIS = {
    'startup_nodes': [
        {'host': 'redis-node-1.example.com', 'port': 7000},
        {'host': 'redis-node-2.example.com', 'port': 7000},
        {'host': 'redis-node-3.example.com', 'port': 7000},
    ],
    'password': 'cluster-password',
    'decode_responses': True,
    'skip_full_coverage_check': True,
}
```

### Redis Sentinel Configuration

```python
# settings.py
RATELIMIT_REDIS = {
    'sentinels': [
        ('sentinel-1.example.com', 26379),
        ('sentinel-2.example.com', 26379),
        ('sentinel-3.example.com', 26379),
    ],
    'service_name': 'mymaster',
    'password': 'redis-password',
    'sentinel_kwargs': {
        'password': 'sentinel-password',
    },
}
```

### Redis Features

- **Atomic Operations**: Uses Lua scripts for atomic increment and reset operations
- **High Performance**: Sub-millisecond response times
- **Persistence**: Data survives Redis restarts (with proper Redis configuration)
- **Clustering**: Supports Redis Cluster and Sentinel for high availability
- **Memory Efficient**: Automatic expiration of rate limiting keys

## Database Backend

The database backend stores rate limiting data in your Django database. Good for smaller applications or when Redis is not available.

### Basic Configuration

```python
# settings.py
RATELIMIT_BACKEND = 'database'
```

### Advanced Database Configuration

```python
# settings.py
RATELIMIT_BACKEND = 'database'
RATELIMIT_DATABASE_CLEANUP_THRESHOLD = 1000  # Clean when this many expired entries exist
```

### Database Models

The database backend uses two models:

- `RateLimitEntry`: For sliding window algorithm
- `RateLimitCounter`: For fixed window algorithm

### Database Optimization

Add indexes for better performance:

```sql
-- For PostgreSQL
CREATE INDEX CONCURRENTLY idx_ratelimit_entry_key_window
ON django_smart_ratelimit_ratelimitentry (key, window_start);

CREATE INDEX CONCURRENTLY idx_ratelimit_counter_key_expires
ON django_smart_ratelimit_ratelimitcounter (key, expires_at);

-- For MySQL
ALTER TABLE django_smart_ratelimit_ratelimitentry
ADD INDEX idx_key_window (key, window_start);

ALTER TABLE django_smart_ratelimit_ratelimitcounter
ADD INDEX idx_key_expires (key, expires_at);
```

### Database Features

- **Persistence**: Data stored in your regular database
- **Transactions**: Atomic operations using database transactions
- **Cleanup**: Automatic cleanup of expired entries
- **Multi-Server**: Works across multiple application servers
- **Backup**: Included in regular database backups

## Memory Backend

The memory backend stores rate limiting data in Python memory. Only suitable for development or single-server deployments.

### Basic Configuration

```python
# settings.py
RATELIMIT_BACKEND = 'memory'
```

### Advanced Memory Configuration

```python
# settings.py
RATELIMIT_BACKEND = 'memory'
RATELIMIT_MEMORY_MAX_KEYS = 10000  # Maximum number of keys to store
RATELIMIT_MEMORY_CLEANUP_INTERVAL = 300  # Cleanup interval in seconds
```

### Memory Features

- **Fast**: Fastest backend (no network or disk I/O)
- **Simple**: No external dependencies
- **Limited**: Memory only, lost on restart
- **Single Server**: Cannot share data between servers

### Memory Limitations

⚠️ **Important Limitations:**

- Data is lost when the process restarts
- Cannot share rate limiting data between multiple servers
- Memory usage grows with the number of unique keys
- Not suitable for production use

## Multi-Backend (High Availability)

The multi-backend allows using multiple backends with automatic fallback. This provides high availability and fault tolerance.

### Basic Multi-Backend Configuration

```python
# settings.py
RATELIMIT_BACKENDS = [
    {
        'name': 'primary_redis',
        'backend': 'redis',
        'config': {'host': 'redis-primary.example.com'}
    },
    {
        'name': 'fallback_redis',
        'backend': 'redis',
        'config': {'host': 'redis-fallback.example.com'}
    },
    {
        'name': 'emergency_database',
        'backend': 'database',
        'config': {}
    }
]
```

### Advanced Multi-Backend Configuration

```python
# settings.py
RATELIMIT_BACKENDS = [
    {
        'name': 'primary_redis',
        'backend': 'django_smart_ratelimit.backends.redis_backend.RedisBackend',
        'config': {
            'host': 'redis-primary.example.com',
            'port': 6379,
            'db': 0,
            'password': 'redis-password',
        }
    },
    {
        'name': 'fallback_redis',
        'backend': 'django_smart_ratelimit.backends.redis_backend.RedisBackend',
        'config': {
            'host': 'redis-fallback.example.com',
            'port': 6379,
            'db': 0,
            'password': 'redis-password',
        }
    },
    {
        'name': 'emergency_database',
        'backend': 'django_smart_ratelimit.backends.database.DatabaseBackend',
        'config': {
            'cleanup_threshold': 500,
        }
    }
]

# Multi-backend strategy configuration
RATELIMIT_MULTI_BACKEND_STRATEGY = 'first_healthy'  # or 'round_robin'
RATELIMIT_HEALTH_CHECK_INTERVAL = 30  # seconds
RATELIMIT_HEALTH_CHECK_TIMEOUT = 5    # seconds
```

### Fallback Strategies

#### First Healthy Strategy

Uses the first healthy backend in the list. Provides consistent behavior and prioritizes your primary backend.

```python
RATELIMIT_MULTI_BACKEND_STRATEGY = 'first_healthy'
```

**Behavior:**

1. Check backends in order
2. Use the first healthy backend
3. Skip unhealthy backends
4. Fail if all backends are unhealthy

#### Round Robin Strategy

Distributes load across all healthy backends. Provides load balancing but may have slight inconsistencies.

```python
RATELIMIT_MULTI_BACKEND_STRATEGY = 'round_robin'
```

**Behavior:**

1. Rotate through healthy backends
2. Skip unhealthy backends
3. Balance load across backends
4. Fail if all backends are unhealthy

### Multi-Backend Features

- **High Availability**: Automatic failover when backends fail
- **Load Balancing**: Distribute load across multiple backends (round-robin)
- **Health Monitoring**: Continuous health checking of backends
- **Flexible Configuration**: Mix different backend types
- **Graceful Degradation**: Falls back to slower but available backends

### Multi-Backend Best Practices

1. **Order backends by preference** (fastest/most reliable first)
2. **Include a database backend** as emergency fallback
3. **Monitor backend health** using the health check command
4. **Test failover scenarios** in staging
5. **Use consistent configurations** across environments

## Algorithm Selection

All backends support both rate limiting algorithms:

### Fixed Window Algorithm

```python
RATELIMIT_ALGORITHM = 'fixed_window'
```

- **Fast**: Lower computational overhead
- **Memory efficient**: Single counter per key
- **Burst traffic**: Allows bursts at window boundaries
- **Predictable**: Fixed reset times

### Sliding Window Algorithm

```python
RATELIMIT_ALGORITHM = 'sliding_window'
```

- **Accurate**: Smooth rate limiting without bursts
- **Complex**: Higher computational overhead
- **Memory usage**: Stores individual request timestamps
- **Flexible**: More precise rate limiting

## Algorithm Support

All backends support both sliding window and fixed window algorithms. You can configure the algorithm globally or per-decorator.

### Global Algorithm Configuration

```python
# settings.py - Set default algorithm for Redis backend
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
    'algorithm': 'sliding_window',  # Default algorithm
}

# For MongoDB backend
RATELIMIT_MONGODB = {
    'host': 'localhost',
    'port': 27017,
    'database': 'ratelimit',
    'algorithm': 'fixed_window',  # Default algorithm
}
```

### Per-Decorator Algorithm Selection

```python
from django_smart_ratelimit import rate_limit

# Use sliding window for smooth rate limiting
@rate_limit(key='ip', rate='100/h', algorithm='sliding_window')
def smooth_api(request):
    return JsonResponse({'algorithm': 'sliding_window'})

# Use fixed window for burst-tolerant rate limiting
@rate_limit(key='ip', rate='100/h', algorithm='fixed_window')
def burst_api(request):
    return JsonResponse({'algorithm': 'fixed_window'})
```

### Algorithm Characteristics

| Algorithm      | Behavior                    | Use Case                         |
| -------------- | --------------------------- | -------------------------------- |
| Sliding Window | Smooth, even distribution   | Consistent load, API protection  |
| Fixed Window   | Allows bursts at boundaries | Batch operations, periodic tasks |

## Backend Selection Guide

### Production Applications

**Small to Medium Scale (< 1M requests/day):**

```python
RATELIMIT_BACKEND = 'database'
RATELIMIT_ALGORITHM = 'fixed_window'
```

**Large Scale (> 1M requests/day):**

```python
RATELIMIT_BACKEND = 'redis'
RATELIMIT_ALGORITHM = 'sliding_window'
```

**High Availability Requirements:**

```python
RATELIMIT_BACKENDS = [
    {'name': 'primary', 'backend': 'redis', 'config': {...}},
    {'name': 'fallback', 'backend': 'redis', 'config': {...}},
    {'name': 'emergency', 'backend': 'database', 'config': {}}
]
```

### Development and Testing

**Development:**

```python
RATELIMIT_BACKEND = 'memory'
RATELIMIT_ALGORITHM = 'fixed_window'
```

**Testing:**

```python
RATELIMIT_BACKEND = 'memory'  # Fast and isolated
```

### Migration Scenarios

**From django-ratelimit:**

```python
RATELIMIT_BACKEND = 'database'  # Similar to cache backend
RATELIMIT_ALGORITHM = 'fixed_window'
```

**Scaling up:**

```python
# Start with database
RATELIMIT_BACKEND = 'database'

# Move to Redis
RATELIMIT_BACKEND = 'redis'

# Add high availability
RATELIMIT_BACKENDS = [...]
```

## Troubleshooting

### Common Issues

#### Redis Connection Errors

```python
# Check Redis connectivity
python manage.py ratelimit_health

# Common solutions:
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'socket_timeout': 1.0,      # Increase timeout
    'socket_connect_timeout': 1.0,
    'retry_on_timeout': True,   # Retry on timeout
}
```

#### Database Performance Issues

```python
# Add database indexes
python manage.py dbshell
# Run the CREATE INDEX commands shown above

# Increase cleanup threshold
RATELIMIT_DATABASE_CLEANUP_THRESHOLD = 5000

# Use fixed window for better performance
RATELIMIT_ALGORITHM = 'fixed_window'
```

#### Memory Backend Limitations

```python
# Increase memory limits
RATELIMIT_MEMORY_MAX_KEYS = 50000

# More frequent cleanup
RATELIMIT_MEMORY_CLEANUP_INTERVAL = 60
```

### Health Monitoring

```bash
# Check backend health
python manage.py ratelimit_health

# Detailed health check
python manage.py ratelimit_health --verbose

# JSON output for monitoring
python manage.py ratelimit_health --json
```

### Performance Monitoring

Monitor these metrics:

- Response times for rate limit checks
- Backend error rates
- Memory usage (for memory backend)
- Database query times (for database backend)
- Redis connection pool usage

## Custom Backends

You can create custom backends by extending the `BaseBackend` class:

```python
from django_smart_ratelimit.backends.base import BaseBackend

class CustomBackend(BaseBackend):
    def incr(self, key: str, period: int) -> int:
        # Your implementation
        pass

    def get_count(self, key: str) -> int:
        # Your implementation
        pass

    def get_reset_time(self, key: str) -> Optional[int]:
        # Your implementation
        pass

    def reset(self, key: str) -> None:
        # Your implementation
        pass

# Use your custom backend
RATELIMIT_BACKEND = 'myapp.backends.CustomBackend'
```

See the [Custom Backends Guide](custom_backends.md) for detailed instructions.

## Getting Help

- **Backend Configuration Questions**: [GitHub Discussions - Q&A](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/q-a)
- **Performance Issues**: [GitHub Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues)
- **Feature Requests**: [Discussions - Ideas](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/ideas)
- **Examples**: Check the [examples/backend_configuration.py](../examples/backend_configuration.py)
