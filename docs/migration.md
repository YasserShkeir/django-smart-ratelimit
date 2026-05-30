# Migration Guide

This guide covers migrating from `django-ratelimit`. If you are upgrading an
existing django-smart-ratelimit install from v2.x to v3.0.0, see the top-level
`MIGRATION.md` instead.

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

Keys and algorithms can also be passed as type-safe enums (`StrEnum`,
interchangeable with the string values everywhere a key/algorithm is accepted):

```python
from django_smart_ratelimit import ratelimit
from django_smart_ratelimit.enums import Algorithm, RateLimitKey

@ratelimit(key=RateLimitKey.IP, rate='10/m', algorithm=Algorithm.TOKEN_BUCKET)
def my_view(request):
    return HttpResponse('Hello')
```

The `ratelimit` name is an alias of `rate_limit`; either works. The async form
is `aratelimit`.

### Key Migration Benefits

- **Familiar decorator name**: `@ratelimit` keeps working with the same
  `key`, `rate`, and `block` arguments.
- **Enhanced reliability**: Circuit breaker protection
- **Better performance**: Atomic Redis operations
- **More flexibility**: Multiple algorithms and backends
- **Active maintenance**: Regular updates and bug fixes

### Differences to check

django-smart-ratelimit's `@ratelimit` does not accept `django-ratelimit`'s
`method` or `group` arguments. Use `skip_if=` to scope by request method, for
example `skip_if=lambda req: req.method == "GET"`.
