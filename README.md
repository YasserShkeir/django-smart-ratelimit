# Django Smart Ratelimit

[![CI](https://github.com/YasserShkeir/django-smart-ratelimit/workflows/CI/badge.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/actions)
[![Coverage](https://img.shields.io/badge/coverage-73%25-yellow.svg)](https://github.com/YasserShkeir/django-smart-ratelimit)
[![PyPI version](https://img.shields.io/pypi/v/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Downloads](https://img.shields.io/pypi/dm/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![License](https://img.shields.io/pypi/l/django-smart-ratelimit.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/LICENSE)

> **The checkmate for abusive traffic.**
>
> A high-performance, stateless rate limiting library for Django that protects your API from abuse, optimized for distributed systems with atomic Redis operations and circuit breaking.

## Sponsors

Support the ongoing development of Django Smart Ratelimit!

<div align="center">
  <!-- Platinum and Gold Sponsors will appear here -->
  <p><em><a href="https://github.com/sponsors/yassershkeir">Become a sponsor</a> to see your logo here!</em></p>
</div>

## Key Features

- **🚀 Stateless & Modern**: Dual-mode support (Sync/Async) without database dependencies.
- **🛡️ Enterprise Reliability**: Built-in **Circuit Breaker** and **Automatic Failover** strategies.
- **⚡ Multiple Algorithms**: Choose between **Token Bucket**, **Sliding Window**, and **Fixed Window**.
- **🔌 Flexible Backends**: Redis (recommended), Async Redis, Memory, or Custom backends.
- **🎯 Precise Control**: Rate limit by IP, User, Header, or any custom callable.

## Quick Start

### Installation

```bash
pip install django-smart-ratelimit[redis]
```

### Usage in 30 Seconds

```python
from django_smart_ratelimit import rate_limit

@rate_limit(key='ip', rate='5/m', block=True)
def login_view(request):
    # If limit is exceeded, this code receives a 429 Too Many Requests
    return authenticate(request)
```

## Documentation

We have moved our detailed documentation to the dedicated `docs/` folder:

| Topic                                         | Description                                          |
| :-------------------------------------------- | :--------------------------------------------------- |
| **[📚 Full Documentation](docs/index.md)**    | Start here for the complete guide.                   |
| **[🚀 Migration Guide](docs/migration.md)**   | Upgrading from `django-ratelimit`? clear steps here. |
| **[🧮 Algorithms](docs/algorithms.md)**       | Deep dive into Token Buckets and Windows.            |
| **[⚙️ Configuration](docs/configuration.md)** | Advanced settings, Backends, and Circuit Breakers.   |
| **[🔍 Design Philosophy](docs/design.md)**    | Why we built this and how it compares to others.     |

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to submit pull requests, report issues, and setup your development environment.

## Community & Support

- **[GitHub Discussions](https://github.com/YasserShkeir/django-smart-ratelimit/discussions)**: Ask questions and share ideas.
- **[Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues)**: Report bugs.
- **[AI Usage Policy](AI_USAGE.md)**: Our transparency commitment.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
