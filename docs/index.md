# Django Smart Ratelimit Documentation

## 📚 Documentation Index

### Getting Started

- **[README](../README.md)** - Quick setup and basic usage
- **[Installation & Configuration](installation.md)** - Detailed setup guide

### Core Concepts

- **[Rate Limiting Algorithms](algorithms.md)** - Fixed window, sliding window, and token bucket algorithms
- **[Backend Configuration](backends.md)** - Redis, Database, Memory, and Multi-Backend setup
- **[Circuit Breaker Pattern](circuit_breaker.md)** - Automatic failure detection and recovery
- **[Architecture & Design](design.md)** - Core architecture and design decisions

### Usage Guides

- **[Decorator Usage](decorator.md)** - Using @rate_limit decorator (advanced patterns)
- **[Utility Functions](utilities.md)** - Reusable functions for key generation and configuration

### Backend Development

- **[Backend Development Utilities](backend_utilities.md)** - For backend developers and contributors

### Integrations

- **[Django REST Framework](integrations/drf.md)** - DRF ViewSets, permissions, and serializers

### Operations

- **[Management Commands](management_commands.md)** - Health checks and cleanup commands

## 🚀 Quick Navigation

### By Use Case

#### Simple Rate Limiting

Start with [README](../README.md) for basic setup, then see [Decorator Usage](decorator.md) for patterns.

#### Production Deployment

Review [Backend Configuration](backends.md) for Redis setup and [Circuit Breaker](circuit_breaker.md) for resilience.

#### Advanced APIs

See [Rate Limiting Algorithms](algorithms.md) for token bucket configuration and [Multi-Backend](backends.md#multi-backend) for high availability.

#### Troubleshooting

Check [Circuit Breaker Troubleshooting](circuit_breaker.md#testing--troubleshooting) and [Management Commands](management_commands.md) for health checks.

### By Component

#### Rate Limiting Core

- [Algorithms](algorithms.md) - How rate limiting works
- [Decorator](decorator.md) - How to apply rate limits
- [Backends](backends.md) - Where data is stored

#### Reliability & Operations

- [Circuit Breaker](circuit_breaker.md) - Failure protection
- [Management Commands](management_commands.md) - Operational tools
- [Utilities](utilities.md) - Helper functions

## 🔗 External Resources

- **[GitHub Repository](https://github.com/YasserShkeir/django-smart-ratelimit)** - Source code and issues
- **[PyPI Package](https://pypi.org/project/django-smart-ratelimit/)** - Package installation
- **[Changelog](../CHANGELOG.md)** - Version history
- **[Contributing Guide](../CONTRIBUTING.md)** - How to contribute
