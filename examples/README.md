# Django Smart Ratelimit Examples

This directory contains comprehensive examples demonstrating various rate limiting patterns and use cases with the django-smart-ratelimit library.

## Quick Start

1. Install the package:

```bash
# Basic installation
pip install django-smart-ratelimit

# With specific backends
pip install django-smart-ratelimit[redis]      # For Redis backend
pip install django-smart-ratelimit[mongodb]    # For MongoDB backend
pip install django-smart-ratelimit[jwt]        # For JWT examples
pip install django-smart-ratelimit[all]        # All optional dependencies
```

2. Add to your Django settings:

```python
INSTALLED_APPS = [
    # ... your other apps
    'django_smart_ratelimit',
]

MIDDLEWARE = [
    'django_smart_ratelimit.middleware.RateLimitMiddleware',
    # ... other middleware
]
```

3. Choose a backend and configure it in your settings (see `backend_configuration.py`).

## Example Files

### Basic Usage

- **`basic_rate_limiting.py`** - Simple IP and user-based rate limiting
- **`django_integration.py`** - Complete Django project integration examples

### Advanced Rate Limiting

- **`advanced_rate_limiting.py`** - Complex rate limiting with custom key functions
- **`custom_key_functions.py`** - Advanced custom key generation strategies
- **`jwt_rate_limiting.py`** - JWT token-based rate limiting
- **`tenant_rate_limiting.py`** - Multi-tenant rate limiting strategies

### Django REST Framework Integration

- **`drf_integration/`** - Complete DRF integration examples
  - **`viewsets.py`** - ViewSet integration patterns
  - **`serializers.py`** - Serializer-level rate limiting
  - **`permissions.py`** - Permission-based rate limiting
  - **`README.md`** - Comprehensive DRF integration guide

### Backend Configuration

- **`backend_configuration.py`** - Configuration for all backend types
- **`redis_backend_examples.py`** - Redis backend specific examples
- **`mongodb_backend_example.py`** - MongoDB backend specific examples

### Middleware and Monitoring

- **`middleware_configuration.py`** - Middleware setup and configuration
- **`monitoring_examples.py`** - Health checks, metrics, and monitoring

## Use Cases by Example

### 1. Basic Rate Limiting (`basic_rate_limiting.py`)

- IP-based rate limiting
- User-based rate limiting
- Session-based rate limiting
- Header-based rate limiting
- Non-blocking rate limiting

### 2. Advanced Scenarios (`advanced_rate_limiting.py`)

- API key-based rate limiting
- Tenant-based rate limiting
- JWT token-based rate limiting
- Dynamic rate limiting
- Conditional rate limiting
- Burst limiting
- Sliding window rate limiting

### 3. Custom Key Functions (`custom_key_functions.py`)

- Geographic-based rate limiting
- Device fingerprint-based rate limiting
- Request size-based rate limiting
- Time-based rate limiting
- Referer-based rate limiting
- HTTP method-based rate limiting
- Content-type based rate limiting
- Complex business logic rate limiting

### 4. JWT Integration (`jwt_rate_limiting.py`)

**Requires:** `pip install django-smart-ratelimit[jwt]` or `pip install PyJWT`

JWT (JSON Web Token) based rate limiting allows you to apply different rate limits based on information embedded in JWT tokens, such as:

- **User identification** - Rate limit per authenticated user (instead of IP)
- **Role-based limiting** - Different limits for admin/user/guest roles
- **Subscription tiers** - Free/Premium/Enterprise users get different quotas
- **Service authentication** - Microservices with JWT get service-specific limits
- **API key management** - JWT tokens as API keys with embedded rate limit info

Examples included:

- JWT subject-based rate limiting
- Role-based rate limiting
- Subscription tier-based rate limiting
- JWT refresh token rate limiting
- Comprehensive JWT validation with rate limiting
- Admin bypass with JWT claims

### 5. Multi-tenant Support (`tenant_rate_limiting.py`)

- Basic tenant-based rate limiting
- Tenant quota-based rate limiting
- Hierarchical tenant rate limiting
- Tenant-specific feature rate limiting
- Tenant API key-based rate limiting
- Tenant subdomain-based rate limiting
- Tenant usage tracking

### 6. Backend Configuration (`backend_configuration.py`)

- Memory backend configuration
- Redis backend configuration
- Database backend configuration
- MongoDB backend configuration
- Multi-backend configuration
- Custom backend implementation

### 7. Monitoring and Health Checks (`monitoring_examples.py`)

- Backend health check endpoints
- Rate limiting metrics collection
- Performance monitoring
- Alerting integration
- Dashboard data endpoints

## Backend Types

### Memory Backend

- **Pros**: No external dependencies, fast for single-server deployments
- **Cons**: Data lost on restart, not suitable for multi-server deployments
- **Use case**: Development, testing, single-server applications

### Redis Backend

- **Pros**: Persistent, fast, supports distributed deployments
- **Cons**: Requires Redis server
- **Use case**: Production deployments, distributed systems

### Database Backend

- **Pros**: Uses existing Django database, persistent
- **Cons**: Slower than memory/Redis, requires database cleanup
- **Use case**: Simple deployments, when Redis is not available

### MongoDB Backend

- **Pros**: NoSQL flexibility, automatic TTL cleanup, good for analytics
- **Cons**: Requires MongoDB server
- **Use case**: Applications already using MongoDB, analytics-heavy applications

### Multi-Backend

- **Pros**: High availability, automatic failover
- **Cons**: Complex configuration, potential consistency issues
- **Use case**: High-availability production deployments

## Rate Limiting Strategies

### Fixed Window

- Simple implementation
- Potential burst issues at window boundaries
- Good for basic rate limiting

### Sliding Window

- More accurate rate limiting
- Prevents burst issues
- Slightly more complex implementation

### Token Bucket

- Allows bursts up to bucket capacity
- Good for APIs that need to handle spikes
- More complex to implement

## Common Patterns

### API Rate Limiting

```python
@rate_limit(key="user", rate="1000/h")
def api_endpoint(request):
    # Your API logic here
    pass
```

### Login Rate Limiting

```python
@rate_limit(key="ip", rate="5/m")
def login_view(request):
    # Login logic here
    pass
```

### File Upload Rate Limiting

```python
@rate_limit(key="user", rate="10/h")
def upload_view(request):
    # File upload logic here
    pass
```

### Admin Panel Protection

```python
@rate_limit(key="ip", rate="100/h")
def admin_view(request):
    # Admin logic here
    pass
```

## Configuration Examples

### Basic Configuration

```python
# settings.py
RATELIMIT_BACKEND = 'memory'
RATELIMIT_DEFAULT_RATE = '100/h'
```

### Redis Configuration

```python
# settings.py
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
}
```

### Middleware Configuration

```python
# settings.py
RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '100/h',
    'BACKEND': 'redis',
    'BLOCK': True,
    'SKIP_PATHS': ['/admin/', '/health/'],
    'RATE_LIMITS': {
        '/api/public/': '1000/h',
        '/api/private/': '100/h',
        '/auth/login/': '5/m',
    },
}
```

## New Features in Examples

### Algorithm Selection

All examples now demonstrate the use of the `algorithm` parameter:

```python
# Sliding window for smooth rate limiting
@rate_limit(key='ip', rate='100/h', algorithm='sliding_window')

# Fixed window for burst-tolerant rate limiting
@rate_limit(key='ip', rate='100/h', algorithm='fixed_window')
```

### Conditional Rate Limiting

Examples show the `skip_if` parameter for bypassing rate limits:

```python
# Skip rate limiting for staff users
@rate_limit(key='ip', rate='50/h', skip_if=lambda req: req.user.is_staff)

# Complex skip conditions
@rate_limit(key='ip', rate='100/h', skip_if=complex_skip_function)
```

## Key Parameters Reference

| Parameter   | Type     | Description                             | Examples                             |
| ----------- | -------- | --------------------------------------- | ------------------------------------ |
| `key`       | str/func | Rate limiting key or key function       | `'ip'`, `'user'`, custom             |
| `rate`      | str      | Rate limit format                       | `'10/m'`, `'100/h'`                  |
| `block`     | bool     | Whether to block when limit exceeded    | `True`, `False`                      |
| `backend`   | str      | Backend to use                          | `'redis'`, `'mongodb'`               |
| `algorithm` | str      | Rate limiting algorithm                 | `'sliding_window'`, `'fixed_window'` |
| `skip_if`   | func     | Function to conditionally skip limiting | `lambda req: req.user.is_staff`      |

## Testing

Each example file includes test scenarios. To run tests:

```bash
# Run all tests
python manage.py test

# Run specific backend tests
python manage.py test tests.test_redis_backend
python manage.py test tests.test_mongodb_backend
python manage.py test tests.test_memory_backend
```

## Management Commands

### Health Check

```bash
python manage.py ratelimit_health
```

### Cleanup (Database backend)

```bash
python manage.py cleanup_ratelimit --older-than 24
```

## Production Considerations

### Performance

- Use Redis backend for production
- Configure appropriate connection pooling
- Monitor backend performance
- Set up proper caching strategies

### Security

- Use HTTPS for API endpoints
- Implement proper authentication
- Consider IP whitelisting for admin endpoints
- Use secure headers for tenant identification

### Monitoring

- Set up health checks for backends
- Monitor rate limiting metrics
- Configure alerting for high usage
- Track performance metrics

### Scaling

- Use multi-backend for high availability
- Consider backend clustering
- Implement proper load balancing
- Plan for capacity scaling

## Troubleshooting

### Common Issues

1. **Backend connection failures**: Check backend configuration and connectivity
2. **Rate limits not working**: Verify middleware order and configuration
3. **Performance issues**: Check backend performance and connection pooling
4. **Memory leaks**: Ensure proper cleanup for memory backend

### Debug Mode

Enable debug logging:

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'loggers': {
        'django_smart_ratelimit': {
            'level': 'DEBUG',
            'handlers': ['console'],
        },
    },
}
```

## Getting Help

- **Questions about Examples**: [GitHub Discussions - Q&A](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/q-a)
- **Request New Examples**: [Discussions - Ideas](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/ideas)
- **Report Issues**: [GitHub Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues)
- **Share Your Use Cases**: [General Discussions](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/general)

## Contributing

To add new examples:

1. Create a new `.py` file in the examples directory
2. Follow the existing pattern with comprehensive comments
3. Include URL configuration examples
4. Add Django settings examples
5. Update this README with the new example

## License

These examples are provided under the same license as the django-smart-ratelimit library.
