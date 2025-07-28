# Django Smart Ratelimit - AI Coding Instructions

## Project Architecture

This is a Django rate limiting library with a **plugin-based backend architecture** and **algorithm abstraction layer**.

### Core Components

- **`@rate_limit` decorator** (`decorator.py`) - Main entry point for rate limiting
- **Backend abstraction** (`backends/`) - Pluggable storage systems (Redis, DB, Memory, MongoDB, Multi)
- **Algorithm layer** (`algorithms/`) - Rate limiting algorithms (token bucket, sliding window, fixed window)
- **Middleware** (`middleware.py`) - Global rate limiting for Django requests
- **Utilities** (`utils.py`, `key_functions.py`, `auth_utils.py`) - Key generation and auth helpers

### Backend Pattern

All backends inherit from `BaseBackend` and implement:

- `incr(key, period)` - Atomic increment with TTL
- `token_bucket_check()` - Algorithm-specific operations
- `get_count()`, `get_reset_time()`, `reset()` - State management

**Multi-backend** (`backends/multi.py`) provides automatic failover between backends with health checks.

### Algorithm Integration

Algorithms like `TokenBucketAlgorithm` work with any backend through the `is_allowed()` method, using backend-specific implementations for atomicity (Redis Lua scripts, database transactions).

## Development Workflows

### Testing Commands

```bash
# Full test suite (340+ tests)
make test                    # Run with coverage
make test-quick             # Fast run without HTML coverage
./run_with_venv.sh pytest  # Direct pytest execution
```

### Code Quality

```bash
make lint                   # Pre-commit hooks (black, isort, mypy, bandit)
make format                 # Auto-format code
```

### Virtual Environment

**CRITICAL**: All terminal commands MUST use `./run_with_venv.sh` prefix with `python3`:

```bash
./run_with_venv.sh python3 -m pytest    # Correct
./run_with_venv.sh python3 manage.py    # Correct
python pytest                           # WRONG - will fail
```

The script auto-creates/activates venv and ensures Python 3.9+ compatibility.

## Project-Specific Patterns

### Rate Limit Key Generation

```python
# Use generate_key() for consistent key formatting
limit_key = generate_key(key, request, *args, **kwargs)
# Supports: strings, callables, lambda functions
```

### Backend Configuration

- Single backend: `RATELIMIT_BACKEND = 'redis'`
- Multi-backend failover: `RATELIMIT_BACKENDS = [...]` (automatically uses `multi` backend)
- Backend instances are **cached globally** in `_backend_instances`

### Algorithm-Specific Headers

- Standard: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- Token bucket: Additional `X-RateLimit-Bucket-*` headers for burst info
- Use `add_rate_limit_headers()` or `add_token_bucket_headers()`

### Error Handling Philosophy

- **Graceful degradation**: Rate limiting failures shouldn't break requests
- **Fallback strategies**: Multi-backend automatically switches on failure
- **Circuit breaker pattern**: Planned for backend health management (see FEATURES_ROADMAP.md)

## Critical Integration Points

### Django Integration

- **Middleware**: Applies rate limiting before view execution
- **Decorator**: Function-level rate limiting with view introspection
- **Management commands**: `cleanup_ratelimit`, `ratelimit_health`

### External Dependencies

- **Redis**: Primary backend, uses Lua scripts for atomicity
- **MongoDB**: Alternative NoSQL backend with TTL collections
- **PyJWT**: Optional JWT-based rate limiting support

### Cross-Component Communication

- Backend factory (`backends/factory.py`) handles dynamic backend loading
- Configuration validation (`utils.py`) ensures algorithm compatibility
- Health checks communicate backend status across the system

## Testing Patterns

### Backend Testing

Each backend has standardized tests for:

- Basic increment operations
- TTL/expiration behavior
- Thread safety (memory backend)
- Connection handling
- Algorithm-specific methods

### Algorithm Testing

- Burst behavior validation
- Time-based scenarios
- Backend integration tests
- Performance benchmarks

### Fixture Pattern

```python
@pytest.fixture
def redis_backend():
    # Mock Redis client for consistent testing
    with patch("django_smart_ratelimit.backends.redis_backend.redis"):
        # ... setup mocked Redis
```

## Code Conventions

### DRY (Don't Repeat Yourself) Principles

- **Utility Functions**: Use existing utilities in `utils.py`, `key_functions.py`, `auth_utils.py`
- **Backend Patterns**: Inherit from `BaseBackend`, don't duplicate backend logic
- **Key Generation**: Always use `generate_key()` - never custom key formatting
- **Header Management**: Use `add_rate_limit_headers()` functions, not manual header setting
- **Configuration**: Leverage `validate_rate_config()` for all algorithm validation

### Performance Requirements

- **Atomic Operations**: Use Redis Lua scripts or database transactions for consistency
- **Connection Pooling**: Leverage Django's database pools and Redis connection pools
- **Caching**: Backend instances cached in `_backend_instances` - don't create duplicates
- **Lazy Loading**: Import optional dependencies conditionally to avoid startup overhead
- **Memory Management**: Implement TTL and cleanup mechanisms for all backends

### Type Safety

- Full mypy compatibility with strict checking
- Type hints required for all new code
- Generic types for backend/algorithm interfaces

### Import Organization

- Relative imports within package
- Conditional imports for optional dependencies (pymongo, PyJWT)
- Lazy loading of backends to avoid import errors

### Configuration Validation

Use `validate_rate_config()` early in decorators to catch invalid algorithm/rate combinations before runtime.

## Development Priorities (from FEATURES_ROADMAP.md)

**High Priority**: Circuit breaker pattern, health checks, configuration validation, graceful degradation
**Active**: Token bucket algorithm (completed), MongoDB backend (completed)

## Required File Updates for New Features

When implementing new features, **ALWAYS** update these files:

### Backend Implementation

1. **`backends/base.py`** - Add new abstract methods if needed
2. **`backends/your_backend.py`** - Implement the new backend
3. **`backends/__init__.py`** - Add backend to factory logic
4. **`tests/test_your_backend.py`** - Comprehensive test suite
5. **`FEATURES_ROADMAP.md`** - Mark feature as completed with date

### Algorithm Implementation

1. **`algorithms/base.py`** - Define algorithm interface
2. **`algorithms/your_algorithm.py`** - Implement algorithm logic
3. **`algorithms/__init__.py`** - Export new algorithm
4. **`decorator.py`** - Add algorithm support in decorator
5. **`tests/test_your_algorithm.py`** - Algorithm-specific tests

### Documentation Updates

1. **`README.md`** - Add usage examples and feature list
2. **`docs/`** - Create detailed documentation
3. **`examples/`** - Add practical examples
4. **`pyproject.toml`** - Update dependencies if needed

### Performance Testing

Always add performance tests in `tests/` for:

- Concurrent request handling
- Memory usage patterns
- Backend switching overhead
- Algorithm efficiency

When implementing new features, follow the established patterns:

1. Create backend interface in `base.py`
2. Implement algorithm in `algorithms/`
3. Add comprehensive tests following existing patterns
4. Update feature roadmap completion status
