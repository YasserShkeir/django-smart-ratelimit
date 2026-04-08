# Django Smart Ratelimit

[![CI](https://github.com/YasserShkeir/django-smart-ratelimit/workflows/CI/badge.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/actions)
[![PyPI version](https://img.shields.io/pypi/v/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Downloads](https://img.shields.io/pypi/dm/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Python Versions](https://img.shields.io/pypi/pyversions/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Django Versions](https://img.shields.io/badge/django-3.2%20%7C%204.x%20%7C%205.x-blue.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![License](https://img.shields.io/pypi/l/django-smart-ratelimit.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/LICENSE)

A high-performance, stateless rate limiting library for Django. Protects your APIs from abuse with atomic Redis operations, multiple algorithms, circuit breaking, and full async support -- optimized for distributed systems.

## Key Features

- **Stateless and Modern** -- Dual-mode support (sync and async) with no database dependencies
- **Enterprise Reliability** -- Built-in circuit breaker, automatic failover, and fail-open strategies
- **Multiple Algorithms** -- Token bucket, sliding window, fixed window, and leaky bucket
- **Flexible Backends** -- Redis (recommended), async Redis, in-memory, MongoDB, or custom backends
- **Precise Control** -- Rate limit by IP, user, header, or any custom callable
- **Prometheus Metrics** -- Built-in `/metrics` endpoint for monitoring
- **Structured JSON Logging** -- ELK/Datadog/Splunk-compatible structured log output
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

### Async Support

```python
from django_smart_ratelimit import aratelimit

@aratelimit(key='user', rate='100/h', block=True)
async def api_view(request):
    return await process(request)
```

### Class-Based Views

```python
from django_smart_ratelimit import RateLimitMixin

class LoginView(RateLimitMixin, View):
    ratelimit_key = 'ip'
    ratelimit_rate = '5/m'
    ratelimit_block = True
```

## Configuration

Add to your Django settings:

```python
RATELIMIT_DEFAULT_BACKEND = 'redis'
RATELIMIT_REDIS_URL = 'redis://localhost:6379/0'

# Optional: enable structured logging
RATELIMIT_LOGGING = {
    'ENABLED': True,
    'LEVEL': 'INFO',
    'FORMAT': 'json',
}

# Optional: enable Prometheus metrics
RATELIMIT_PROMETHEUS = {
    'ENABLED': True,
}
```

## Documentation

Detailed documentation is available in the `docs/` folder:

| Topic | Description |
| :--- | :--- |
| [Full Documentation](docs/index.md) | Start here for the complete guide |
| [Migration Guide](docs/migration.md) | Steps for upgrading from `django-ratelimit` |
| [Algorithms](docs/algorithms.md) | Deep dive into token bucket, sliding window, and more |
| [Configuration](docs/configuration.md) | Advanced settings, backends, and circuit breakers |
| [Design Philosophy](docs/design.md) | Architecture decisions and comparison with alternatives |

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
