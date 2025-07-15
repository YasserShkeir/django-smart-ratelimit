# Decorator Usage Guide

The `@rate_limit` decorator is the primary way to add rate limiting to individual Django views and functions.

> **Note**: For quick setup and basic examples, see the [README](../README.md). This guide covers advanced decorator usage patterns and detailed configuration options.

## Basic Usage

### Simple Rate Limiting

```python
from django_smart_ratelimit import rate_limit
from django.http import JsonResponse

@rate_limit(key='ip', rate='10/m')
def api_endpoint(request):
    return JsonResponse({'message': 'Hello World'})
```

### User-Based Rate Limiting

```python
@rate_limit(key='user', rate='100/h')
def user_dashboard(request):
    return JsonResponse({'user_data': request.user.username})
```

## Decorator Parameters

### Required Parameters

- **`key`**: Rate limiting key (string or callable)
- **`rate`**: Rate limit in format "count/period" (e.g., "10/m")

### Optional Parameters

- **`block`**: Whether to block requests when limit exceeded (default: `True`)
- **`backend`**: Backend to use for storage (default: configured backend)
- **`skip_if`**: Function to skip rate limiting conditionally
- **`algorithm`**: Algorithm to use ('fixed_window', 'sliding_window', 'token_bucket')
- **`algorithm_config`**: Configuration dict for the algorithm

## Key Types

### Predefined Keys

#### IP-based Rate Limiting

```python
@rate_limit(key='ip', rate='50/h')
def public_api(request):
    return JsonResponse({'data': 'public'})
```

#### User-based Rate Limiting

```python
@rate_limit(key='user', rate='1000/h')
def authenticated_api(request):
    # Automatically falls back to IP for anonymous users
    return JsonResponse({'data': 'authenticated'})
```

### Custom Key Functions

#### Lambda Functions

```python
@rate_limit(
    key=lambda req: f"api_key:{req.headers.get('X-API-Key', 'anonymous')}",
    rate='100/m'
)
def api_with_keys(request):
    return JsonResponse({'data': 'api_key_based'})
```

#### Named Functions

```python
def get_tenant_key(request):
    tenant_id = request.headers.get('X-Tenant-ID', 'default')
    if request.user.is_authenticated:
        return f"tenant:{tenant_id}:user:{request.user.id}"
    return f"tenant:{tenant_id}:ip:{request.META.get('REMOTE_ADDR')}"

@rate_limit(key=get_tenant_key, rate='500/h')
def multi_tenant_api(request):
    return JsonResponse({'tenant': 'data'})
```

#### Class-based Key Functions

```python
class RateLimitKeyGenerator:
    def __init__(self, prefix='custom'):
        self.prefix = prefix

    def __call__(self, request):
        if hasattr(request, 'api_key'):
            return f"{self.prefix}:api_key:{request.api_key}"
        return f"{self.prefix}:ip:{request.META.get('REMOTE_ADDR')}"

api_key_generator = RateLimitKeyGenerator('api')

@rate_limit(key=api_key_generator, rate='200/m')
def custom_key_api(request):
    return JsonResponse({'custom': 'key'})
```

## Rate Formats

### Supported Time Periods

- **`/s`**: Per second
- **`/m`**: Per minute
- **`/h`**: Per hour
- **`/d`**: Per day

### Examples

```python
@rate_limit(key='ip', rate='5/s')    # 5 requests per second
@rate_limit(key='ip', rate='100/m')  # 100 requests per minute
@rate_limit(key='ip', rate='1000/h') # 1000 requests per hour
@rate_limit(key='ip', rate='10000/d') # 10000 requests per day
```

## Algorithms

### Fixed Window Algorithm

```python
@rate_limit(
    key='ip',
    rate='100/h',
    algorithm='fixed_window'
)
def simple_api(request):
    return JsonResponse({'algorithm': 'fixed_window'})
```

**Characteristics:**

- Simple and memory efficient
- Allows bursts at window boundaries
- Suitable for basic rate limiting

### Sliding Window Algorithm

```python
@rate_limit(
    key='user',
    rate='500/h',
    algorithm='sliding_window'
)
def smooth_api(request):
    return JsonResponse({'algorithm': 'sliding_window'})
```

**Characteristics:**

- Smooth rate limiting without boundary effects
- Higher memory usage
- Precise rate control

### Token Bucket Algorithm

```python
@rate_limit(
    key='api_key',
    rate='100/m',
    algorithm='token_bucket',
    algorithm_config={
        'bucket_size': 200,    # Allow bursts up to 200 requests
        'refill_rate': 2.0,    # Refill at 2 tokens per second
    }
)
def burst_friendly_api(request):
    return JsonResponse({'algorithm': 'token_bucket'})
```

**Characteristics:**

- Allows burst traffic
- Configurable burst capacity
- Natural capacity and refill behavior

## Block Behavior

### Blocking Mode (Default)

```python
@rate_limit(key='ip', rate='10/m', block=True)
def strict_api(request):
    # Returns HTTP 429 when rate limit exceeded
    return JsonResponse({'data': 'strict'})
```

### Non-blocking Mode

```python
@rate_limit(key='ip', rate='10/m', block=False)
def lenient_api(request):
    # Continues execution but adds rate limit headers
    return JsonResponse({'data': 'lenient'})
```

## Conditional Rate Limiting

### Skip Based on User Status

```python
@rate_limit(
    key='ip',
    rate='10/m',
    skip_if=lambda req: req.user.is_staff
)
def staff_friendly_api(request):
    # Staff users bypass rate limiting
    return JsonResponse({'staff_access': True})
```

### Skip Based on Request Headers

```python
def skip_internal_requests(request):
    return request.headers.get('X-Internal-Request') == 'true'

@rate_limit(
    key='ip',
    rate='100/m',
    skip_if=skip_internal_requests
)
def internal_api(request):
    return JsonResponse({'internal': True})
```

### Skip Based on IP Address

```python
INTERNAL_IPS = ['127.0.0.1', '10.0.0.0/8', '192.168.0.0/16']

def skip_internal_ips(request):
    client_ip = request.META.get('REMOTE_ADDR')
    return client_ip in INTERNAL_IPS

@rate_limit(key='ip', rate='50/m', skip_if=skip_internal_ips)
def public_api(request):
    return JsonResponse({'public': True})
```

## Backend Selection

### Use Specific Backend

```python
@rate_limit(key='ip', rate='100/m', backend='redis')
def redis_rate_limited(request):
    return JsonResponse({'backend': 'redis'})

@rate_limit(key='ip', rate='100/m', backend='database')
def db_rate_limited(request):
    return JsonResponse({'backend': 'database'})
```

### Backend Fallback

```python
@rate_limit(key='ip', rate='100/m', backend='multi')
def highly_available_api(request):
    # Uses multi-backend with automatic failover
    return JsonResponse({'backend': 'multi'})
```

## Class-Based Views

### Function-Based Views

```python
@rate_limit(key='user', rate='100/h')
def my_view(request):
    return JsonResponse({'view': 'function'})
```

### Method Decoration

```python
from django.views import View
from django.utils.decorators import method_decorator

@method_decorator(rate_limit(key='user', rate='100/h'), name='get')
@method_decorator(rate_limit(key='user', rate='20/h'), name='post')
class MyView(View):
    def get(self, request):
        return JsonResponse({'method': 'GET'})

    def post(self, request):
        return JsonResponse({'method': 'POST'})
```

### Class Decoration

```python
@method_decorator(rate_limit(key='user', rate='100/h'), name='dispatch')
class RateLimitedView(View):
    def get(self, request):
        return JsonResponse({'class': 'decorated'})
```

## Django REST Framework Integration

### ViewSet Methods

```python
from rest_framework import viewsets
from rest_framework.response import Response

class APIViewSet(viewsets.ViewSet):
    @rate_limit(key='ip', rate='100/h')
    def list(self, request):
        return Response({'action': 'list'})

    @rate_limit(key='user', rate='10/h')
    def create(self, request):
        return Response({'action': 'create'})

    @rate_limit(key='user', rate='50/h')
    def retrieve(self, request, pk=None):
        return Response({'action': 'retrieve', 'id': pk})
```

### API View Classes

```python
from rest_framework.views import APIView

class RateLimitedAPIView(APIView):
    @rate_limit(key='user', rate='200/h')
    def get(self, request):
        return Response({'data': 'GET response'})

    @rate_limit(key='user', rate='50/h')
    def post(self, request):
        return Response({'data': 'POST response'})
```

## Advanced Patterns

### Different Limits for Different User Types

```python
def get_user_rate(request):
    if not request.user.is_authenticated:
        return '10/m'  # Anonymous users
    elif request.user.is_premium:
        return '1000/h'  # Premium users
    else:
        return '100/h'  # Regular users

def rate_limit_by_user_type(key):
    def decorator(func):
        def wrapper(request, *args, **kwargs):
            rate = get_user_rate(request)
            return rate_limit(key=key, rate=rate)(func)(request, *args, **kwargs)
        return wrapper
    return decorator

@rate_limit_by_user_type('user')
def tiered_api(request):
    return JsonResponse({'tier': 'dynamic'})
```

### Geographic Rate Limiting

```python
def get_country_key(request):
    # Assuming you have GeoIP setup
    country = request.META.get('HTTP_CF_IPCOUNTRY', 'unknown')
    return f"country:{country}:ip:{request.META.get('REMOTE_ADDR')}"

@rate_limit(key=get_country_key, rate='1000/h')
def geo_api(request):
    return JsonResponse({'geographic': 'rate_limiting'})
```

### Time-based Rate Limiting

```python
from datetime import datetime

def get_time_based_rate(request):
    hour = datetime.now().hour
    if 9 <= hour <= 17:  # Business hours
        return '1000/h'
    else:  # Off hours
        return '100/h'

def time_based_rate_limit(key):
    def decorator(func):
        def wrapper(request, *args, **kwargs):
            rate = get_time_based_rate(request)
            return rate_limit(key=key, rate=rate)(func)(request, *args, **kwargs)
        return wrapper
    return decorator

@time_based_rate_limit('user')
def business_hours_api(request):
    return JsonResponse({'time_based': True})
```

## Error Handling

### Custom Rate Limit Exceeded Response

```python
from django.http import HttpResponseTooManyRequests

def custom_rate_limit_decorator(key, rate):
    def decorator(func):
        original_decorator = rate_limit(key=key, rate=rate, block=False)

        def wrapper(request, *args, **kwargs):
            response = original_decorator(func)(request, *args, **kwargs)

            # Check if rate limit was exceeded
            remaining = response.get('X-RateLimit-Remaining', '1')
            if remaining == '0':
                return HttpResponseTooManyRequests(
                    "Custom rate limit message",
                    content_type="application/json"
                )

            return response
        return wrapper
    return decorator

@custom_rate_limit_decorator('ip', '10/m')
def custom_error_api(request):
    return JsonResponse({'custom': 'error_handling'})
```

### Graceful Degradation

```python
@rate_limit(key='user', rate='100/h', block=False)
def graceful_api(request):
    response_data = {'data': 'full_response'}

    # Check rate limit status from headers
    # Note: This requires custom middleware or response processing
    if hasattr(request, 'rate_limit_exceeded'):
        response_data = {'data': 'limited_response'}

    return JsonResponse(response_data)
```

## Testing Rate Limited Views

### Disable Rate Limiting in Tests

```python
from django.test import TestCase, override_settings

@override_settings(RATELIMIT_ENABLE=False)
class TestMyViews(TestCase):
    def test_api_endpoint(self):
        response = self.client.get('/api/endpoint/')
        self.assertEqual(response.status_code, 200)
```

### Test Rate Limiting Behavior

```python
from django.test import TestCase
from django_smart_ratelimit.backends.memory import MemoryBackend

class TestRateLimiting(TestCase):
    def setUp(self):
        # Use memory backend for testing
        self.backend = MemoryBackend()

    def test_rate_limit_exceeded(self):
        # Make requests up to the limit
        for i in range(10):
            response = self.client.get('/api/limited/')
            self.assertEqual(response.status_code, 200)

        # Next request should be rate limited
        response = self.client.get('/api/limited/')
        self.assertEqual(response.status_code, 429)
```

## Best Practices

### 1. Choose Appropriate Keys

- Use `user` for authenticated endpoints
- Use `ip` for public endpoints
- Use custom keys for complex scenarios

### 2. Set Reasonable Limits

- Start conservative and adjust based on usage
- Consider different limits for different user types
- Account for legitimate burst patterns

### 3. Use Appropriate Algorithms

- `fixed_window` for simple cases
- `sliding_window` for smooth limiting
- `token_bucket` for burst-friendly APIs

### 4. Handle Rate Limit Exceeded Gracefully

- Provide meaningful error messages
- Include retry-after information
- Consider non-blocking mode for non-critical endpoints

### 5. Monitor and Adjust

- Monitor rate limit hit rates
- Adjust limits based on real usage patterns
- Use appropriate backends for your scale

### 6. Test Thoroughly

- Test rate limiting behavior in staging
- Use appropriate test backends
- Test edge cases and error conditions
