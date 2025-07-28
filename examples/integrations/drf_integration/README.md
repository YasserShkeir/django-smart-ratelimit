# Django REST Framework Integration Examples

This directory contains comprehensive examples demonstrating how to integrate Django Smart Ratelimit with Django REST Framework (DRF).

## Files Overview

### `viewsets.py`

Contains examples of integrating rate limiting with DRF ViewSets, including:

- **PostViewSet**: Basic ModelViewSet with method-specific rate limiting
- **AdvancedPostViewSet**: Advanced patterns with custom key functions and dynamic rates
- **CommentViewSet**: Hierarchical and usage-based rate limiting
- **MultiBackendViewSet**: Multi-backend rate limiting configuration
- **ConditionalRateLimitViewSet**: Conditional rate limiting based on request parameters
- **CustomErrorHandlingViewSet**: Custom error handling for rate limiting
- **MonitoredViewSet**: Built-in monitoring and metrics

### `serializers.py`

Contains examples of integrating rate limiting with DRF Serializers, including:

- **PostSerializer**: Basic serializer with rate-limited validation
- **AdvancedPostSerializer**: Rate-limited SerializerMethodField examples
- **CommentSerializer**: Nested serializer with rate-limited operations
- **RateLimitedPostSerializer**: Rate-limited create/update operations
- **ConditionalRateLimitSerializer**: Conditional rate limiting in serializers
- **FieldRateLimitedSerializer**: Field-specific rate limiting
- **BulkPostSerializer**: Bulk operations with rate limiting
- **ExternalAPISerializer**: Rate-limited external API calls

### `permissions.py`

Contains examples of integrating rate limiting with DRF Permissions, including:

- **RateLimitedPermission**: Basic permission with rate limiting
- **RoleBasedRateLimitedPermission**: Role-based rate limiting
- **ResourceSpecificRateLimitedPermission**: Resource-specific rate limits
- **TimeBasedRateLimitedPermission**: Time-based rate limiting
- **CompositeRateLimitedPermission**: Multiple rate limiting strategies
- **AdaptiveRateLimitedPermission**: Adaptive rate limiting based on system conditions
- **BypassableRateLimitedPermission**: Rate limiting with bypass mechanisms

## Installation

1. Install the required packages:

```bash
pip install djangorestframework django-smart-ratelimit
```

2. Add to your Django settings:

```python
INSTALLED_APPS = [
    # ... other apps
    'rest_framework',
    'django_smart_ratelimit',
]

# Configure rate limiting backend
RATELIMIT_BACKEND = 'django_smart_ratelimit.backends.redis_backend.RedisBackend'
RATELIMIT_BACKEND_OPTIONS = {
    'CONNECTION_POOL_KWARGS': {
        'host': 'localhost',
        'port': 6379,
        'db': 0,
    }
}
```

## Usage Examples

### Basic ViewSet Integration

```python
from rest_framework import viewsets
from django_smart_ratelimit import rate_limit
from .models import Post
from .serializers import PostSerializer

class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all()
    serializer_class = PostSerializer

    @rate_limit(key='ip', rate='100/m')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @rate_limit(key='user', rate='10/m')
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)
```

### Custom Permission with Rate Limiting

```python
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import Throttled
from django.core.cache import cache

class RateLimitedPermission(BasePermission):
    def has_permission(self, request, view):
        if not self._check_rate_limit(request):
            raise Throttled(detail="Rate limit exceeded")
        return True

    def _check_rate_limit(self, request):
        key = f"permission:{request.user.id if request.user.is_authenticated else request.META.get('REMOTE_ADDR')}"
        current = cache.get(key, 0)
        if current >= 100:  # 100 requests per minute
            return False
        cache.set(key, current + 1, 60)
        return True
```

### Serializer with Rate-Limited Validation

```python
from rest_framework import serializers
from django_smart_ratelimit import rate_limit

class PostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ['id', 'title', 'content', 'author']

    def validate_title(self, value):
        # Apply rate limiting before expensive validation
        if self._is_spam_title(value):
            raise serializers.ValidationError("Title appears to be spam")
        return value

    def _is_spam_title(self, title):
        # Expensive spam detection logic
        return False
```

## URL Configuration

```python
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PostViewSet, CommentViewSet

router = DefaultRouter()
router.register(r'posts', PostViewSet)
router.register(r'comments', CommentViewSet)

urlpatterns = [
    path('api/', include(router.urls)),
]
```

## Rate Limiting Strategies

### 1. Method-Specific Rate Limiting

Apply different rate limits to different HTTP methods:

```python
@rate_limit(key='ip', rate='100/m')
@rate_limit(key='user', rate='10/m')
def my_view(request):
    pass
```

### 2. Role-Based Rate Limiting

Apply different rate limits based on user roles:

```python
def get_rate_for_user(user):
    if user.is_staff:
        return '100/m'
    elif user.is_authenticated:
        return '50/m'
    else:
        return '10/m'
```

### 3. Resource-Specific Rate Limiting

Apply different rate limits based on the resource being accessed:

```python
RESOURCE_RATE_LIMITS = {
    'posts': {'GET': 200, 'POST': 10},
    'comments': {'GET': 500, 'POST': 30},
}
```

### 4. Time-Based Rate Limiting

Apply different rate limits based on time of day:

```python
def get_time_based_rate():
    now = timezone.now()
    if 9 <= now.hour < 17:  # Peak hours
        return '50/m'
    else:  # Off-peak hours
        return '100/m'
```

## Best Practices

### 1. Choose Appropriate Rate Limiting Keys

- Use `'ip'` for anonymous users
- Use `'user'` for authenticated users
- Use custom key functions for complex scenarios

### 2. Set Reasonable Limits

- Start with generous limits and adjust based on usage
- Consider different limits for different user types
- Account for legitimate batch operations

### 3. Provide Clear Error Messages

- Include information about when to retry
- Explain the rate limiting policy
- Provide contact information for questions

### 4. Monitor and Adjust

- Log rate limiting events for analysis
- Monitor false positives
- Adjust limits based on actual usage patterns

### 5. Handle Failures Gracefully

- Provide fallback mechanisms
- Implement circuit breakers
- Maintain service availability

## Testing

### Unit Tests

```python
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient

class RateLimitTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user('testuser', 'test@test.com', 'pass')

    def test_rate_limit_enforcement(self):
        self.client.force_authenticate(user=self.user)

        # Make requests up to the limit
        for i in range(10):
            response = self.client.post('/api/posts/', {'title': f'Post {i}'})
            self.assertEqual(response.status_code, 201)

        # This should be rate limited
        response = self.client.post('/api/posts/', {'title': 'Excess Post'})
        self.assertEqual(response.status_code, 429)
```

### Load Testing

```python
import threading
import time
from rest_framework.test import APIClient

def load_test_endpoint():
    client = APIClient()
    for i in range(100):
        response = client.get('/api/posts/')
        print(f"Response {i}: {response.status_code}")
        time.sleep(0.1)

# Run multiple threads
threads = []
for i in range(10):
    thread = threading.Thread(target=load_test_endpoint)
    threads.append(thread)
    thread.start()

for thread in threads:
    thread.join()
```

## Advanced Patterns

### 1. Hierarchical Rate Limiting

```python
@rate_limit(key='user', rate='100/h')  # Global user limit
@rate_limit(key=lambda r: f"post:{r.data.get('post_id')}:user:{r.user.id}", rate='10/h')  # Per-post limit
def create_comment(request):
    pass
```

### 2. Dynamic Rate Limiting

```python
def dynamic_rate_limit(request):
    if request.user.is_premium:
        return '100/m'
    elif request.user.is_authenticated:
        return '50/m'
    else:
        return '10/m'
```

### 3. Conditional Rate Limiting

```python
def conditional_rate_limit(request):
    if request.method == 'GET':
        return True  # No rate limiting for GET requests
    if request.user.is_staff:
        return True  # No rate limiting for staff
    return False  # Apply rate limiting
```

## Troubleshooting

### Common Issues

1. **Rate limits not being enforced**: Check that the rate limiting backend is properly configured
2. **Unexpected rate limit errors**: Verify that your rate limiting keys are unique
3. **Performance issues**: Consider using Redis for high-performance scenarios
4. **False positives**: Implement proper bypass mechanisms for legitimate use cases

### Debug Mode

```python
RATELIMIT_DEBUG = True  # Enable debug mode
```

### Logging

```python
LOGGING = {
    'version': 1,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'ratelimit.log',
        },
    },
    'loggers': {
        'django_smart_ratelimit': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Update documentation
6. Submit a pull request

## License

This project is licensed under the MIT License. See the LICENSE file for details.
