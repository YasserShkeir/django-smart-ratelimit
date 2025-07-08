# Django Smart Ratelimit - Architecture Design

## Overview

Django Smart Ratelimit is a flexible and efficient rate limiting library for Django applications. It provides both decorator-based and middleware-based rate limiting with support for multiple backends and algorithms.

## Architecture

### Core Components

```
┌─────────────────────┐
│   Django Views      │
│   @rate_limit       │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   Rate Limiter      │
│   (Decorator/MW)    │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   Backend Layer     │
│ (Redis/Database/    │
│     Memory)         │
└─────────────────────┘
```

### Component Responsibilities

1. **Decorator Layer** (`decorator.py`)

   - Applies rate limiting to individual views or functions
   - Handles key generation and rate parsing
   - Manages response headers and blocking behavior

2. **Middleware Layer** (`middleware.py`)

   - Applies rate limiting to all requests or specific paths
   - Configurable skip patterns and rate limits per path
   - Supports custom key functions

3. **Backend Layer** (`backends/`)
   - Abstracts storage implementation
   - Provides atomic operations for rate counting
   - Supports multiple algorithms (sliding window, fixed window)

## Rate Limiting Algorithms

### Fixed Window Algorithm

```
Time:     0s    60s   120s   180s
Window:   |-----|-----|-----|
Requests: [10]  [10]  [10]  [10]
```

**Characteristics:**

- Simple and memory efficient
- Potential for burst traffic at window boundaries
- Uses Redis INCR with expiration

**Implementation:**

```lua
local current = redis.call('GET', key)
if current == false then current = 0 end
local new_count = redis.call('INCR', key)
if new_count == 1 then
    redis.call('EXPIRE', key, window)
end
return new_count
```

### Sliding Window Algorithm

```
Time:     0s    30s    60s    90s   120s
Window:         |------60s------|
Requests:       [  distributed  ]
```

**Characteristics:**

- More accurate rate limiting
- Higher memory usage
- No burst traffic issues
- Uses Redis sorted sets with timestamps

**Implementation:**

```lua
-- Remove expired entries
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

-- Get current count
local current = redis.call('ZCARD', key)

if current < limit then
    -- Add current request
    redis.call('ZADD', key, now, now .. ':' .. math.random())
    redis.call('EXPIRE', key, window)
end
return current + 1
```

## Configuration

### Decorator Configuration

```python
@rate_limit(
    key='user:{user.id}',     # Key template or callable
    rate='10/m',              # Rate limit (10 per minute)
    block=True,               # Block or allow with headers
    backend='redis'           # Backend to use
)
def my_view(request):
    pass
```

### Middleware Configuration

```python
# settings.py
RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '100/m',
    'BACKEND': 'redis',
    'KEY_FUNCTION': 'myapp.utils.custom_key_function',
    'BLOCK': True,
    'SKIP_PATHS': ['/admin/', '/health/'],
    'RATE_LIMITS': {
        '/api/': '1000/h',
        '/auth/': '5/m',
    }
}
```

### Backend Configuration

```python
# Redis Backend
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
    'password': None,
}

# Database Backend
RATELIMIT_BACKEND = 'database'
RATELIMIT_DATABASE_CLEANUP_THRESHOLD = 1000

# Memory Backend
RATELIMIT_BACKEND = 'memory'
RATELIMIT_MEMORY_MAX_KEYS = 10000

# Algorithm Selection
RATELIMIT_ALGORITHM = "sliding_window"  # vs "fixed_window"
RATELIMIT_KEY_PREFIX = 'ratelimit:'
```

### Multi-Backend Support

```python
RATELIMIT_BACKEND = 'django_smart_ratelimit.backends.multi.MultiBackend'
RATELIMIT_BACKEND_CONFIG = {
    'backends': [
        {
            'name': 'primary_redis',
            'backend': 'django_smart_ratelimit.backends.redis_backend.RedisBackend',
            'config': {
                'host': 'redis-1.example.com',
                'port': 6379,
                'db': 0,
            }
        },
        {
            'name': 'secondary_redis',
            'backend': 'django_smart_ratelimit.backends.redis_backend.RedisBackend',
            'config': {
                'host': 'redis-2.example.com',
                'port': 6379,
                'db': 0,
            }
        },
        {
            'name': 'fallback_database',
            'backend': 'django_smart_ratelimit.backends.database.DatabaseBackend',
            'config': {}
        }
    ],
    'fallback_strategy': 'first_healthy',  # or 'round_robin'
    'health_check_interval': 30,  # seconds
    'health_check_timeout': 5,    # seconds
}
```

## Key Generation

### String Templates

```python
# Simple string keys
@rate_limit(key='api:endpoint', rate='10/m')

# With path info (future enhancement)
@rate_limit(key='user:{user.id}:endpoint', rate='10/m')
```

### Callable Keys

```python
def custom_key(request):
    if request.user.is_authenticated:
        return f"user:{request.user.id}"
    return f"ip:{request.META['REMOTE_ADDR']}"

@rate_limit(key=custom_key, rate='10/m')
```

## Response Headers

The library adds standard rate limiting headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 75
X-RateLimit-Reset: 1640995200
```

## Error Handling

### Rate Limit Exceeded

- **Blocked**: Returns HTTP 429 (Too Many Requests)
- **Non-blocked**: Continues with headers indicating limit exceeded

### Backend Errors

- Redis connection failures
- Script execution errors
- Configuration errors

## Performance Considerations

### Memory Usage

- **Fixed Window**: O(1) per key
- **Sliding Window**: O(n) per key (n = requests in window)

### Redis Operations

- **Fixed Window**: 2-3 Redis commands per request
- **Sliding Window**: 4-5 Redis commands per request

### Atomic Operations

All rate limiting operations are atomic using Lua scripts to prevent race conditions.

## Conditional Rate Limiting

### Skip Conditions

The `skip_if` parameter allows conditional bypassing of rate limiting based on request characteristics.

```python
@rate_limit(
    key='ip',
    rate='100/h',
    skip_if=lambda request: request.user.is_staff
)
def protected_view(request):
    """Rate limited for regular users, unlimited for staff."""
    pass
```

### Skip Function Design

Skip functions receive the request object and return a boolean:

```python
def complex_skip_logic(request):
    """Complex skip logic with multiple conditions."""
    # Skip for staff users
    if request.user.is_staff:
        return True

    # Skip for internal IP addresses
    ip = request.META.get('REMOTE_ADDR', '')
    if ip.startswith('192.168.') or ip.startswith('10.'):
        return True

    # Skip during maintenance windows
    from django.utils import timezone
    hour = timezone.now().hour
    if 2 <= hour <= 4:  # 2-4 AM maintenance
        return True

    return False

@rate_limit(key='ip', rate='50/h', skip_if=complex_skip_logic)
def conditional_api(request):
    """API with complex conditional rate limiting."""
    pass
```

### Error Handling in Skip Functions

Skip functions should handle errors gracefully:

```python
def safe_skip_function(request):
    """Skip function with error handling."""
    try:
        # Your skip logic here
        return request.user.is_superuser
    except Exception:
        # If skip function fails, continue with rate limiting
        return False
```

## Getting Help

- **Questions & General Help**: [GitHub Discussions](https://github.com/YasserShkeir/django-smart-ratelimit/discussions)
- **Bug Reports**: [GitHub Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues)
- **Feature Requests**: [Discussions - Ideas](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/ideas)
- **Examples**: Check the [examples/](../examples/) directory
