# Backends

## Available Backends

### Redis Backend

**Class**: `django_smart_ratelimit.backends.RedisBackend`

The most robust backend for distributed systems. Uses Lua scripts for atomic operations.

- **Pros**: Fast, Distributed, Atomic.
- **Cons**: External dependency.

### Async Redis Backend

**Class**: `django_smart_ratelimit.backends.AsyncRedisBackend`

The asynchronous version of the Redis backend, designed for use with `async` views.

- **Requirements**: `redis-py` >= 4.2.0.
- **Pros**: Non-blocking IO, high performance for async apps.

### MongoDB Backend

**Class**: `django_smart_ratelimit.backends.MongoDBBackend`

Uses MongoDB Time-To-Live (TTL) collections.

- **Pros**: Distributed, automatic cleanup via TTL.
- **Cons**: Slower than Redis. Requires `pymongo`.

### Memory Backend

**Class**: `django_smart_ratelimit.backends.MemoryBackend`

Local memory (dict) storage.

- **Pros**: Fastest, zero setup.
- **Cons**: Not distributed (limits are per-process), data lost on restart.

### Multi Backend

**Class**: `django_smart_ratelimit.backends.MultiBackend`

A wrapper that writes to multiple backends or fails over between them.

## Backend API

All backends implement `BaseBackend`:

- `check(key, rate, ...)`: Returns `True` if allowed, `False` if blocked.
- `get_health_status()`: Returns connectivity info.
