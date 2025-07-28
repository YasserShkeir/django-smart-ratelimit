# Django REST Framework (DRF) Integration Guide

This guide provides comprehensive instructions for integrating Django Smart Ratelimit with Django REST Framework.

## Quick Start

### Installation & Setup

```bash
pip install djangorestframework django-smart-ratelimit
```

Add both to your `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ... other apps
    'rest_framework',
    'django_smart_ratelimit',
]
```

Configure rate limiting:

```python
RATELIMIT_BACKEND = 'redis'
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
}
```

### Simple Example

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from django_smart_ratelimit import rate_limit

class UserListView(APIView):
    @rate_limit(key='ip', rate='10/m')
    def get(self, request):
        return Response({'users': []})

    @rate_limit(key='user', rate='5/m')
    def post(self, request):
        return Response({'message': 'User created'})
```

## APIView Integration

### Basic Usage

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from django_smart_ratelimit import rate_limit

class ProductAPIView(APIView):
    @rate_limit(key='ip', rate='100/h')
    def get(self, request):
        return Response([{'id': 1, 'name': 'Product 1'}])

    @rate_limit(key='user', rate='10/h')
    def post(self, request):
        return Response({'message': 'Product created'}, status=201)

    @rate_limit(key='user', rate='5/h')
    def put(self, request):
        return Response({'message': 'Product updated'})

    @rate_limit(key='user', rate='2/h')
    def delete(self, request):
        return Response(status=204)
```

### Dynamic Rate Limiting

```python
def get_user_rate(request):
    if not request.user.is_authenticated:
        return '10/h'
    elif request.user.is_staff:
        return '1000/h'
    elif hasattr(request.user, 'profile') and request.user.profile.is_premium:
        return '500/h'
    return '100/h'

class DynamicRateAPIView(APIView):
    @rate_limit(key='user_or_ip', rate=get_user_rate)
    def get(self, request):
        return Response({'data': 'Your data here'})
```

## ViewSet Integration

### Basic ViewSet

```python
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.decorators import action
from django_smart_ratelimit import rate_limit

class UserViewSet(viewsets.ViewSet):
    @rate_limit(key='ip', rate='50/h')
    def list(self, request):
        return Response([{'id': 1, 'username': 'user1'}])

    @rate_limit(key='ip', rate='20/h')
    def retrieve(self, request, pk=None):
        return Response({'id': pk, 'username': f'user{pk}'})

    @rate_limit(key='user', rate='5/h')
    def create(self, request):
        return Response({'message': 'User created'})

    @rate_limit(key='user', rate='10/h')
    def update(self, request, pk=None):
        return Response({'message': f'User {pk} updated'})

    @rate_limit(key='user', rate='2/h')
    def destroy(self, request, pk=None):
        return Response({'message': f'User {pk} deleted'})

    @action(detail=True)
    @rate_limit(key='user', rate='3/h')
    def set_password(self, request, pk=None):
        return Response({'message': 'Password updated'})

    @action(detail=False)
    @rate_limit(key='ip', rate='30/h')
    def stats(self, request):
        return Response({'total_users': 100, 'active_users': 85})
```

## ModelViewSet Integration

```python
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_smart_ratelimit import rate_limit
from .models import Article
from .serializers import ArticleSerializer

class ArticleViewSet(viewsets.ModelViewSet):
    queryset = Article.objects.all()
    serializer_class = ArticleSerializer
    permission_classes = [IsAuthenticated]

    @rate_limit(key='ip', rate='100/h')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @rate_limit(key='ip', rate='50/h')
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @rate_limit(key='user', rate='10/h')
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @rate_limit(key='user', rate='20/h')
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @rate_limit(key='user', rate='5/h')
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
```

## Authentication Integration

### Token Authentication

```python
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.response import Response
from django_smart_ratelimit import rate_limit

class CustomAuthToken(ObtainAuthToken):
    @rate_limit(key='ip', rate='5/m')
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user_id': user.pk,
            'username': user.username
        })
```

### JWT Authentication

```python
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django_smart_ratelimit import rate_limit

class CustomTokenObtainPairView(TokenObtainPairView):
    @rate_limit(key='ip', rate='10/m')
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

class CustomTokenRefreshView(TokenRefreshView):
    @rate_limit(key='ip', rate='20/m')
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)
```

## Advanced Patterns

### Multi-Level Rate Limiting

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from django_smart_ratelimit import rate_limit

class MultiLevelRateView(APIView):
    @rate_limit(key='ip', rate='1000/h')      # IP-based limit
    @rate_limit(key='user', rate='500/h')     # User-based limit
    @rate_limit(key='endpoint', rate='10000/h')  # Global limit
    def get(self, request):
        return Response({'data': 'Your data'})
```

### Content-Based Rate Limiting

```python
def content_based_rate(request):
    data = request.data or {}
    if data.get('priority') == 'high':
        return '5/h'
    elif data.get('bulk_operation'):
        return '2/h'
    return '20/h'

class ContentBasedRateView(APIView):
    @rate_limit(key='user', rate=content_based_rate)
    def post(self, request):
        return Response({'message': 'Request processed'})
```

## Testing & Best Practices

### Unit Testing

```python
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

class RateLimitedViewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', password='testpass123')

    def test_rate_limit_enforced(self):
        self.client.force_authenticate(user=self.user)

        # Make requests up to the limit
        for i in range(5):  # Assuming 5/h rate limit
            response = self.client.post('/api/test/')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Next request should be rate limited
        response = self.client.post('/api/test/')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_different_users_separate_limits(self):
        user2 = User.objects.create_user(username='testuser2', password='testpass123')

        # User 1 hits rate limit
        self.client.force_authenticate(user=self.user)
        for i in range(5):
            self.client.post('/api/test/')

        # User 2 should still have access
        self.client.force_authenticate(user=user2)
        response = self.client.post('/api/test/')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
```

### Best Practices

1. **Choose Appropriate Rate Limits**

   ```python
   @rate_limit(key='user', rate='100/h')  # Read operations
   @rate_limit(key='user', rate='20/h')   # Write operations
   @rate_limit(key='user', rate='5/h')    # Destructive operations
   ```

2. **Use Smart Key Functions**

   ```python
   def smart_key(request):
       if request.user.is_authenticated:
           return f"user:{request.user.id}"
       return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"
   ```

3. **Implement Graceful Error Handling**

   ```python
   from django_smart_ratelimit.exceptions import RateLimitExceeded

   @rate_limit(key='user', rate='10/h')
   def api_view(request):
       try:
           return Response({'data': 'success'})
       except RateLimitExceeded as e:
           return Response({
               'error': 'Rate limit exceeded',
               'retry_after': e.retry_after
           }, status=429)
   ```

4. **Monitor Rate Limit Usage**

   ```python
   from django_smart_ratelimit import get_backend

   def rate_limit_status(request):
       backend = get_backend()
       key = f"user:{request.user.id}"
       usage_info = backend.get_usage_info(key)
       return Response({
           'remaining_requests': usage_info.get('remaining', 0),
           'reset_time': usage_info.get('reset_time')
       })
   ```

## See Also

- [Decorator Usage Guide](../decorator.md) - Complete decorator documentation
- [Backend Configuration](../backends.md) - Backend setup and configuration
- [Circuit Breaker Pattern](../circuit_breaker.md) - Failure protection for backends
  - Implement health checks
  - Use fallback backends

4. **Performance Issues**
   - Use connection pooling
   - Implement caching
   - Monitor backend performance

### Debug Mode

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('django_smart_ratelimit')

# Add debug info to views
class DebugRateView(APIView):
    @rate_limit(key='user', rate='10/h')
    def get(self, request):
        logger.debug(f"Rate limit check for user: {request.user.id}")
        return Response({'message': 'Debug info logged'})
```

## Getting Help

If you need help with DRF integration:

1. Check the [main documentation](../README.md)
2. Look at the [examples](../../examples/drf_integration/)
3. Visit our [GitHub Discussions](https://github.com/yourusername/django-smart-ratelimit/discussions)
4. Report bugs in [GitHub Issues](https://github.com/yourusername/django-smart-ratelimit/issues)

## Contributing

We welcome contributions to improve DRF integration:

1. Add more examples
2. Improve documentation
3. Report bugs and issues
4. Suggest new features

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for more details.
