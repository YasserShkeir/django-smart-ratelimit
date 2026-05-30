# Backends

## Selecting a Backend

Set `RATELIMIT_BACKEND` to either a short alias or a dotted class path.
When unset, the default is the in-memory backend.

```python
# settings.py

# Short alias (resolved via the built-in backend registry)
RATELIMIT_BACKEND = "redis"

# ...or an explicit dotted class path
RATELIMIT_BACKEND = "django_smart_ratelimit.backends.redis_backend.RedisBackend"
```

The recognized short aliases (from `backends/factory.py`, `BUILTIN_BACKENDS`) are:

| Alias         | Class path                                                       |
| ------------- | ---------------------------------------------------------------- |
| `memory`      | `django_smart_ratelimit.backends.memory.MemoryBackend`           |
| `redis`       | `django_smart_ratelimit.backends.redis_backend.RedisBackend`     |
| `async_redis` | `django_smart_ratelimit.backends.redis_backend.AsyncRedisBackend`|
| `mongodb`     | `django_smart_ratelimit.backends.mongodb.MongoDBBackend`         |
| `multi`       | `django_smart_ratelimit.backends.multi.MultiBackend`             |
| `database`    | `django_smart_ratelimit.backends.database.DatabaseBackend`       |

You can register your own backend under a custom alias with
`django_smart_ratelimit.backends.factory.register_backend(name, backend_class)`.

## Available Backends

### Redis Backend

**Alias**: `redis` &nbsp; **Class**: `django_smart_ratelimit.backends.redis_backend.RedisBackend`

The most robust backend for distributed systems. Uses Lua scripts for atomic operations.

- Pros: fast, distributed, atomic.
- Cons: external dependency. Install with `pip install django-smart-ratelimit[redis]`.

Connection options are read from `RATELIMIT_REDIS`, which accepts either
host/port/db keys or a single `url`:

```python
# settings.py
RATELIMIT_BACKEND = "redis"

RATELIMIT_REDIS = {
    "host": "localhost",
    "port": 6379,
    "db": 0,
}

# ...or, equivalently, a connection URL:
RATELIMIT_REDIS = {"url": "redis://localhost:6379/0"}
```

### Async Redis Backend

**Alias**: `async_redis` &nbsp; **Class**: `django_smart_ratelimit.backends.redis_backend.AsyncRedisBackend`

The asynchronous version of the Redis backend, designed for use with `async` views.
When `RATELIMIT_BACKEND = "redis"`, async views automatically use `AsyncRedisBackend`.

- Requirements: `redis-py` >= 4.2.0.
- Pros: non-blocking IO, high performance for async apps.

### MongoDB Backend

**Alias**: `mongodb` &nbsp; **Class**: `django_smart_ratelimit.backends.mongodb.MongoDBBackend`

Uses MongoDB Time-To-Live (TTL) collections.

- Pros: distributed, automatic cleanup via TTL.
- Cons: slower than Redis. Requires `pymongo` (`pip install django-smart-ratelimit[mongodb]`).

Connection options are read from `RATELIMIT_MONGODB`:

```python
# settings.py
RATELIMIT_BACKEND = "mongodb"

RATELIMIT_MONGODB = {
    "host": "localhost",
    "port": 27017,
    "database": "ratelimit",
}
```

### Database Backend

**Alias**: `database` &nbsp; **Class**: `django_smart_ratelimit.backends.database.DatabaseBackend`

Stores rate limit state in your Django database. This is the only built-in
backend with native leaky-bucket support.

- Pros: no extra infrastructure, works with your existing database.
- Cons: higher per-request overhead than Redis.

### Memory Backend

**Alias**: `memory` &nbsp; **Class**: `django_smart_ratelimit.backends.memory.MemoryBackend`

Local memory (dict) storage. This is the default when `RATELIMIT_BACKEND` is unset.

- Pros: fastest, zero setup.
- Cons: not distributed (limits are per-process), data lost on restart.

Tuning options:

```python
# settings.py
RATELIMIT_MEMORY_MAX_KEYS = 10000        # default
RATELIMIT_MEMORY_CLEANUP_INTERVAL = 300  # seconds, default
```

### Multi Backend

**Alias**: `multi` &nbsp; **Class**: `django_smart_ratelimit.backends.multi.MultiBackend`

A wrapper that writes to multiple backends or fails over between them. It is
selected automatically when `RATELIMIT_MULTI_BACKENDS` (or `RATELIMIT_BACKENDS`)
is configured.

Each entry needs a `type` (the backend alias) and may supply `options` (alias
`config`) and a `name`. The strategy is either `first_healthy` or `round_robin`.

```python
# settings.py
RATELIMIT_MULTI_BACKENDS = [
    {"name": "primary", "type": "redis", "options": {"host": "localhost", "port": 6379}},
    {"name": "fallback", "type": "memory", "options": {}},
]
RATELIMIT_MULTI_BACKEND_STRATEGY = "first_healthy"  # default
```

## Backend Names as Enums

Backend aliases above are plain strings. If you prefer the enums used for keys
and algorithms, those live in `django_smart_ratelimit.enums` (see the
configuration docs); backend selection itself accepts the alias strings shown
here. For algorithm selection, `RATELIMIT_ALGORITHM` accepts both the string
and the enum value:

```python
from django_smart_ratelimit.enums import Algorithm

# Equivalent:
RATELIMIT_ALGORITHM = "sliding_window"
RATELIMIT_ALGORITHM = Algorithm.SLIDING_WINDOW
```

Note that `leaky_bucket` (`Algorithm.LEAKY_BUCKET`) via the decorator requires a
backend with native leaky-bucket support (the `database` backend). On other
backends it warns and falls back to standard window limiting.

## Backend API

All backends inherit from `BaseBackend` (`django_smart_ratelimit.backends.base.BaseBackend`):

- `check_rate_limit(key, limit, period)`: returns a `(allowed, metadata)` tuple,
  where `allowed` is a `bool` and `metadata` is a dict (e.g. `count`, `remaining`).
- `health_check()`: returns a dict with connectivity information.
