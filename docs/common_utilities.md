# Common Key Functions and Authentication Utilities

This document describes the new centralized utilities added to django-smart-ratelimit to eliminate code duplication and provide consistent patterns across examples, tests, and user applications.

## Key Functions (`django_smart_ratelimit.key_functions`)

### Basic Key Functions

#### `user_or_ip_key(request: HttpRequest) -> str`

The most common rate limiting pattern. Returns user ID if authenticated, otherwise falls back to IP address.

```python
from django_smart_ratelimit import rate_limit, user_or_ip_key

@rate_limit(key=user_or_ip_key, rate='100/h')
def my_view(request):
    return JsonResponse({'message': 'success'})
```

#### `user_role_key(request: HttpRequest) -> str`

Includes user role (staff/user) in the key for role-based rate limiting.

```python
from django_smart_ratelimit import rate_limit, user_role_key

@rate_limit(key=user_role_key, rate='1000/h')  # Staff users get same limit as regular users
def api_view(request):
    return JsonResponse({'data': 'content'})
```

### Advanced Key Functions

#### `geographic_key(request: HttpRequest) -> str`

Combines geographic information with user/IP for location-based rate limiting.

```python
from django_smart_ratelimit import rate_limit, geographic_key

@rate_limit(key=geographic_key, rate='200/h')
def geo_limited_api(request):
    return JsonResponse({'location': 'specific content'})
```

#### `tenant_aware_key(request: HttpRequest, tenant_field: str = 'tenant_id') -> str`

Multi-tenant aware key function for SaaS applications.

```python
from django_smart_ratelimit import rate_limit, tenant_aware_key

@rate_limit(key=tenant_aware_key, rate='5000/h')
def tenant_api(request):
    return JsonResponse({'tenant_data': 'content'})
```

#### `composite_key(request: HttpRequest, strategies: Optional[List[str]] = None) -> str`

Tries multiple identification strategies in order.

```python
from django_smart_ratelimit import rate_limit, composite_key

# Try user, then session, then IP
@rate_limit(key=lambda req: composite_key(req, ['user', 'session', 'ip']), rate='300/h')
def smart_api(request):
    return JsonResponse({'smart': 'content'})
```

#### `device_fingerprint_key(request: HttpRequest) -> str`

Generates a key based on device characteristics from request headers.

```python
from django_smart_ratelimit import rate_limit, device_fingerprint_key

@rate_limit(key=device_fingerprint_key, rate='150/h')
def device_limited_api(request):
    return JsonResponse({'device': 'content'})
```

#### `api_key_aware_key(request: HttpRequest, header_name: str = 'X-API-Key') -> str`

Uses API key if present, otherwise falls back to user or IP.

```python
from django_smart_ratelimit import rate_limit, api_key_aware_key

@rate_limit(key=api_key_aware_key, rate='10000/h')
def api_key_endpoint(request):
    return JsonResponse({'api': 'content'})
```

#### `time_aware_key(request: HttpRequest, time_window: str = 'hour') -> str`

Includes time window in the key for time-based rate limiting patterns.

```python
from django_smart_ratelimit import rate_limit, time_aware_key

@rate_limit(key=lambda req: time_aware_key(req, 'day'), rate='1000/d')
def daily_reset_api(request):
    return JsonResponse({'daily': 'content'})
```

### Legacy Compatibility Functions

#### `user_or_ip_key_legacy(group: str, request: HttpRequest) -> str`

#### `user_role_key_legacy(group: str, request: HttpRequest) -> str`

These functions provide backward compatibility with old-style key functions that expected a `group` parameter.

## Authentication Utilities (`django_smart_ratelimit.auth_utils`)

### Basic Authentication Checks

#### `is_authenticated_user(request: HttpRequest) -> bool`

Safe check for authenticated user.

```python
from django_smart_ratelimit.auth_utils import is_authenticated_user

if is_authenticated_user(request):
    # User is authenticated
    pass
```

#### `get_user_info(request: HttpRequest) -> Optional[Dict[str, Any]]`

Extract user information safely.

```python
from django_smart_ratelimit.auth_utils import get_user_info

user_info = get_user_info(request)
if user_info:
    print(f"User: {user_info['username']}, Staff: {user_info['is_staff']}")
```

#### `get_user_role(request: HttpRequest) -> str`

Get user role as string ('anonymous', 'user', 'staff', 'superuser').

```python
from django_smart_ratelimit.auth_utils import get_user_role

role = get_user_role(request)
if role == 'staff':
    # Handle staff user
    pass
```

### Advanced Authentication Utilities

#### `get_client_info(request: HttpRequest) -> Dict[str, Any]`

Extract comprehensive client information from request.

```python
from django_smart_ratelimit.auth_utils import get_client_info

client_info = get_client_info(request)
print(f"IP: {client_info['ip']}, User-Agent: {client_info['user_agent']}")
```

#### `has_permission(request: HttpRequest, permission: str) -> bool`

Check if user has a specific permission.

```python
from django_smart_ratelimit.auth_utils import has_permission

if has_permission(request, 'myapp.special_action'):
    # User has permission
    pass
```

#### `should_bypass_rate_limit(request: HttpRequest, bypass_staff: bool = False, bypass_superuser: bool = True) -> bool`

Check if rate limiting should be bypassed for this user.

```python
from django_smart_ratelimit.auth_utils import should_bypass_rate_limit

if should_bypass_rate_limit(request, bypass_staff=True):
    # Skip rate limiting for this user
    pass
```

#### `extract_user_identifier(request: HttpRequest) -> str`

Extract a unique identifier for the user.

```python
from django_smart_ratelimit.auth_utils import extract_user_identifier

identifier = extract_user_identifier(request)
# Returns "user:123" or "ip:192.168.1.1"
```

#### `is_internal_request(request: HttpRequest, internal_ips: Optional[list] = None) -> bool`

Check if request comes from internal IP addresses.

```python
from django_smart_ratelimit.auth_utils import is_internal_request

if is_internal_request(request, ['192.168.1.0/24', '10.0.0.0/8']):
    # Internal request - might skip rate limiting
    pass
```

## Usage Examples

### Replacing Duplicate Code

**Before** (duplicated across multiple files):

```python
# This pattern was repeated in 10+ files
def user_or_ip_key(group, request):
    if request.user.is_authenticated:
        return str(request.user.id)
    return request.META.get('REMOTE_ADDR')

def user_role_key(group, request):
    if request.user.is_authenticated:
        role = 'staff' if request.user.is_staff else 'user'
        return f"{request.user.id}:{role}"
    return request.META.get('REMOTE_ADDR')
```

**After** (centralized):

```python
from django_smart_ratelimit import user_or_ip_key, user_role_key

# Use directly in decorators
@rate_limit(key=user_or_ip_key, rate='100/h')
def my_view(request):
    pass

@rate_limit(key=user_role_key, rate='200/h')
def role_based_view(request):
    pass
```

### Authentication Patterns

**Before** (scattered checks):

```python
# This pattern was repeated 16+ times
if hasattr(request, 'user') and request.user.is_authenticated:
    # Do something with authenticated user
    pass
```

**After** (centralized):

```python
from django_smart_ratelimit import is_authenticated_user, get_user_info

if is_authenticated_user(request):
    user_info = get_user_info(request)
    # Use user_info safely
```

### Complex Rate Limiting Scenarios

```python
from django_smart_ratelimit import (
    rate_limit,
    composite_key,
    should_bypass_rate_limit,
    get_user_role
)

def smart_rate_limit_key(request):
    if should_bypass_rate_limit(request):
        return 'bypass:always'

    role = get_user_role(request)
    if role == 'staff':
        return f'staff:{request.user.id}'

    return composite_key(request, ['user', 'session', 'ip'])

@rate_limit(key=smart_rate_limit_key, rate='500/h')
def complex_api(request):
    return JsonResponse({'complex': 'logic'})
```

## Benefits

1. **Reduced Code Duplication**: Common patterns are centralized
2. **Consistent Behavior**: All code uses the same implementations
3. **Better Maintainability**: Changes need to be made in one place
4. **Easier Testing**: Centralized functions are easier to test
5. **Improved Documentation**: Clear patterns for common use cases

## Migration Guide

### For Existing Examples and Tests

1. **Replace duplicate key functions**:

   ```python
   # Old
   def user_or_ip_key(group, request):
       # ... implementation

   # New
   from django_smart_ratelimit import user_or_ip_key
   ```

2. **Replace authentication checks**:

   ```python
   # Old
   if hasattr(request, 'user') and request.user.is_authenticated:
       # ...

   # New
   from django_smart_ratelimit import is_authenticated_user
   if is_authenticated_user(request):
       # ...
   ```

3. **Use centralized utilities**:

   ```python
   # Old
   def extract_user_info(request):
       if request.user.is_authenticated:
           return {'id': request.user.id, ...}
       return None

   # New
   from django_smart_ratelimit import get_user_info
   user_info = get_user_info(request)
   ```

### For New Code

Always prefer the centralized utilities over custom implementations:

```python
from django_smart_ratelimit import (
    rate_limit,
    user_or_ip_key,           # Most common pattern
    user_role_key,            # Role-based limiting
    geographic_key,           # Location-based limiting
    tenant_aware_key,         # Multi-tenant applications
    composite_key,            # Complex identification
    is_authenticated_user,    # Safe auth check
    get_user_role,           # Role identification
    should_bypass_rate_limit, # Bypass logic
)
```

This centralization eliminates the duplicate logic identified in the code review and provides a solid foundation for consistent rate limiting patterns across the django-smart-ratelimit ecosystem.
