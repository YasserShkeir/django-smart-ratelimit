# Django Smart Ratelimit

[![CI](https://github.com/YasserShkeir/django-smart-ratelimit/workflows/CI/badge.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/actions)
[![PyPI version](https://img.shields.io/pypi/v/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Downloads](https://img.shields.io/pypi/dm/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Python Versions](https://img.shields.io/pypi/pyversions/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Django Versions](https://img.shields.io/badge/django-3.2%20%7C%204.x%20%7C%205.x-blue.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![License](https://img.shields.io/pypi/l/django-smart-ratelimit.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/LICENSE)

A high-performance rate limiting library for Django. Protects your APIs from abuse with atomic Redis operations, multiple algorithms, circuit breaking, and full async support -- optimized for distributed systems.

## Key Features

- **Sync and Async** -- Dual-mode support with native `@ratelimit` and `@aratelimit` decorators
- **Enterprise Reliability** -- Built-in circuit breaker, automatic failover, and fail-open strategies
- **Multiple Algorithms** -- Token bucket, sliding window, fixed window, and leaky bucket
- **Flexible Backends** -- Redis (recommended), async Redis, in-memory, MongoDB, Django ORM (database), or custom backends
- **Precise Control** -- Rate limit by IP, user, header, or any custom callable
- **Shadow Mode** -- Evaluate and log decisions without enforcing them for safe, zero-risk rollouts ([docs](https://django-smart-ratelimit.readthedocs.io/en/latest/decorator/))
- **Cost-Based (Weighted) Limiting** -- Charge expensive requests more of the budget via a per-request `cost` ([docs](https://django-smart-ratelimit.readthedocs.io/en/latest/decorator/))
- **CIDR Allow/Deny Lists** -- IPv4/IPv6 allowlists and denylists from inline CIDRs, files, or URL feeds ([docs](https://django-smart-ratelimit.readthedocs.io/en/latest/configuration/))
- **DRF Throttle Adapter** -- Drop-in `BaseThrottle` classes for Django REST Framework ([docs](https://django-smart-ratelimit.readthedocs.io/en/latest/installation/))
- **Observability** -- Prometheus `/metrics`, OpenTelemetry spans and metrics, and structured JSON logging ([docs](https://django-smart-ratelimit.readthedocs.io/en/latest/installation/))
- **Type-Safe Enums** -- Optional `Algorithm` and `RateLimitKey` enums for autocomplete and typo-proof config
- **Configurable Proxy Trust** -- `RATELIMIT_TRUSTED_PROXIES` for spoof-resistant client IP extraction behind load balancers (new in v3.1)
- **Adaptive Rate Limiting** -- Dynamic limits based on CPU, memory, latency, and custom load indicators

## Quick Start

### Installation

```bash
pip install django-smart-ratelimit[redis]
```

### Basic Usage

```python
from django_smart_ratelimit import ratelimit

@ratelimit(key='ip', rate='5/m', block=True)
def login_view(request):
    return authenticate(request)
```

Keys and algorithms accept plain strings, or the `RateLimitKey` and `Algorithm`
enums if you prefer autocomplete and a typo-proof contract. The two are
interchangeable:

```python
from django_smart_ratelimit import ratelimit
from django_smart_ratelimit.enums import Algorithm, RateLimitKey

@ratelimit(key=RateLimitKey.USER_OR_IP, rate='5/m', algorithm=Algorithm.TOKEN_BUCKET)
def login_view(request):
    return authenticate(request)
```

### Async Support

```python
from django_smart_ratelimit import aratelimit

@aratelimit(key='user', rate='100/h', block=True)
async def api_view(request):
    return await process(request)
```

### Class-Based Views

Apply the decorator to a method with Django's `method_decorator`:

```python
from django.utils.decorators import method_decorator
from django.views import View

from django_smart_ratelimit import ratelimit


class LoginView(View):
    @method_decorator(ratelimit(key='ip', rate='5/m', block=True))
    def post(self, request):
        return authenticate(request)
```

## Configuration

Add to your Django settings:

```python
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {'host': 'localhost', 'port': 6379, 'db': 0}
# Or point at a Redis URL instead of host/port:
# RATELIMIT_REDIS = {'url': 'redis://localhost:6379/0'}

# Optional: enable structured logging
RATELIMIT_LOGGING = {
    'ENABLED': True,
    'FORMAT': 'json',  # "json" or "text"
}

# Optional: enable Prometheus metrics
RATELIMIT_PROMETHEUS = {
    'ENABLED': True,
}
```

If `RATELIMIT_BACKEND` is unset, the in-memory backend is used by default.

## Documentation

Full documentation is hosted on Read the Docs:

| Topic | Description |
| :--- | :--- |
| [Full Documentation](https://django-smart-ratelimit.readthedocs.io/en/latest/) | Start here for the complete guide |
| [Installation](https://django-smart-ratelimit.readthedocs.io/en/latest/installation/) | Optional extras: Redis, MongoDB, DRF, Prometheus, OpenTelemetry |
| [Decorator API](https://django-smart-ratelimit.readthedocs.io/en/latest/decorator/) | Every argument, including shadow mode and cost-based limiting |
| [Migration Guide](https://django-smart-ratelimit.readthedocs.io/en/latest/migration/) | Steps for upgrading from `django-ratelimit` |
| [Algorithms](https://django-smart-ratelimit.readthedocs.io/en/latest/algorithms/) | Deep dive into token bucket, sliding window, and more |
| [Backends](https://django-smart-ratelimit.readthedocs.io/en/latest/backends/) | Redis, async Redis, memory, MongoDB, and the Django ORM database backend |
| [Configuration](https://django-smart-ratelimit.readthedocs.io/en/latest/configuration/) | Advanced settings, CIDR lists, proxy trust, and circuit breakers |
| [Deployment](https://django-smart-ratelimit.readthedocs.io/en/latest/deployment/) | Running in production behind proxies and load balancers |
| [Design Philosophy](https://django-smart-ratelimit.readthedocs.io/en/latest/design/) | Architecture decisions and comparison with alternatives |

## Compatibility

| | Supported Versions |
| :--- | :--- |
| Python | 3.9, 3.10, 3.11, 3.12, 3.13 |
| Django | 3.2, 4.0, 4.1, 4.2, 5.0, 5.1 |

## Contributing

Contributions are welcome. Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to submit pull requests, report issues, and set up your development environment.

## Community and Support

- [GitHub Discussions](https://github.com/YasserShkeir/django-smart-ratelimit/discussions) -- Ask questions and share ideas
- [Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues) -- Report bugs
- [Changelog](CHANGELOG.md) -- Release history

## Sponsors

Support the ongoing development of Django Smart Ratelimit:

[![Sponsor](https://img.shields.io/badge/Sponsor-Support%20Development-blue.svg)](https://www.yasser-shkeir.com/donate)

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
