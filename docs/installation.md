# Installation & Configuration Guide

## 🚀 Installation

### Basic Installation

```bash
pip install django-smart-ratelimit
```

### With Optional Dependencies

```bash
# Redis backend (recommended for production)
pip install django-smart-ratelimit[redis]

# MongoDB backend
pip install django-smart-ratelimit[mongodb]

# JWT-based rate limiting
pip install django-smart-ratelimit[jwt]

# All optional dependencies
pip install django-smart-ratelimit[all]
```

### Development Installation

```bash
git clone https://github.com/YasserShkeir/django-smart-ratelimit.git
cd django-smart-ratelimit
pip install -e .[dev]
```

## ⚙️ Django Configuration

### 1. Add to INSTALLED_APPS

```python
# settings.py
INSTALLED_APPS = [
    # ... your apps
    'django_smart_ratelimit',
]
```

### 2. Configure Backend

#### Redis Backend (Recommended)

```python
# settings.py
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
    'password': None,  # Optional
    'socket_timeout': 0.1,
    'socket_connect_timeout': 0.1,
    'socket_keepalive': True,
    'socket_keepalive_options': {},
    'health_check_interval': 30,
}
```

#### Database Backend

```python
# settings.py
RATELIMIT_BACKEND = 'database'

# Run migrations
python manage.py migrate
```

#### Memory Backend (Development Only)

```python
# settings.py
RATELIMIT_BACKEND = 'memory'
RATELIMIT_MEMORY_MAX_KEYS = 10000
```

#### Multi-Backend (High Availability)

```python
# settings.py
RATELIMIT_BACKENDS = [
    {
        'name': 'primary_redis',
        'backend': 'redis',
        'config': {
            'host': 'redis-primary.example.com',
            'port': 6379,
            'db': 0,
        }
    },
    {
        'name': 'fallback_redis',
        'backend': 'redis',
        'config': {
            'host': 'redis-fallback.example.com',
            'port': 6379,
            'db': 0,
        }
    },
    {
        'name': 'emergency_db',
        'backend': 'database',
        'config': {}
    }
]
RATELIMIT_MULTI_BACKEND_STRATEGY = 'first_healthy'
```

### 3. Middleware Configuration (Optional)

```python
# settings.py
MIDDLEWARE = [
    'django_smart_ratelimit.middleware.RateLimitMiddleware',
    # ... other middleware
]

RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '100/m',
    'RATE_LIMITS': {
        '/api/auth/': '10/m',
        '/api/upload/': '5/h',
        '/api/': '200/h',
    },
    'SKIP_PATHS': ['/admin/', '/health/', '/static/'],
    'BLOCK': True,
    'KEY_FUNCTION': 'django_smart_ratelimit.utils.get_ip_key',
}
```

## 🔧 Advanced Configuration

### Custom Key Functions

```python
# utils.py
def custom_key_function(request):
    if request.user.is_authenticated:
        return f"user:{request.user.id}"
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

# settings.py
RATELIMIT_MIDDLEWARE = {
    'KEY_FUNCTION': 'myapp.utils.custom_key_function',
    # ... other settings
}
```

### Environment-Specific Configuration

```python
# settings/production.py
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': os.environ.get('REDIS_HOST', 'localhost'),
    'port': int(os.environ.get('REDIS_PORT', 6379)),
    'password': os.environ.get('REDIS_PASSWORD'),
}

# settings/development.py
RATELIMIT_BACKEND = 'memory'

# settings/testing.py
RATELIMIT_BACKEND = 'memory'
RATELIMIT_ENABLE = False  # Disable in tests
```

## 🧪 Testing Configuration

### Disable Rate Limiting in Tests

```python
# settings/test.py
RATELIMIT_ENABLE = False

# Or use override in specific tests
from django.test.utils import override_settings

@override_settings(RATELIMIT_ENABLE=False)
class MyTestCase(TestCase):
    def test_my_view(self):
        # Rate limiting is disabled
        pass
```

### Mock Backend for Testing

```python
# tests.py
from unittest.mock import patch
from django_smart_ratelimit.backends.memory import MemoryBackend

@patch('django_smart_ratelimit.backends.get_backend')
def test_with_mock_backend(mock_get_backend):
    mock_get_backend.return_value = MemoryBackend()
    # Your test code here
```

## 🏥 Health Checks

### Built-in Health Check

```bash
# Check backend health
python manage.py ratelimit_health

# Verbose output
python manage.py ratelimit_health --verbose

# JSON output for monitoring
python manage.py ratelimit_health --json
```

### Custom Health Check Integration

```python
# health_checks.py
from django_smart_ratelimit import get_backend

def ratelimit_health_check():
    backend = get_backend()
    return backend.health_check()

# In your monitoring system
if not ratelimit_health_check():
    alert("Rate limiting backend is unhealthy")
```

## 🔍 Troubleshooting

### Common Issues

#### Redis Connection Issues

```python
# Check Redis connectivity
redis-cli ping

# Check Django logs
python manage.py shell
>>> from django_smart_ratelimit import get_backend
>>> backend = get_backend()
>>> backend.health_check()
```

#### Database Backend Issues

```python
# Run migrations
python manage.py migrate

# Check database connectivity
python manage.py dbshell
```

#### Import Errors

```python
# Verify installation
pip show django-smart-ratelimit

# Check INSTALLED_APPS
python manage.py check
```

### Debug Mode

```python
# settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django_smart_ratelimit': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}
```

## 📊 Performance Considerations

### Redis Optimization

```python
RATELIMIT_REDIS = {
    'connection_pool_kwargs': {
        'max_connections': 50,
    },
    'socket_keepalive': True,
    'socket_keepalive_options': {
        'TCP_KEEPIDLE': 1,
        'TCP_KEEPINTVL': 3,
        'TCP_KEEPCNT': 5,
    },
}
```

### Database Optimization

```python
# Use separate database for rate limiting
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'myapp',
        # ... main database config
    },
    'ratelimit': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'ratelimit',
        # ... rate limiting database config
    }
}

DATABASE_ROUTERS = ['myapp.routers.RateLimitRouter']
```

### Memory Backend Limits

```python
RATELIMIT_MEMORY_MAX_KEYS = 100000
RATELIMIT_MEMORY_CLEANUP_INTERVAL = 60
```

## 🔐 Security Configuration

### IP Address Detection

```python
# settings.py
RATELIMIT_IP_META_KEYS = [
    'HTTP_CF_CONNECTING_IP',    # Cloudflare
    'HTTP_X_FORWARDED_FOR',     # Standard proxy
    'HTTP_X_REAL_IP',           # Nginx
    'REMOTE_ADDR',              # Fallback
]
```

### Trusted Proxies

```python
RATELIMIT_TRUSTED_PROXIES = [
    '10.0.0.0/8',
    '172.16.0.0/12',
    '192.168.0.0/16',
]
```

## 🚀 Production Deployment

### Docker Configuration

```dockerfile
# Dockerfile
FROM python:3.11-slim

COPY requirements.txt .
RUN pip install -r requirements.txt

# Set environment variables
ENV RATELIMIT_BACKEND=redis
ENV REDIS_HOST=redis
ENV REDIS_PORT=6379

COPY . .
CMD ["gunicorn", "myproject.wsgi:application"]
```

```yaml
# docker-compose.yml
version: "3.8"
services:
  web:
    build: .
    environment:
      - RATELIMIT_BACKEND=redis
      - REDIS_HOST=redis
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

### Kubernetes Configuration

```yaml
# k8s-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ratelimit-config
data:
  RATELIMIT_BACKEND: "redis"
  REDIS_HOST: "redis-service"
  REDIS_PORT: "6379"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: django-app
spec:
  template:
    spec:
      containers:
        - name: django
          image: myapp:latest
          envFrom:
            - configMapRef:
                name: ratelimit-config
```

## 📈 Monitoring Integration

### Prometheus Metrics

```python
# monitoring.py
from prometheus_client import Counter, Histogram

RATE_LIMIT_HITS = Counter('ratelimit_hits_total', 'Rate limit hits', ['key_type'])
RATE_LIMIT_BLOCKS = Counter('ratelimit_blocks_total', 'Rate limit blocks', ['key_type'])
```

### Datadog Integration

```python
# settings.py
RATELIMIT_MONITORING = {
    'BACKEND': 'datadog',
    'CONFIG': {
        'api_key': os.environ.get('DATADOG_API_KEY'),
        'tags': ['environment:production', 'service:ratelimit'],
    }
}
```

This configuration guide provides comprehensive setup instructions for all deployment scenarios.
