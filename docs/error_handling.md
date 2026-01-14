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

## Circuit Breaker Protection

Automatic failure detection and recovery for backend operations to ensure system reliability.

### Circuit Breaker States

- **🟢 CLOSED**: Normal operation, requests pass through
- **🔴 OPEN**: Too many failures, requests fail fast (no backend calls)
- **🟡 HALF_OPEN**: Testing recovery with limited requests

### Known Limitations

- **Circuit Breaker Persistence**: The circuit breaker state is currently stored in memory for all backends. This means the state (failure counts, open/closed status) is reset if the application process restarts. In a multi-worker environment (e.g., Gunicorn/uWSGI), each worker maintains its own independent circuit breaker state.
