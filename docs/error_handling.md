# Error Handling & Security

## Error Handling

Django Smart Ratelimit provides robust error handling to ensure your application remains stable even if the rate limiting backend fails.

### Handling Strategy

- **Fail-Closed (Default)**: If the backend fails, requests are denied to protect your application.
- **Fail-Open**: Configure `RATELIMIT_FAIL_OPEN = True` to allow requests when the backend is unavailable.
- **Circuit Breaker**: Automatically detects backend failures and temporarily disables rate limiting to prevent cascading failures.
- **Custom Handlers**: Define custom exception handlers to return specific responses (e.g., JSON) when limits are exceeded.

## Security: Fail-Open Mechanism

The library supports a "fail-open" security model. This means that if the rate limiting backend becomes unavailable (e.g., database connection failure, deadlock), the system can be configured to:

1.  **Log the error**: The failure is logged with full traceback for debugging.
2.  **Allow the request**: The request is allowed to proceed to avoid blocking legitimate traffic during infrastructure issues.
3.  **Degrade gracefully**: The application continues to function, albeit without rate limiting protection for that specific request.

This behavior is controlled via the `RATELIMIT_FAIL_OPEN` setting (default: `False`). Set it to `True` to enable fail-open behavior.

```python
# settings.py
RATELIMIT_FAIL_OPEN = True  # allow requests when the backend is unavailable
```

## Custom Exception Handler

When a backend raises an error and fail-open is disabled, the request is routed
through an exception handler. By default this logs the error (with traceback)
and returns a 429 response. Override it with `RATELIMIT_EXCEPTION_HANDLER`, set
to the dotted import path of a callable.

The handler receives the request and the raised exception and must return an
`HttpResponse`:

```python
# myapp/handlers.py
from django.http import JsonResponse


def ratelimit_exception_handler(request, exception):
    return JsonResponse(
        {"error": "rate limiting temporarily unavailable"},
        status=503,
    )
```

```python
# settings.py
RATELIMIT_EXCEPTION_HANDLER = "myapp.handlers.ratelimit_exception_handler"
```

A separate `RATELIMIT_RESPONSE_HANDLER` (also a dotted path, or a template name)
customizes the response returned when a request is actually rate limited, as
opposed to when the backend errors.

## Circuit Breaker Protection

Automatic failure detection and recovery for backend operations to ensure system reliability.

### Circuit Breaker States

- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Too many failures, requests fail fast (no backend calls)
- **HALF_OPEN**: Testing recovery with limited requests

### Configuration

Tune the circuit breaker with `RATELIMIT_CIRCUIT_BREAKER` (a dict). The keys
below map to `CircuitBreakerConfig`; values shown are the defaults:

```python
# settings.py
RATELIMIT_CIRCUIT_BREAKER = {
    "failure_threshold": 5,          # failures before opening the circuit
    "recovery_timeout": 60,          # seconds before attempting HALF_OPEN
    "reset_timeout": 300,            # seconds of success before clearing failures
    "half_open_max_calls": 1,        # probe calls allowed in HALF_OPEN
    "exponential_backoff_multiplier": 2.0,
    "exponential_backoff_max": 300,  # cap on backoff (seconds)
}
```

State storage is selected separately:

```python
# settings.py
RATELIMIT_CIRCUIT_BREAKER_STORAGE = "memory"        # "memory" (default) or "redis"
RATELIMIT_CIRCUIT_BREAKER_REDIS_URL = "redis://localhost:6379/0"
```

When the storage is set to `"redis"` but no usable Redis URL/client is
available, the breaker logs a warning and falls back to in-memory state.

### Known Limitations

- **Circuit Breaker Persistence**: With the default `"memory"` storage the circuit breaker state (failure counts, open/closed status) is reset if the application process restarts, and in a multi-worker environment (e.g., Gunicorn/uWSGI) each worker maintains its own independent state. Set `RATELIMIT_CIRCUIT_BREAKER_STORAGE = "redis"` to share state across processes.

## Multi-Backend Fallback

When you configure several backends, the multi-backend dispatcher decides how to
route around an unhealthy one. The strategy is set with
`RATELIMIT_MULTI_BACKEND_STRATEGY`:

- `"first_healthy"` (default): try backends in order, using the first healthy one.
- `"round_robin"`: rotate across healthy backends.

```python
# settings.py
RATELIMIT_MULTI_BACKEND_STRATEGY = "first_healthy"
```

## Choosing an Algorithm Safely

Error-handling configuration is independent of the rate limiting algorithm, but
the `algorithm` choice is accepted as a raw string or, equivalently, the
type-safe `Algorithm` enum. Using the enum avoids typos that would otherwise
surface only at request time:

```python
from django_smart_ratelimit.enums import Algorithm

# settings.py
RATELIMIT_ALGORITHM = Algorithm.SLIDING_WINDOW  # same as "sliding_window"
```

`Algorithm` is a `StrEnum`, so its members are interchangeable with their string
values (`Algorithm.SLIDING_WINDOW`, `Algorithm.FIXED_WINDOW`,
`Algorithm.TOKEN_BUCKET`, `Algorithm.LEAKY_BUCKET`) anywhere an algorithm string
is accepted.
