# Circuit Breaker Pattern

The circuit breaker pattern protects your Django application from cascading failures by detecting when backend services are failing and temporarily stopping requests to give them time to recover.

> **Note**: Circuit breaker works with all [rate limiting algorithms](algorithms.md) (fixed_window, sliding_window, token_bucket) and all [backends](backends.md) (Redis, Database, Memory, Multi).

## Overview

Think of a circuit breaker like an electrical circuit breaker in your house - it "opens" the circuit when there's too much load, protecting the system from damage.

### States & Algorithm

The circuit breaker operates in three states with automatic transitions:

```
🟢 CLOSED ──(failures ≥ threshold)──> 🔴 OPEN ──(timeout)──> 🟡 HALF_OPEN
   ↑                                                               │
   └──(success)──────────────────────────────────────────────────┘
```

1. **🟢 CLOSED (Normal)**: All requests pass through to the backend
2. **🔴 OPEN (Protecting)**: Requests fail fast without hitting the backend
3. **🟡 HALF_OPEN (Testing)**: Limited requests test if the backend has recovered

### Exponential Backoff

When failures persist, the circuit breaker uses exponential backoff:

- First failure: Wait 60 seconds
- Second failure: Wait 120 seconds
- Third failure: Wait 240 seconds
- Maximum: 300 seconds (configurable)

## Configuration

### Global Configuration

```python
# settings.py
RATELIMIT_CIRCUIT_BREAKER = {
    'failure_threshold': 5,                    # Open after 5 consecutive failures
    'recovery_timeout': 60,                    # Wait 60 seconds before testing
    'reset_timeout': 300,                      # Reset after 5 minutes of success
    'half_open_max_calls': 1,                  # Test with 1 call in half-open
    'exponential_backoff_multiplier': 2.0,     # Double timeout on repeated failures
    'exponential_backoff_max': 300,            # Maximum backoff time
}
```

### Backend-Specific Configuration

```python
from django_smart_ratelimit.backends import MemoryBackend, RedisBackend

# Custom circuit breaker for specific backend
custom_config = {
    'failure_threshold': 3,
    'recovery_timeout': 30,
}

backend = MemoryBackend(enable_circuit_breaker=True, circuit_breaker_config=custom_config)

# Disable circuit breaker for a backend
backend = RedisBackend(enable_circuit_breaker=False)
```

## Usage Patterns

### Automatic Integration

Circuit breaker works automatically with all rate limiting operations:

```python
@rate_limit(key='user', rate='100/h')
def api_endpoint(request):
    # Circuit breaker automatically protects the backend
    return JsonResponse({'data': 'response'})
```

### Manual Usage

```python
from django_smart_ratelimit.circuit_breaker import circuit_breaker, CircuitBreakerError

@circuit_breaker(name="external_api", failure_threshold=3)
def call_external_api():
    import requests
    response = requests.get("https://api.example.com/data")
    return response.json()

# Handle circuit breaker errors
try:
    data = call_external_api()
except CircuitBreakerError:
    data = get_cached_data()  # Graceful degradation
```

### Checking Status & Manual Control

```python
from django_smart_ratelimit import get_backend

backend = get_backend()

# Get health status including circuit breaker info
health = backend.get_backend_health_status()
print(f"Circuit breaker enabled: {health['circuit_breaker_enabled']}")

# Get detailed circuit breaker status
if health['circuit_breaker_enabled']:
    cb_status = backend.get_circuit_breaker_status()
    print(f"State: {cb_status['state']}")
    print(f"Failure count: {cb_status['failure_count']}")
    print(f"Failure threshold: {cb_status['failure_threshold']}")

# Manually reset a circuit breaker
backend.reset_circuit_breaker()

# Check if circuit breaker is enabled for this backend
if backend.is_circuit_breaker_enabled():
    print("Circuit breaker is active")
```

## Error Handling & Monitoring

### CircuitBreakerError

```python
from django_smart_ratelimit.circuit_breaker import CircuitBreakerError

try:
    backend.incr("user:123", 60)
except CircuitBreakerError:
    # Circuit breaker is open - backend is failing
    return handle_graceful_degradation()
```

### Graceful Degradation Patterns

```python
@rate_limit(key='user', rate='100/h')
def api_endpoint(request):
    try:
        return process_request(request)
    except CircuitBreakerError:
        return JsonResponse({
            'error': 'Service temporarily unavailable',
            'retry_after': 60
        }, status=503)

def get_rate_limit_count_safely(key):
    """Get count with circuit breaker protection."""
    try:
        return backend.get_count(key)
    except CircuitBreakerError:
        return 0  # Assume no rate limiting when backend is down
```

### Monitoring & Health Checks

```python
from django_smart_ratelimit.circuit_breaker import circuit_breaker_registry

# Get status of all circuit breakers
all_status = circuit_breaker_registry.get_all_status()
for name, status in all_status.items():
    print(f"{name}: {status['state']} ({status['failure_count']} failures)")

# Health check endpoint
def circuit_breaker_health():
    status = circuit_breaker_registry.get_all_status()
    failing = sum(1 for s in status.values() if s['state'] == 'open')
    return {'total': len(status), 'failing': failing, 'healthy': failing == 0}
```

## Configuration Examples

### Environment-Specific Settings

```python
# For high-traffic production APIs
PRODUCTION_CONFIG = {
    'failure_threshold': 10,     # More tolerance for occasional failures
    'recovery_timeout': 30,      # Quick recovery testing
    'exponential_backoff_max': 180,  # Shorter max backoff
}

# For critical external services
CRITICAL_SERVICE_CONFIG = {
    'failure_threshold': 3,      # Fail fast
    'recovery_timeout': 120,     # Give more time to recover
    'exponential_backoff_max': 600,  # Longer backoff for stability
}

# Development/testing
DEVELOPMENT_CONFIG = {
    'failure_threshold': 1,      # Immediate testing
    'recovery_timeout': 5,       # Quick recovery for development
}
```

### Multi-Backend with Circuit Breakers

```python
# settings.py
RATELIMIT_BACKENDS = [
    {
        'type': 'django_smart_ratelimit.backends.redis_backend.RedisBackend',
        'name': 'primary_redis',
        'options': {
            'enable_circuit_breaker': True,
            'circuit_breaker_config': {'failure_threshold': 5}
        }
    },
    {
        'type': 'django_smart_ratelimit.backends.memory.MemoryBackend',
        'name': 'fallback_memory',
        'options': {
            'enable_circuit_breaker': True,
            'circuit_breaker_config': {'failure_threshold': 10}
        }
    }
]
```

## Testing & Troubleshooting

### Testing Circuit Breaker Behavior

```python
import pytest
from django_smart_ratelimit.circuit_breaker import circuit_breaker_registry

@pytest.fixture(autouse=True)
def reset_circuit_breakers():
    """Reset circuit breakers between tests."""
    circuit_breaker_registry.reset_all()
    circuit_breaker_registry._breakers.clear()
    yield
    circuit_breaker_registry.reset_all()
    circuit_breaker_registry._breakers.clear()

def test_circuit_breaker_opens_on_failures():
    backend = MemoryBackend(enable_circuit_breaker=True)

    # Simulate failures to open circuit breaker
    for _ in range(5):  # Assuming failure_threshold=5
        with pytest.raises(Exception):
            backend.incr("test", 60)  # This should fail

    # Circuit breaker should now be open
    with pytest.raises(CircuitBreakerError):
        backend.incr("test", 60)
```

### Common Issues

#### Circuit Breaker Stuck Open

```python
# Check the current status
status = backend.get_circuit_breaker_status()
print(f"Next attempt time: {status['next_attempt_time']}")

# Manually reset if needed
backend.reset_circuit_breaker()
```

#### Too Sensitive (Opens Too Often)

```python
# Increase the failure threshold
config = {'failure_threshold': 10}  # Instead of 5
backend = MemoryBackend(circuit_breaker_config=config)
```

#### Too Slow to Recover

```python
# Decrease the recovery timeout
config = {'recovery_timeout': 30}  # Instead of 60
backend = MemoryBackend(circuit_breaker_config=config)
```

## See Also

- [Backend Documentation](backends.md) - Backend-specific circuit breaker configuration
- [Multi-Backend Guide](backends.md#multi-backend) - Using circuit breakers with failover
- [Utilities Documentation](utilities.md) - General utility functions and patterns
