# Utility Functions Documentation

The `django_smart_ratelimit` package provides comprehensive utility functions for building flexible and reusable rate limiting solutions. These utilities help reduce code duplication and provide consistent behavior across your application.

> **Note**: For basic usage examples, see the [README](../README.md). This document covers advanced utility functions and patterns.

## Key Generation Functions (`django_smart_ratelimit.key_functions`)

### Common Patterns

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

@rate_limit(key=user_role_key, rate='1000/h')  # Staff users get higher limits
def api_view(request):
    return JsonResponse({'data': 'content'})
```

### Legacy Key Functions (Deprecated)

> **⚠️ Deprecated**: These functions are maintained for backward compatibility. Use the newer functions above.

#### `get_ip_key(request: HttpRequest) -> str`

Extract IP address from request, considering proxy headers.

```python
from django_smart_ratelimit.utils import get_ip_key

def my_view(request):
    ip_key = get_ip_key(request)  # Returns: "ip:192.168.1.1"
```

#### `get_user_key(request: HttpRequest) -> str`

Extract user-based key, falling back to IP for anonymous users.

```python
from django_smart_ratelimit.utils import get_user_key

def my_view(request):
    user_key = get_user_key(request)  # Returns: "user:123" or "ip:192.168.1.1"
```

### Advanced Key Functions

#### `get_jwt_key(request: HttpRequest, jwt_field: str = 'sub') -> str`

Extract key from JWT token claims.

```python
from django_smart_ratelimit.utils import get_jwt_key

def jwt_key_func(request):
    return get_jwt_key(request, jwt_field='sub')  # Returns: "jwt:sub:user123"

@rate_limit(key=jwt_key_func, rate='100/h')
def api_view(request):
    # Rate limited by JWT subject
    pass
```

#### `get_api_key_key(request: HttpRequest, header_name: str = 'X-API-Key') -> str`

Extract API key from custom headers.

```python
from django_smart_ratelimit.utils import get_api_key_key

def api_key_func(request):
    return get_api_key_key(request, header_name='X-API-Key')

@rate_limit(key=api_key_func, rate='1000/h')
def api_endpoint(request):
    # Rate limited by API key
    pass
```

#### `get_tenant_key(request: HttpRequest, tenant_field: str = 'tenant_id') -> str`

Extract tenant-based key for multi-tenant applications.

```python
from django_smart_ratelimit import get_tenant_key

def tenant_key_func(request):
    return get_tenant_key(request, tenant_field='org_id')

@rate_limit(key=tenant_key_func, rate='500/h')
def tenant_api(request):
    # Rate limited per organization
    pass
```

#### `get_device_fingerprint_key(request: HttpRequest) -> str`

Generate device fingerprint from request headers.

```python
from django_smart_ratelimit import get_device_fingerprint_key

@rate_limit(key=get_device_fingerprint_key, rate='50/h')
def public_api(request):
    # Rate limited by device fingerprint
    pass
```

### Composite Key Function

#### `get_client_identifier(request: HttpRequest, identifier_type: str = 'auto') -> str`

Smart client identification with multiple strategies.

```python
from django_smart_ratelimit import get_client_identifier

# Available types: 'ip', 'user', 'session', 'auto'
key = get_client_identifier(request, 'auto')  # Automatically selects best option
```

## Rate Parsing and Validation

#### `parse_rate(rate: str) -> Tuple[int, int]`

Parse rate strings into limit and period.

```python
from django_smart_ratelimit import parse_rate

limit, period = parse_rate("100/h")  # Returns: (100, 3600)
limit, period = parse_rate("10/m")   # Returns: (10, 60)
```

**Supported formats:**

- `"10/s"` - 10 requests per second
- `"100/m"` - 100 requests per minute
- `"1000/h"` - 1000 requests per hour
- `"10000/d"` - 10000 requests per day

#### `validate_rate_config(rate: str, algorithm: str = None, algorithm_config: dict = None) -> None`

Validate complete rate limiting configuration.

```python
from django_smart_ratelimit import validate_rate_config

# Validates rate format and algorithm configuration
validate_rate_config(
    rate="100/h",
    algorithm="token_bucket",
    algorithm_config={"bucket_size": 200, "refill_rate": 1.67}
)
```

## Key Generation Utilities

#### `generate_key(key: Union[str, Callable], request: HttpRequest, *args, **kwargs) -> str`

Universal key generator supporting templates and callables.

```python
from django_smart_ratelimit import generate_key

# Template strings
key1 = generate_key("ip", request)      # Uses get_ip_key()
key2 = generate_key("user", request)    # Uses get_user_key()
key3 = generate_key("custom:value", request)  # Returns as-is

# Callable functions
def custom_key(request):
    return f"custom:{request.user.id}"

key4 = generate_key(custom_key, request)  # Calls function
```

## HTTP Header Utilities

#### `add_rate_limit_headers(response, limit, remaining, reset_time=None, period=None)`

Add standard rate limiting headers to responses.

```python
from django_smart_ratelimit import add_rate_limit_headers

def my_view(request):
    response = JsonResponse({"data": "hello"})
    add_rate_limit_headers(response, limit=100, remaining=95, period=3600)
    return response
```

#### `add_token_bucket_headers(response, metadata, limit, period)`

Add token bucket specific headers.

```python
from django_smart_ratelimit import add_token_bucket_headers

metadata = {
    'tokens_remaining': 85,
    'bucket_size': 100,
    'refill_rate': 1.67,
    'time_to_refill': 15
}
add_token_bucket_headers(response, metadata, 100, 3600)
```

#### `format_rate_headers(metadata: dict, limit: int, period: int) -> dict`

Format metadata into header dictionary.

```python
from django_smart_ratelimit import format_rate_headers

headers = format_rate_headers(metadata, limit=100, period=3600)
# Returns dict of headers ready to add to response
```

## Request Filtering Utilities

#### `is_exempt_request(request, exempt_paths=None, exempt_ips=None) -> bool`

Check if request should be exempt from rate limiting.

```python
from django_smart_ratelimit import is_exempt_request

exempt_paths = ['/admin/.*', '/health/.*']
exempt_ips = ['192.168.1.1', '10.0.0.1']

if is_exempt_request(request, exempt_paths, exempt_ips):
    # Skip rate limiting
    pass
```

#### `should_skip_path(path: str, skip_patterns: list) -> bool`

Check if path matches skip patterns.

```python
from django_smart_ratelimit import should_skip_path

skip_patterns = ['/admin/', '/health/', '/static/']
if should_skip_path(request.path, skip_patterns):
    # Skip this path
    pass
```

#### `get_rate_for_path(path: str, rate_limits: dict, default_rate: str) -> str`

Get rate limit for specific path based on patterns.

```python
from django_smart_ratelimit import get_rate_for_path

rate_limits = {
    '/api/': '1000/h',
    '/auth/': '10/m',
    '/public/': '100/h'
}

rate = get_rate_for_path('/api/users', rate_limits, '50/h')
# Returns: '1000/h' (matches '/api/' pattern)
```

## Configuration Utilities

#### `load_function_from_string(function_path: str) -> Callable`

Dynamically load functions from string paths.

```python
from django_smart_ratelimit import load_function_from_string

# Load custom key function
key_func = load_function_from_string('myapp.utils.custom_key_function')

@rate_limit(key=key_func, rate='100/h')
def my_view(request):
    pass
```

## Usage Examples

### Composite Key Strategy

```python
from django_smart_ratelimit import (
    rate_limit, get_api_key_key, get_jwt_key,
    get_user_key, get_device_fingerprint_key, get_ip_key
)

def smart_key_function(request):
    """
    Intelligent key selection with fallback strategy:
    1. API Key (highest priority)
    2. JWT token
    3. Authenticated user
    4. Device fingerprint
    5. IP address (fallback)
    """
    # Try API key first
    try:
        api_key = get_api_key_key(request)
        if not api_key.startswith('ip:'):
            return api_key
    except:
        pass

    # Try JWT
    try:
        jwt_key = get_jwt_key(request)
        if not jwt_key.startswith('ip:'):
            return jwt_key
    except:
        pass

    # Try user
    user_key = get_user_key(request)
    if not user_key.startswith('ip:'):
        return user_key

    # Try device fingerprint
    try:
        return get_device_fingerprint_key(request)
    except:
        return get_ip_key(request)

@rate_limit(key=smart_key_function, rate='200/h')
def smart_api_view(request):
    return JsonResponse({"message": "Smart rate limiting applied"})
```

### Multi-Tier Rate Limiting

```python
def tier_based_key(request):
    """Rate limiting based on user subscription tier."""
    if hasattr(request, 'user') and request.user.is_authenticated:
        tier = getattr(request.user, 'subscription_tier', 'basic')
        return f"{tier}:user:{request.user.id}"
    return get_device_fingerprint_key(request)

@rate_limit(key=tier_based_key, rate='1000/h')  # Adjust per tier
def premium_feature(request):
    return JsonResponse({"premium": "content"})
```

### Geographic Rate Limiting

```python
from django_smart_ratelimit import get_ip_key

def geographic_key(request):
    """Rate limit by geographic region."""
    country = request.META.get('HTTP_CF_IPCOUNTRY', 'unknown')
    ip_key = get_ip_key(request)
    return f"geo:{country}:{ip_key}"

@rate_limit(key=geographic_key, rate='100/h')
def geo_limited_api(request):
    return JsonResponse({"geo": "content"})
```

## Best Practices

1. **Use appropriate key functions**: Choose the most specific identifier available
2. **Implement fallback strategies**: Always have a fallback (usually IP) for key generation
3. **Validate configurations**: Use `validate_rate_config()` to catch errors early
4. **Handle exceptions**: Wrap utility calls in try/except for robustness
5. **Cache expensive operations**: Consider caching results of complex key generation
6. **Document custom functions**: Clearly document your custom key functions
7. **Test thoroughly**: Test all code paths in your key generation logic

These utilities provide the building blocks for sophisticated rate limiting strategies while maintaining code reusability and consistency across your application.
