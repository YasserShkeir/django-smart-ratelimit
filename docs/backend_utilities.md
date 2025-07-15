# Backend Development Utilities

The `django_smart_ratelimit.backends.utils` module provides a comprehensive set of utility functions for building robust and maintainable backend implementations. These utilities eliminate code duplication and provide consistent patterns across different backend types.

> **Note**: This documentation is for backend developers and advanced users. For general backend configuration, see [Backend Configuration Guide](backends.md).

## Overview

Backend utilities are organized into the following categories:

1. **Connection & Health Management** - Connection testing, retry logic, health monitoring
2. **Data Management** - Serialization, key normalization, expiration handling
3. **Algorithm Helpers** - Rate limiting calculations, data merging, token bucket operations
4. **Lua Script Helpers** - Redis script management and validation
5. **Configuration & Validation** - Backend setup and validation
6. **Monitoring & Logging** - Operation logging and performance tracking
7. **Memory Management** - Memory usage optimization and cleanup

## Connection & Health Management

### Retry Decorator

The `@with_retry` decorator provides automatic retry functionality with exponential backoff for backend operations:

```python
from django_smart_ratelimit.backends.utils import with_retry

class MyBackend:
    @with_retry(max_retries=3, delay=0.1, exponential_backoff=True)
    def get(self, key):
        # This operation will be retried up to 3 times with exponential backoff
        return self.client.get(key)

    @with_retry(max_retries=2, delay=0.05)
    def set(self, key, value, ttl=None):
        # Different retry configuration for write operations
        return self.client.set(key, value, ttl)
```

**Features:**

- Configurable retry attempts
- Exponential or linear backoff
- Automatic logging of failures
- Exception preservation

### Health Monitoring

```python
from django_smart_ratelimit.backends.utils import test_backend_connection, get_backend_metrics

# Test if backend is healthy
is_healthy, error = test_backend_connection(backend_instance)
if not is_healthy:
    print(f"Backend unhealthy: {error}")

# Get comprehensive metrics
metrics = get_backend_metrics(backend_instance)
print(f"Response time: {metrics['response_time_ms']}ms")
print(f"Backend type: {metrics['backend_type']}")
print(f"Health status: {metrics['is_healthy']}")
```

**Metrics returned:**

- `backend_type` - Class name of the backend
- `is_healthy` - Boolean health status
- `response_time_ms` - Operation response time
- `timestamp` - When metrics were collected
- `error` - Error message if unhealthy
- `backend_stats` - Backend-specific statistics (if available)

## Data Management

### Key Normalization

The `normalize_key()` function handles edge cases and length limits:

```python
from django_smart_ratelimit.backends.utils import normalize_key

# Handle long keys automatically
long_key = "user:12345:very_long_endpoint_name_that_exceeds_backend_limits"
normalized = normalize_key(long_key, prefix="rl", max_length=100)
# Result: "rl:user:12345:very_long_end...:a1b2c3d4e5f6"

# Regular keys with prefix
short_key = normalize_key("user:123", prefix="ratelimit")
# Result: "ratelimit:user:123"
```

**Features:**

- Automatic length limit handling via hashing
- Prefix support for namespacing
- Preserves readability where possible
- Consistent key formatting

### Data Serialization

```python
from django_smart_ratelimit.backends.utils import serialize_data, deserialize_data

# Serialize various data types
token_data = {"tokens": 10, "last_refill": 1234567890}
serialized = serialize_data(token_data)

# Deserialize with type hints
deserialized = deserialize_data(serialized, dict)

# Simple types
number_data = serialize_data(42)           # "42"
string_data = serialize_data("hello")      # "hello"
list_data = serialize_data([1, 2, 3])      # "[1, 2, 3]"
```

**Features:**

- Handles all common Python data types
- JSON serialization for complex objects
- Type validation on deserialization
- Fallback handling for edge cases

### Expiration Management

```python
from django_smart_ratelimit.backends.utils import generate_expiry_timestamp, is_expired

# Generate expiry timestamp
expires_at = generate_expiry_timestamp(ttl_seconds=300)  # 5 minutes from now

# Check if expired
if is_expired(expires_at):
    # Remove expired entry
    del storage[key]

# Clean multiple entries
from django_smart_ratelimit.backends.utils import clean_expired_entries

data = {
    'key1': {'value': 'data1', 'expires_at': 1234567890},
    'key2': {'value': 'data2', 'expires_at': 1234567999}
}
cleaned_data = clean_expired_entries(data, current_time=1234567950)
```

## Algorithm Helpers

### Sliding Window Calculations

```python
from django_smart_ratelimit.backends.utils import calculate_sliding_window_count

# Window data format: [(timestamp, unique_id), ...]
window_data = [(1234567890, 'req1'), (1234567895, 'req2'), (1234567900, 'req3')]
current_count = calculate_sliding_window_count(
    window_data,
    window_size=60,      # 60 second window
    current_time=1234567910
)
# Returns count of requests within the last 60 seconds
```

### Token Bucket Operations

```python
from django_smart_ratelimit.backends.utils import (
    calculate_token_bucket_state,
    format_token_bucket_metadata
)

# Calculate current token state
current_tokens, time_to_full = calculate_token_bucket_state(
    current_tokens=5.0,
    last_refill=1234567890,
    bucket_size=10.0,
    refill_rate=1.0,  # 1 token per second
    current_time=1234567895
)

# Format metadata for responses
metadata = format_token_bucket_metadata(
    tokens_remaining=7.5,
    bucket_size=10.0,
    refill_rate=1.0,
    time_to_refill=2.5
)
# Returns: {
#   'tokens_remaining': 7.5,
#   'bucket_size': 10.0,
#   'refill_rate': 1.0,
#   'time_to_refill': 2.5,
#   'utilization_percent': 25.0
# }
```

### Data Merging

```python
from django_smart_ratelimit.backends.utils import merge_rate_limit_data

data1 = {"requests": 10, "tokens": 5}
data2 = {"requests": 7, "tokens": 3}
merged = merge_rate_limit_data(data1, data2)
# Result: {"requests": 17, "tokens": 8}

# Handles different data types intelligently
list_data1 = {"items": [1, 2], "count": 5}
list_data2 = {"items": [3, 4], "count": 3}
merged_lists = merge_rate_limit_data(list_data1, list_data2)
# Result: {"items": [1, 2, 3, 4], "count": 8}
```

## Configuration & Validation

### Backend Configuration Validation

```python
from django_smart_ratelimit.backends.utils import validate_backend_config

# Redis configuration
redis_config = {
    'host': 'localhost',
    'port': 6379,
    'timeout': 5.0
}

try:
    validated = validate_backend_config(redis_config, 'redis')
    # Returns validated config with defaults filled in
    print(validated)  # {'host': 'localhost', 'port': 6379, 'db': 0, 'timeout': 5.0}
except ValueError as e:
    print(f"Invalid config: {e}")

# Memory configuration
memory_config = {
    'max_entries': 5000,
    'cleanup_interval': 300
}
validated_memory = validate_backend_config(memory_config, 'memory')
```

**Supported backend types:**

- `'redis'` - Redis backend configuration
- `'database'` - Database backend configuration
- `'memory'` - Memory backend configuration

## Monitoring & Logging

### Operation Logging

```python
from django_smart_ratelimit.backends.utils import log_backend_operation, create_operation_timer

def my_backend_operation(self, key):
    with create_operation_timer() as timer:
        try:
            result = self.client.get(key)
            log_backend_operation('get', 'redis', key, timer.elapsed_ms, True)
            return result
        except Exception as e:
            log_backend_operation('get', 'redis', key, timer.elapsed_ms, False, str(e))
            raise
```

**Log output includes:**

- Operation name and backend type
- Key being operated on (truncated if long)
- Duration in milliseconds
- Success/failure status
- Error details if failed

### Performance Timing

```python
from django_smart_ratelimit.backends.utils import create_operation_timer

# Manual timing
with create_operation_timer() as timer:
    # Perform operation
    result = expensive_operation()
    print(f"Operation took {timer.elapsed_ms:.2f}ms")

# In backend methods
def enhanced_get(self, key):
    with create_operation_timer() as timer:
        result = self._internal_get(key)
        # timer.elapsed_ms is automatically calculated
        self._log_metrics('get', timer.elapsed_ms)
        return result
```

## Memory Management

### Memory Usage Estimation

```python
from django_smart_ratelimit.backends.utils import estimate_memory_usage

# Estimate memory usage of data structures
data = {"key1": "value1", "key2": {"nested": "data"}}
memory_bytes = estimate_memory_usage(data)
print(f"Estimated memory: {memory_bytes} bytes")

# Use in backend stats
def get_stats(self):
    return {
        'entries': len(self.storage),
        'memory_bytes': estimate_memory_usage(self.storage),
        'memory_mb': estimate_memory_usage(self.storage) / (1024 * 1024)
    }
```

### Memory Cleanup

```python
from django_smart_ratelimit.backends.utils import cleanup_memory_data

# Large data set
large_data = {f"key_{i}": f"value_{i}" for i in range(10000)}

# Cleanup using different strategies
lru_cleaned = cleanup_memory_data(large_data, max_size=5000, cleanup_strategy='lru')
fifo_cleaned = cleanup_memory_data(large_data, max_size=5000, cleanup_strategy='fifo')
random_cleaned = cleanup_memory_data(large_data, max_size=5000, cleanup_strategy='random')

# For LRU, ensure your data has 'last_access' timestamps
data_with_access = {
    'key1': {'value': 'data1', 'last_access': 1234567890},
    'key2': {'value': 'data2', 'last_access': 1234567895}
}
```

**Cleanup strategies:**

- `'lru'` - Least Recently Used (requires `last_access` field)
- `'fifo'` - First In, First Out (requires `created_at` field)
- `'random'` - Random selection

## Lua Script Helpers

### Script Management

```python
from django_smart_ratelimit.backends.utils import (
    create_lua_script_hash,
    validate_lua_script_args,
    format_lua_args
)

# Create script hash for caching
script = "return redis.call('get', KEYS[1])"
script_hash = create_lua_script_hash(script)

# Validate arguments before execution
args = ['key1', 100, 'timeout']
validate_lua_script_args(args, expected_count=3, script_name='my_script')

# Format arguments for Lua execution
formatted_args = format_lua_args([42, {"key": "value"}, "string"])
# Returns: ['42', '{"key": "value"}', 'string']
```

## Complete Backend Example

Here's a complete example of a backend using all utilities:

```python
from django_smart_ratelimit.backends.base import BaseBackend
from django_smart_ratelimit.backends.utils import *
import threading
import time

class EnhancedMemoryBackend(BaseBackend):
    def __init__(self, **config):
        # Validate configuration
        validated_config = validate_backend_config(config, 'memory')

        self.storage = {}
        self.lock = threading.RLock()
        self.max_entries = validated_config.get('max_entries', 10000)
        self.cleanup_interval = validated_config.get('cleanup_interval', 300)
        self.key_prefix = validated_config.get('key_prefix', 'rl:')

    @with_retry(max_retries=2, delay=0.01)
    def get(self, key: str):
        with create_operation_timer() as timer:
            try:
                normalized_key = normalize_key(key, self.key_prefix)

                with self.lock:
                    if normalized_key in self.storage:
                        entry = self.storage[normalized_key]

                        if 'expires_at' in entry and is_expired(entry['expires_at']):
                            del self.storage[normalized_key]
                            result = None
                        else:
                            # Update access time for LRU
                            entry['last_access'] = time.time()
                            result = deserialize_data(entry['value'])
                    else:
                        result = None

                log_backend_operation('get', 'memory', key, timer.elapsed_ms, True)
                return result

            except Exception as e:
                log_backend_operation('get', 'memory', key, timer.elapsed_ms, False, str(e))
                raise

    def set(self, key: str, value, ttl: int = None):
        with create_operation_timer() as timer:
            try:
                normalized_key = normalize_key(key, self.key_prefix)

                with self.lock:
                    entry = {
                        'value': serialize_data(value),
                        'created_at': time.time(),
                        'last_access': time.time()
                    }

                    if ttl:
                        entry['expires_at'] = generate_expiry_timestamp(ttl)

                    self.storage[normalized_key] = entry
                    self._maybe_cleanup()

                log_backend_operation('set', 'memory', key, timer.elapsed_ms, True)
                return True

            except Exception as e:
                log_backend_operation('set', 'memory', key, timer.elapsed_ms, False, str(e))
                raise

    def _maybe_cleanup(self):
        if len(self.storage) > self.max_entries:
            self.storage = cleanup_memory_data(
                self.storage,
                max_size=int(self.max_entries * 0.8),
                cleanup_strategy='lru'
            )

    def get_stats(self):
        with self.lock:
            return {
                'total_entries': len(self.storage),
                'estimated_memory_bytes': estimate_memory_usage(self.storage),
                'max_entries': self.max_entries
            }
```

## Best Practices

1. **Always use retry decorators** for network operations that may fail transiently
2. **Normalize keys** to handle edge cases and prevent backend-specific issues
3. **Log operations** for monitoring and debugging in production
4. **Validate configurations** at backend initialization
5. **Monitor memory usage** in memory-based backends to prevent resource exhaustion
6. **Use timers** to track performance and identify bottlenecks
7. **Handle expiration properly** to prevent memory leaks and stale data
8. **Test health regularly** to ensure backend availability
9. **Clean up expired data** to maintain optimal performance

## Performance Considerations

- **Key normalization** has minimal overhead (~0.1ms for long keys)
- **Serialization** is optimized for common data types
- **Memory estimation** is approximate but fast
- **Cleanup operations** are designed to be efficient
- **Logging** can be configured to different levels for production
- **Health checks** are lightweight and non-intrusive

## Thread Safety

All utility functions are thread-safe and can be used in multi-threaded environments. Backend implementations should still use appropriate locking mechanisms for their internal state management.

## Error Handling

Utilities provide comprehensive error handling:

- **Configuration validation** catches setup errors early
- **Retry mechanisms** handle transient failures gracefully
- **Logging** captures both successes and failures
- **Health monitoring** detects backend issues proactively
- **Exception preservation** maintains original error context
