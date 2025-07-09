# Django Smart Ratelimit

[![CI](https://github.com/YasserShkeir/django-smart-ratelimit/workflows/CI/badge.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/actions)
[![PyPI version](https://img.shields.io/pypi/v/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![PyPI status](https://img.shields.io/pypi/status/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Django versions](https://img.shields.io/badge/Django-3.2%20%7C%204.0%20%7C%204.1%20%7C%204.2%20%7C%205.0%20%7C%205.1-blue.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![Downloads](https://img.shields.io/pypi/dm/django-smart-ratelimit.svg)](https://pypi.org/project/django-smart-ratelimit/)
[![License](https://img.shields.io/pypi/l/django-smart-ratelimit.svg)](https://github.com/YasserShkeir/django-smart-ratelimit/blob/main/LICENSE)
[![GitHub Discussions](https://img.shields.io/github/discussions/YasserShkeir/django-smart-ratelimit)](https://github.com/YasserShkeir/django-smart-ratelimit/discussions)

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
- 🌐 **DRF Integration**: Full Django REST Framework support with ViewSet, Serializer, and Permission integration

## 🚀 Quick Setup

### 1. Installation

```bash
# Basic installation
pip install django-smart-ratelimit

# With optional dependencies for specific backends/features
pip install django-smart-ratelimit[redis]      # Redis backend (recommended)
pip install django-smart-ratelimit[mongodb]    # MongoDB backend
pip install django-smart-ratelimit[jwt]        # JWT-based rate limiting
pip install django-smart-ratelimit[all]        # All optional dependencies
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

# With algorithm and skip_if parameters
@rate_limit(key='ip', rate='50/h', algorithm='sliding_window', skip_if=lambda req: req.user.is_staff)
def advanced_api(request):
    return JsonResponse({'advanced': 'data'})
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

### Core Documentation

- **[Backend Configuration](docs/backends.md)** - Redis, Database, Memory, and Multi-Backend setup
- **[Architecture & Design](docs/design.md)** - Core architecture, algorithms, and design decisions
- **[Management Commands](docs/management_commands.md)** - Health checks and cleanup commands

### Examples & Advanced Usage

- **[Basic Examples](examples/)** - Working examples for different use cases
- **[Complex Key Functions](examples/custom_key_functions.py)** - Custom key patterns and JWT tokens
- **[Multi-Backend Setup](examples/backend_configuration.py)** - High availability configurations
- **[DRF Integration](examples/drf_integration/)** - Django REST Framework integration examples
- **[DRF Documentation](docs/integrations/drf.md)** - Complete DRF integration guide

## 🏗️ Basic Examples

### Django REST Framework Integration

```python
from rest_framework import viewsets
from rest_framework.response import Response
from django_smart_ratelimit import rate_limit

class APIViewSet(viewsets.ViewSet):
    @rate_limit(key='ip', rate='100/h')
    def list(self, request):
        return Response({'data': 'list'})

    @rate_limit(key='user', rate='10/h')
    def create(self, request):
        return Response({'data': 'created'})

# Custom permission with rate limiting
from rest_framework.permissions import BasePermission

class RateLimitedPermission(BasePermission):
    def has_permission(self, request, view):
        # Apply rate limiting logic here
        return True
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

## 📚 Comprehensive Examples

The `examples/` directory contains detailed examples for every use case:

- **[basic_rate_limiting.py](examples/basic_rate_limiting.py)** - IP, user, and session-based limiting
- **[advanced_rate_limiting.py](examples/advanced_rate_limiting.py)** - Complex scenarios with custom logic
- **[custom_key_functions.py](examples/custom_key_functions.py)** - Geographic, device, and business logic keys
- **[jwt_rate_limiting.py](examples/jwt_rate_limiting.py)** - JWT token and role-based limiting
- **[tenant_rate_limiting.py](examples/tenant_rate_limiting.py)** - Multi-tenant applications
- **[backend_configuration.py](examples/backend_configuration.py)** - All backend configurations
- **[monitoring_examples.py](examples/monitoring_examples.py)** - Health checks and metrics
- **[django_integration.py](examples/django_integration.py)** - Complete Django project setup

See the **[Examples README](examples/README.md)** for detailed usage instructions.

## 🤝 Community & Support

We have an active community ready to help you get the most out of django-smart-ratelimit!

### 💬 GitHub Discussions

Join our community discussions for questions, ideas, and sharing experiences:

- **[� Q&A & Help](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/q-a)** - Get help with implementation and troubleshooting
- **[� Ideas & Feature Requests](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/ideas)** - Share ideas for new features
- **[📢 Announcements](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/announcements)** - Stay updated with project news
- **[💬 General Discussions](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/general)** - Community chat and use case sharing

### 🐛 Issues & Bug Reports

For bug reports and specific issues, please use [GitHub Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues).

### 🤝 Contributing

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

**[📚 Documentation](docs/)** • **[💡 Examples](examples/)** • **[🤝 Contributing](CONTRIBUTING.md)** • **[💬 Discussions](https://github.com/YasserShkeir/django-smart-ratelimit/discussions)** • **[🐛 Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues)**
