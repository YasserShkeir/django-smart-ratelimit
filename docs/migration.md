# Migration Guide

## Migration from django-ratelimit

Migrating from `django-ratelimit` is straightforward with minimal code changes:

### Basic Decorator Migration

```python
# OLD: django-ratelimit
from django_ratelimit.decorators import ratelimit

@ratelimit(key='ip', rate='10/m', block=True)
def my_view(request):
    return HttpResponse('Hello')

# NEW: django-smart-ratelimit
from django_smart_ratelimit import ratelimit

@ratelimit(key='ip', rate='10/m', block=True)
def my_view(request):
    return HttpResponse('Hello')
```

### Enhanced Features Available

```python
# NEW: Add algorithm choice
@ratelimit(key='ip', rate='10/m', algorithm='token_bucket')

# NEW: Add backend failover
@ratelimit(key='ip', rate='10/m', backend='redis')

# NEW: Add skip conditions
@ratelimit(key='ip', rate='10/m', skip_if=lambda req: req.user.is_staff)
```

### Key Migration Benefits

- **Drop-in replacement**: Same decorator syntax (`@ratelimit` vs `@ratelimit`)
- **Enhanced reliability**: Circuit breaker protection
- **Better performance**: Atomic Redis operations
- **More flexibility**: Multiple algorithms and backends
- **Active maintenance**: Regular updates and bug fixes
