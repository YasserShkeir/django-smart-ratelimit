# Django Smart Ratelimit

[![CI](https://github.com/YasserShkeir/django-smart-ratelimit/workflows/CI/badge.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/actions)
[![PyPI version](https://img.shields.io/pypi/v/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![PyPI status](https://img.shields.io/pypi/status/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Django versions](https://img.shields.io/badge/Django-3.2%20%7C%204.0%20%7C%204.1%20%7C%204.2%20%7C%205.0%20%7C%205.1-blue.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Downloads](https://img.shields.io/pypi/dm/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![License](https://img.shields.io/pypi/l/django-smart-ratelimit.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/LICENSE)
[![GitHub Discussions](https://img.shields.io/github/discussions/YasserShkeir/django-smart-ratelimit)](https://github.com/YasserShkeir/django-smart-ratelimit/discussions)

A comprehensive rate limiting library for Django applications with multiple algorithms, backends, and flexible configuration options.

## Why Rate Limiting Matters

Rate limiting helps protect your Django applications from:

- **Resource exhaustion** from excessive requests
- **Brute force attacks** on authentication endpoints
- **API abuse** and scraping attempts
- **Unintentional traffic spikes** that can overwhelm your server

## Library Features

- **Multiple algorithms**: Token bucket, sliding window, and fixed window
- **Backend flexibility**: Redis, Database, Memory, and Multi-Backend support
- **Circuit breaker protection**: Automatic failure detection and recovery for backends
- **Atomic operations**: Redis Lua scripts prevent race conditions
- **Automatic failover**: Graceful degradation between backends
- **Type safety**: Full mypy compatibility with strict type checking
- **Framework integration**: Native Django and Django REST Framework support
- **Monitoring tools**: Health checks and cleanup management commands
- **Standard headers**: X-RateLimit-\* headers for client information

## Quick Start

### Installation

```bash
pip install django-smart-ratelimit[redis]
```

### Basic Usage

```python
from django_smart_ratelimit import rate_limit

# IP-based rate limiting
@rate_limit(key='ip', rate='100/h')
def api_endpoint(request):
    return JsonResponse({'data': 'protected'})

# User-based rate limiting
@rate_limit(key='user', rate='50/h')
def user_dashboard(request):
    return JsonResponse({'user_data': '...'})
```

### Authentication Protection

```python
@rate_limit(key='ip', rate='5/m', block=True)
def login_view(request):
    return authenticate_user(request)
```

### Django REST Framework

```python
from rest_framework import viewsets
from django_smart_ratelimit import rate_limit

class APIViewSet(viewsets.ViewSet):
    @rate_limit(key='ip', rate='100/h')
    def list(self, request):
        return Response({'data': 'list'})
```

### Middleware Configuration

```python
# settings.py
MIDDLEWARE = ['django_smart_ratelimit.middleware.RateLimitMiddleware']
RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '1000/h',
    'RATE_LIMITS': {
        '/api/auth/': '10/m',
        '/api/': '500/h',
    }
}
```

## Algorithm Comparison

| Algorithm          | Characteristics              | Best For                   |
| ------------------ | ---------------------------- | -------------------------- |
| **token_bucket**   | Allows traffic bursts        | APIs with variable load    |
| **sliding_window** | Smooth request distribution  | Consistent traffic control |
| **fixed_window**   | Simple, predictable behavior | Basic rate limiting needs  |

### Token Bucket Algorithm

The token bucket algorithm allows for burst traffic handling:

```python
@rate_limit(
    key='user',
    rate='100/h',  # Base rate
    algorithm='token_bucket',
    algorithm_config={
        'bucket_size': 200,  # Allow bursts up to 200 requests
        'refill_rate': 2.0,  # Refill tokens at 2 per second
    }
)
def api_with_bursts(request):
    return JsonResponse({'data': 'handled'})
```

**Common use cases:**

- Mobile app synchronization after offline periods
- Batch file processing
- API retry mechanisms

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

### Database

```python
RATELIMIT_BACKEND = 'database'
# Uses your default Django database
```

### Multi-Backend with Failover

```python
RATELIMIT_BACKENDS = [
    {
        'name': 'primary_redis',
        'backend': 'redis',
        'config': {'host': 'redis-primary.example.com'}
    },
    {
        'name': 'fallback_db',
        'backend': 'database',
        'config': {}
    }
]
```

## Response Headers

The library adds standard rate limit headers to responses:

```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 99
X-RateLimit-Reset: 1642678800
```

## Monitoring and Management

### Health Checks

```bash
# Check backend health
python manage.py ratelimit_health

# Detailed status
python manage.py ratelimit_health --verbose
```

### Cleanup (Database Backend)

```bash
# Clean expired entries
python manage.py cleanup_ratelimit

# Preview cleanup
python manage.py cleanup_ratelimit --dry-run
```

## Library Features

- **Multiple algorithms**: Token bucket, sliding window, and fixed window
- **Backend flexibility**: Redis, Database, Memory, and Multi-Backend support
- **Atomic operations**: Redis Lua scripts prevent race conditions
- **Automatic failover**: Graceful degradation between backends
- **Type safety**: Full mypy compatibility with strict type checking
- **Framework integration**: Native Django and Django REST Framework support

## Examples

The library includes comprehensive examples for various use cases:

- **[Basic Rate Limiting](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/examples/basic_rate_limiting.py)** - IP and user-based limiting
- **[Custom Key Functions](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/examples/custom_key_functions.py)** - Geographic and device-based keys
- **[JWT Rate Limiting](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/examples/jwt_rate_limiting.py)** - Token-based limiting
- **[DRF Integration](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/examples/drf_integration/)** - Django REST Framework examples
- **[Multi-tenant Applications](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/examples/tenant_rate_limiting.py)** - Tenant-aware rate limiting

## Configuration Options

### Decorator Parameters

```python
@rate_limit(
    key='user',                    # Key function or string
    rate='100/h',                  # Rate limit (requests/period)
    algorithm='token_bucket',      # Algorithm choice
    algorithm_config={},           # Algorithm-specific config
    backend='redis',               # Backend override
    block=True,                    # Block vs. continue on limit
    skip_if=lambda req: req.user.is_staff,  # Skip condition
)
```

## Testing

```bash
# Run tests
python -m pytest

# Run with coverage
python -m pytest --cov=django_smart_ratelimit
```

### Decorator Examples

```python
from django_smart_ratelimit import rate_limit

# Basic IP-based limiting
@rate_limit(key='ip', rate='10/m')
def public_api(request):
    return JsonResponse({'message': 'Hello World'})

# User-based limiting (automatically falls back to IP for anonymous users)
@rate_limit(key='user', rate='100/h')
def user_dashboard(request):
    return JsonResponse({'user_data': '...'})

# Custom key function for more control
@rate_limit(key=lambda req: f"user:{req.user.id}" if req.user.is_authenticated else f"ip:{req.META.get('REMOTE_ADDR')}", rate='50/h')
def flexible_api(request):
    return JsonResponse({'data': '...'})

# Block when limit exceeded (default is to continue)
@rate_limit(key='ip', rate='5/m', block=True)
def strict_api(request):
    return JsonResponse({'sensitive': 'data'})

# Skip rate limiting for staff users
@rate_limit(key='ip', rate='10/m', skip_if=lambda req: req.user.is_staff)
def staff_friendly_api(request):
    return JsonResponse({'data': 'staff can access unlimited'})

# Use sliding window algorithm
@rate_limit(key='user', rate='100/h', algorithm='sliding_window')
def smooth_api(request):
    return JsonResponse({'algorithm': 'sliding_window'})

# Use fixed window algorithm
@rate_limit(key='ip', rate='20/m', algorithm='fixed_window')
def burst_api(request):
    return JsonResponse({'algorithm': 'fixed_window'})

# Use token bucket algorithm (NEW!)
@rate_limit(
    key='api_key',
    rate='100/m',  # Base rate: 100 requests per minute
    algorithm='token_bucket',
    algorithm_config={
        'bucket_size': 200,  # Allow bursts up to 200 requests
        'refill_rate': 2.0,  # Refill at 2 tokens per second
    }
)
def api_with_bursts(request):
    return JsonResponse({'algorithm': 'token_bucket', 'burst_allowed': True})
```

## Circuit Breaker Protection

Automatic failure detection and recovery for backend operations to ensure system reliability:

### Configuration

```python
# settings.py
RATELIMIT_CIRCUIT_BREAKER = {
    'failure_threshold': 5,        # Open circuit after 5 failures
    'recovery_timeout': 60,        # Wait 60 seconds before testing recovery
    'reset_timeout': 300,          # Reset after 5 minutes of success
    'half_open_max_calls': 1,      # Test with 1 call in half-open state
}
```

### Backend-Specific Circuit Breakers

```python
from django_smart_ratelimit.backends import MemoryBackend

# Enable circuit breaker (default: enabled)
backend = MemoryBackend(enable_circuit_breaker=True)

# Custom configuration
custom_config = {'failure_threshold': 3, 'recovery_timeout': 30}
backend = MemoryBackend(
    enable_circuit_breaker=True,
    circuit_breaker_config=custom_config
)

# Check circuit breaker status
status = backend.get_backend_health_status()
print(f"Circuit breaker enabled: {status['circuit_breaker_enabled']}")
print(f"Current state: {status['circuit_breaker']['state']}")
```

### Circuit Breaker States

- **🟢 CLOSED**: Normal operation, requests pass through
- **🔴 OPEN**: Too many failures, requests fail fast (no backend calls)
- **🟡 HALF_OPEN**: Testing recovery with limited requests

## Community & Support

- **[GitHub Discussions](https://github.com/YasserShkeir/django-smart-ratelimit/discussions)** - Community support and questions
- **[Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues)** - Bug reports and feature requests
- **[Contributing](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/CONTRIBUTING.md)** - Contributing guidelines
- **[AI Usage Policy](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/AI_USAGE.md)** - Transparency about AI assistance in development

## 💖 Support the Project

If you find this project helpful and want to support its development, you can make a donation to help maintain and improve this open-source library:

### Cryptocurrency Donations

- **USDT (Ethereum Network)**: `0xBD90e5df7389295AE6fbaB5FEf6817f22A8123eF`
- **Solana (SOL)**: `WzQHS7hzBcznkYoR7TkMH1DRo3WLYQdWCNBuy6ZfY3h`
- **Ripple (XRP)**: `rE8CM2sv4gBEDhek2Ajm2vMmqMXdPV34jC`

Your support helps maintain and improve this project for the Django community! 🙏

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/LICENSE) file for details.

---

**[📚 Documentation](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/docs/)** • **[💡 Examples](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/examples/)** • **[🤝 Contributing](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/CONTRIBUTING.md)** • **[💬 Discussions](https://github.com/YasserShkeir/django-smart-ratelimit/discussions)** • **[🤖 AI Usage](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/AI_USAGE.md)**
