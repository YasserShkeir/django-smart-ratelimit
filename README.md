# Django Smart Ratelimit

[![CI](https://github.com/YasserShkeir/django-smart-ratelimit/workflows/CI/badge.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/actions)
[![PyPI version](https://img.shields.io/pypi/v/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![PyPI status](https://img.shields.io/pypi/status/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Django versions](https://img.shields.io/badge/Django-3.2%20%7C%204.0%20%7C%204.1%20%7C%204.2%20%7C%205.0%20%7C%205.1-blue.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Downloads](https://img.shields.io/pypi/dm/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![License](https://img.shields.io/pypi/l/django-smart-ratelimit.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/LICENSE)

A flexible and efficient rate limiting library for Django applications with support for multiple backends and automatic fallback.

## ✨ Features

- 🚀 **High Performance**: Atomic operations using Redis Lua scripts and optimized algorithms
- 🔧 **Flexible Configuration**: Both decorator and middleware support with custom key functions
- 🪟 **Multiple Algorithms**: Fixed window and sliding window rate limiting
- 🔌 **Multiple Backends**: Redis, Database, Memory, and Multi-Backend with automatic fallback
- 📊 **Rich Headers**: Standard rate limiting headers (X-RateLimit-\*)
- 🛡️ **Production Ready**: Comprehensive testing, error handling, and monitoring
- 🔄 **Auto-Fallback**: Seamless failover between backends when one goes down
- 📈 **Health Monitoring**: Built-in health checks and status reporting

## 🚀 Quick Setup

### 1. Installation

```bash
pip install django-smart-ratelimit
```

### 2. Add to Django Settings

```python
# settings.py
INSTALLED_APPS = [
    # ... your apps
    'django_smart_ratelimit',
]

# Basic Redis configuration (recommended for production)
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
}
```

### 3. Choose Your Style

#### Option A: Decorator Style (View-Level)

```python
from django_smart_ratelimit import rate_limit
from django.http import JsonResponse

@rate_limit(key='ip', rate='10/m')
def api_endpoint(request):
    return JsonResponse({'message': 'Hello World'})

@rate_limit(key='user', rate='100/h', block=True)
def user_api(request):
    return JsonResponse({'data': 'user-specific data'})
```

#### Option B: Middleware Style (Application-Level)

```python
# settings.py
MIDDLEWARE = [
    'django_smart_ratelimit.middleware.RateLimitMiddleware',
    # ... other middleware
]

RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '100/m',
    'RATE_LIMITS': {
        '/api/': '1000/h',
        '/auth/login/': '5/m',
    },
    'SKIP_PATHS': ['/admin/', '/health/'],
}
```

### 4. Test It Works

```bash
# Check backend health
python manage.py ratelimit_health

# Test with curl
curl -I http://localhost:8000/api/endpoint/
# Look for X-RateLimit-* headers
```

That's it! You now have rate limiting protection. 🎉

## 📖 Documentation

### Core Concepts

- **[Backend Configuration](docs/backends.md)** - Redis, Database, Memory, and Multi-Backend setup
- **[Architecture & Design](docs/design.md)** - Core architecture, algorithms, and design decisions
- **[Management Commands](docs/management_commands.md)** - Health checks and cleanup commands

### Advanced Configuration

- **[Multi-Backend Examples](docs/backends.md#multi-backend-high-availability)** - High availability with automatic fallback
- **[Complex Key Functions](CONTRIBUTING.md#complex-key-function-examples)** - Enterprise API keys, JWT tokens, custom patterns
- **[Performance Tuning](CONTRIBUTING.md#performance-tuning)** - Optimization tips and best practices
- **[Monitoring Setup](CONTRIBUTING.md#monitoring-and-alerting)** - Production monitoring and alerting

### Development & Contributing

- **[Contributing Guide](CONTRIBUTING.md)** - Development setup, testing, and code guidelines
- **[Features Roadmap](FEATURES_ROADMAP.md)** - Planned features and implementation status
- **[Release Guide](RELEASE_GUIDE.md)** - Release process and version management

## 🏗️ Basic Examples

### Decorator Examples

```python
from django_smart_ratelimit import rate_limit

# Basic IP-based limiting
@rate_limit(key='ip', rate='10/m')
def public_api(request):
    return JsonResponse({'message': 'Hello World'})

# User-based limiting (requires authentication)
@rate_limit(key='user', rate='100/h')
def user_dashboard(request):
    return JsonResponse({'user_data': '...'})

# Custom key with fallback
@rate_limit(key='user_or_ip', rate='50/h')
def flexible_api(request):
    return JsonResponse({'data': '...'})

# Block when limit exceeded (default is to continue)
@rate_limit(key='ip', rate='5/m', block=True)
def strict_api(request):
    return JsonResponse({'sensitive': 'data'})
```

### Middleware Configuration

```python
# settings.py
RATELIMIT_MIDDLEWARE = {
    # Default rate for all paths
    'DEFAULT_RATE': '100/m',

    # Path-specific rates
    'RATE_LIMITS': {
        '/api/auth/': '10/m',      # Authentication endpoints
        '/api/upload/': '5/h',     # File uploads
        '/api/search/': '50/m',    # Search endpoints
        '/api/': '200/h',          # General API
    },

    # Paths to skip (no rate limiting)
    'SKIP_PATHS': [
        '/admin/',
        '/health/',
        '/static/',
    ],

    # Custom key function
    'KEY_FUNCTION': 'myapp.utils.get_api_key_or_ip',

    # Block requests when limit exceeded
    'BLOCK': True,
}
```

## 🔧 Backend Options

### Redis (Recommended for Production)

```python
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
    'password': 'your-password',  # if needed
    'socket_timeout': 0.1,
}
```

### Database (Good for Small Scale)

```python
RATELIMIT_BACKEND = 'database'
# No additional configuration needed
# Uses your default Django database
```

### Memory (Development Only)

```python
RATELIMIT_BACKEND = 'memory'
RATELIMIT_MEMORY_MAX_KEYS = 10000
```

### Multi-Backend (High Availability)

```python
RATELIMIT_BACKENDS = [
    {
        'name': 'primary_redis',
        'backend': 'redis',
        'config': {'host': 'redis-primary.example.com'}
    },
    {
        'name': 'fallback_redis',
        'backend': 'redis',
        'config': {'host': 'redis-fallback.example.com'}
    },
    {
        'name': 'emergency_db',
        'backend': 'database',
        'config': {}
    }
]
RATELIMIT_MULTI_BACKEND_STRATEGY = 'first_healthy'
```

## 🔍 Monitoring

### Health Checks

```bash
# Basic health check
python manage.py ratelimit_health

# Detailed status
python manage.py ratelimit_health --verbose

# JSON output for monitoring
python manage.py ratelimit_health --json
```

### Cleanup (Database Backend)

```bash
# Clean expired entries
python manage.py cleanup_ratelimit

# Preview what would be deleted
python manage.py cleanup_ratelimit --dry-run

# Clean entries older than 24 hours
python manage.py cleanup_ratelimit --older-than 24
```

## 🆚 Comparison

| Feature           | django-smart-ratelimit      | django-ratelimit   | django-rest-framework |
| ----------------- | --------------------------- | ------------------ | --------------------- |
| Multiple Backends | ✅ Redis, DB, Memory, Multi | ❌ Cache only      | ❌ Cache only         |
| Sliding Window    | ✅                          | ❌                 | ❌                    |
| Auto-Fallback     | ✅                          | ❌                 | ❌                    |
| Health Monitoring | ✅                          | ❌                 | ❌                    |
| Standard Headers  | ✅                          | ❌                 | ⚠️ Limited            |
| Atomic Operations | ✅                          | ⚠️ Race conditions | ⚠️ Race conditions    |
| Production Ready  | ✅                          | ⚠️                 | ⚠️                    |

## 🤝 Contributing

We welcome contributions! See our [Contributing Guide](CONTRIBUTING.md) for details on:

- Setting up the development environment
- Running tests and code quality checks
- Submitting pull requests
- Code style guidelines

## 💖 Support the Project

If you find this project helpful and want to support its development, you can make a donation:

- **USDT (Ethereum)**: `0x202943b3a6CC168F92871d9e295537E6cbc53Ff4`

Your support helps maintain and improve this open-source project for the Django community! 🙏

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Inspired by various rate limiting implementations in the Django ecosystem
- Built with performance and reliability in mind for production use
- Community feedback and contributions help make this better

---

**[Documentation](docs/)** • **[Examples](examples.py)** • **[Contributing](CONTRIBUTING.md)** • **[Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues)**
