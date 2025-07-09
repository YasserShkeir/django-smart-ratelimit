# Django REST Framework (DRF) Integration Guide

This guide provides comprehensive instructions for integrating Django Smart Ratelimit with Django REST Framework, including examples for different DRF patterns, authentication, and advanced use cases.

## Table of Contents

- [Quick Start](#quick-start)
- [APIView Integration](#apiview-integration)
- [ViewSet Integration](#viewset-integration)
- [ModelViewSet Integration](#modelviewset-integration)
- [Serializer Integration](#serializer-integration)
- [Permission Integration](#permission-integration)
- [Authentication Integration](#authentication-integration)
- [Pagination and Filtering](#pagination-and-filtering)
- [Advanced Patterns](#advanced-patterns)
- [Testing DRF Integration](#testing-drf-integration)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Quick Start

### Basic Setup

First, ensure you have both Django REST Framework and Django Smart Ratelimit installed:

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

Configure rate limiting in your settings:

```python
RATELIMIT_BACKEND = 'django_smart_ratelimit.backends.redis_backend.RedisBackend'
RATELIMIT_BACKEND_OPTIONS = {
    'CONNECTION_POOL_KWARGS': {
        'host': 'localhost',
        'port': 6379,
        'db': 0,
    }
}
```

### Simple APIView Example

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from django_smart_ratelimit.decorator import rate_limit

class UserListView(APIView):
    @rate_limit(key='ip', rate='10/m')
    def get(self, request):
        return Response({'users': []})

    @rate_limit(key='user', rate='5/m')
    def post(self, request):
        return Response({'message': 'User created'})
```

## APIView Integration

### Basic APIView Rate Limiting

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django_smart_ratelimit.decorator import rate_limit

class ProductAPIView(APIView):
    """
    APIView with different rate limits for different HTTP methods
    """

    @rate_limit(key='ip', rate='100/h')
    def get(self, request):
        """Get products - higher rate limit for read operations"""
        products = [
            {'id': 1, 'name': 'Product 1'},
            {'id': 2, 'name': 'Product 2'},
        ]
        return Response(products)

    @rate_limit(key='user', rate='10/h')
    def post(self, request):
        """Create product - lower rate limit for write operations"""
        # Product creation logic here
        return Response(
            {'message': 'Product created successfully'},
            status=status.HTTP_201_CREATED
        )

    @rate_limit(key='user', rate='5/h')
    def put(self, request):
        """Update product - restrictive rate limit"""
        # Product update logic here
        return Response({'message': 'Product updated'})

    @rate_limit(key='user', rate='2/h')
    def delete(self, request):
        """Delete product - very restrictive rate limit"""
        # Product deletion logic here
        return Response(status=status.HTTP_204_NO_CONTENT)
```

### Dynamic Rate Limiting Based on User Type

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from django_smart_ratelimit.decorator import rate_limit

def get_user_rate(request):
    """Custom rate function based on user type"""
    if not request.user.is_authenticated:
        return '10/h'  # Anonymous users
    elif request.user.is_staff:
        return '1000/h'  # Staff users
    elif hasattr(request.user, 'profile') and request.user.profile.is_premium:
        return '500/h'  # Premium users
    else:
        return '100/h'  # Regular users

class DynamicRateAPIView(APIView):
    @rate_limit(key='user_or_ip', rate=get_user_rate)
    def get(self, request):
        return Response({'data': 'Your data here'})
```

## ViewSet Integration

### Basic ViewSet Rate Limiting

```python
from rest_framework import viewsets
from rest_framework.response import Response
from django_smart_ratelimit.decorator import rate_limit

class UserViewSet(viewsets.ViewSet):
    """
    ViewSet with method-specific rate limiting
    """

    @rate_limit(key='ip', rate='50/h')
    def list(self, request):
        """List users"""
        return Response([
            {'id': 1, 'username': 'user1'},
            {'id': 2, 'username': 'user2'},
        ])

    @rate_limit(key='ip', rate='20/h')
    def retrieve(self, request, pk=None):
        """Retrieve specific user"""
        return Response({'id': pk, 'username': f'user{pk}'})

    @rate_limit(key='user', rate='5/h')
    def create(self, request):
        """Create new user"""
        return Response({'message': 'User created'})

    @rate_limit(key='user', rate='10/h')
    def update(self, request, pk=None):
        """Update user"""
        return Response({'message': f'User {pk} updated'})

    @rate_limit(key='user', rate='2/h')
    def destroy(self, request, pk=None):
        """Delete user"""
        return Response({'message': f'User {pk} deleted'})
```

### Custom Actions in ViewSets

```python
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django_smart_ratelimit.decorator import rate_limit

class UserViewSet(viewsets.ViewSet):

    @action(detail=True)
    @rate_limit(key='user', rate='3/h')
    def set_password(self, request, pk=None):
        """Custom action with rate limiting"""
        # Password setting logic
        return Response({'message': 'Password updated'})

    @action(detail=False)
    @rate_limit(key='ip', rate='30/h')
    def stats(self, request):
        """Get user statistics"""
        return Response({'total_users': 100, 'active_users': 85})

    @action(detail=True)
    @rate_limit(key='user', rate='1/d')
    def send_welcome_email(self, request, pk=None):
        """Send welcome email - once per day limit"""
        # Email sending logic
        return Response({'message': 'Welcome email sent'})
```

## ModelViewSet Integration

### Basic ModelViewSet with Rate Limiting

```python
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_smart_ratelimit.decorator import rate_limit
from .models import Article
from .serializers import ArticleSerializer

class ArticleViewSet(viewsets.ModelViewSet):
    """
    ModelViewSet with comprehensive rate limiting
    """
    queryset = Article.objects.all()
    serializer_class = ArticleSerializer
    permission_classes = [IsAuthenticated]

    @rate_limit(key='ip', rate='100/h')
    def list(self, request, *args, **kwargs):
        """List articles with rate limiting"""
        return super().list(request, *args, **kwargs)

    @rate_limit(key='ip', rate='50/h')
    def retrieve(self, request, *args, **kwargs):
        """Retrieve article with rate limiting"""
        return super().retrieve(request, *args, **kwargs)

    @rate_limit(key='user', rate='10/h')
    def create(self, request, *args, **kwargs):
        """Create article with rate limiting"""
        return super().create(request, *args, **kwargs)

    @rate_limit(key='user', rate='20/h')
    def update(self, request, *args, **kwargs):
        """Update article with rate limiting"""
        return super().update(request, *args, **kwargs)

    @rate_limit(key='user', rate='20/h')
    def partial_update(self, request, *args, **kwargs):
        """Partially update article with rate limiting"""
        return super().partial_update(request, *args, **kwargs)

    @rate_limit(key='user', rate='5/h')
    def destroy(self, request, *args, **kwargs):
        """Delete article with rate limiting"""
        return super().destroy(request, *args, **kwargs)
```

### ModelViewSet with Custom Key Functions

```python
from rest_framework import viewsets
from django_smart_ratelimit.decorator import rate_limit
from .models import Comment
from .serializers import CommentSerializer

def comment_key(request, *args, **kwargs):
    """Custom key function for comments"""
    if request.user.is_authenticated:
        return f"user:{request.user.id}"
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer

    @rate_limit(key=comment_key, rate='50/h')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @rate_limit(key=comment_key, rate='20/h')
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)
```

## Serializer Integration

### Rate Limiting in Serializer Methods

```python
from rest_framework import serializers
from django_smart_ratelimit.decorator import rate_limit
from .models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']

    def validate_email(self, value):
        """Validate email with rate limiting"""
        # Email validation logic
        return value

    @rate_limit(key='user', rate='5/h')
    def create(self, validated_data):
        """Create user with rate limiting"""
        return super().create(validated_data)

    @rate_limit(key='user', rate='10/h')
    def update(self, instance, validated_data):
        """Update user with rate limiting"""
        return super().update(instance, validated_data)

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm']

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError("Passwords don't match")
        return attrs

    @rate_limit(key='ip', rate='3/h')
    def create(self, validated_data):
        """Create user with strict rate limiting for registration"""
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User.objects.create_user(**validated_data)
        user.set_password(password)
        user.save()
        return user
```

### Serializer with Nested Rate Limiting

```python
from rest_framework import serializers
from django_smart_ratelimit.decorator import rate_limit
from .models import Post, Comment

class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ['id', 'content', 'created_at', 'author']
        read_only_fields = ['id', 'created_at', 'author']

    @rate_limit(key='user', rate='30/h')
    def create(self, validated_data):
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)

class PostSerializer(serializers.ModelSerializer):
    comments = CommentSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = ['id', 'title', 'content', 'created_at', 'author', 'comments']
        read_only_fields = ['id', 'created_at', 'author']

    @rate_limit(key='user', rate='10/h')
    def create(self, validated_data):
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)
```

## Permission Integration

### Custom Permission with Rate Limiting

```python
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied
from django_smart_ratelimit.decorator import rate_limit
from django_smart_ratelimit.backends import get_backend

class RateLimitedPermission(permissions.BasePermission):
    """
    Permission that includes rate limiting logic
    """

    def has_permission(self, request, view):
        # Check basic permission first
        if not request.user.is_authenticated:
            return False

        # Check rate limit
        backend = get_backend()
        key = f"user:{request.user.id}"
        rate = '100/h'

        if not backend.check_rate_limit(key, rate):
            raise PermissionDenied("Rate limit exceeded")

        return True

class AdminRateLimitedPermission(permissions.BasePermission):
    """
    Permission for admin users with higher rate limits
    """

    def has_permission(self, request, view):
        if not request.user.is_staff:
            return False

        backend = get_backend()
        key = f"admin:{request.user.id}"
        rate = '1000/h'  # Higher limit for admin users

        if not backend.check_rate_limit(key, rate):
            raise PermissionDenied("Admin rate limit exceeded")

        return True
```

### Permission Classes with Rate Limiting

```python
from rest_framework import permissions
from django_smart_ratelimit.decorator import rate_limit

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Permission that allows owners to edit their own objects
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions for any request
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions only for owner
        return obj.owner == request.user

# Usage in ViewSet
class DocumentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOwnerOrReadOnly]

    @rate_limit(key='user', rate='50/h')
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @rate_limit(key='user', rate='10/h')
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)
```

## Authentication Integration

### Token Authentication with Rate Limiting

```python
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from django_smart_ratelimit.decorator import rate_limit

class CustomAuthToken(ObtainAuthToken):
    @rate_limit(key='ip', rate='5/m')
    def post(self, request, *args, **kwargs):
        """Rate limited token authentication"""
        serializer = self.serializer_class(data=request.data,
                                           context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user_id': user.pk,
            'username': user.username
        })
```

### JWT Authentication with Rate Limiting

```python
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django_smart_ratelimit.decorator import rate_limit

class CustomTokenObtainPairView(TokenObtainPairView):
    @rate_limit(key='ip', rate='10/m')
    def post(self, request, *args, **kwargs):
        """Rate limited JWT token obtain"""
        return super().post(request, *args, **kwargs)

class CustomTokenRefreshView(TokenRefreshView):
    @rate_limit(key='ip', rate='20/m')
    def post(self, request, *args, **kwargs):
        """Rate limited JWT token refresh"""
        return super().post(request, *args, **kwargs)
```

### Session Authentication with Rate Limiting

```python
from django.contrib.auth import authenticate, login, logout
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django_smart_ratelimit.decorator import rate_limit

class LoginView(APIView):
    @rate_limit(key='ip', rate='5/m')
    def post(self, request):
        """Rate limited login"""
        username = request.data.get('username')
        password = request.data.get('password')

        if username and password:
            user = authenticate(username=username, password=password)
            if user:
                login(request, user)
                return Response({'message': 'Login successful'})

        return Response(
            {'error': 'Invalid credentials'},
            status=status.HTTP_401_UNAUTHORIZED
        )

class LogoutView(APIView):
    @rate_limit(key='user', rate='10/m')
    def post(self, request):
        """Rate limited logout"""
        logout(request)
        return Response({'message': 'Logout successful'})
```

## Pagination and Filtering

### Pagination with Rate Limiting

```python
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from django_smart_ratelimit.decorator import rate_limit

class CustomPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

class PaginatedListView(APIView):
    pagination_class = CustomPagination

    @rate_limit(key='ip', rate='100/h')
    def get(self, request):
        """Paginated list with rate limiting"""
        # Your data fetching logic here
        data = list(range(1, 101))  # Example data

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(data, request)

        if page is not None:
            return paginator.get_paginated_response(page)

        return Response(data)
```

### Filtering with Rate Limiting

```python
from django_filters import rest_framework as filters
from rest_framework import viewsets
from django_smart_ratelimit.decorator import rate_limit
from .models import Product

class ProductFilter(filters.FilterSet):
    name = filters.CharFilter(lookup_expr='icontains')
    price_min = filters.NumberFilter(field_name='price', lookup_expr='gte')
    price_max = filters.NumberFilter(field_name='price', lookup_expr='lte')

    class Meta:
        model = Product
        fields = ['name', 'category', 'price_min', 'price_max']

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    filterset_class = ProductFilter

    @rate_limit(key='ip', rate='200/h')
    def list(self, request, *args, **kwargs):
        """Filtered list with rate limiting"""
        return super().list(request, *args, **kwargs)
```

## Advanced Patterns

### Rate Limiting Based on Request Content

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from django_smart_ratelimit.decorator import rate_limit

def content_based_rate(request):
    """Rate limiting based on request content"""
    data = request.data or {}
    if data.get('priority') == 'high':
        return '5/h'  # Lower rate for high priority
    elif data.get('bulk_operation'):
        return '2/h'  # Very low rate for bulk operations
    return '20/h'  # Default rate

class ContentBasedRateView(APIView):
    @rate_limit(key='user', rate=content_based_rate)
    def post(self, request):
        return Response({'message': 'Request processed'})
```

### Multi-Level Rate Limiting

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from django_smart_ratelimit.decorator import rate_limit

class MultiLevelRateView(APIView):
    @rate_limit(key='ip', rate='1000/h')  # IP-based limit
    @rate_limit(key='user', rate='500/h')  # User-based limit
    @rate_limit(key='endpoint', rate='10000/h')  # Global limit
    def get(self, request):
        """Multi-level rate limiting"""
        return Response({'data': 'Your data'})
```

### Rate Limiting with Custom Headers

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from django_smart_ratelimit.decorator import rate_limit

def api_key_rate(request):
    """Rate limiting based on API key"""
    api_key = request.headers.get('X-API-Key')
    if api_key in ['premium_key_1', 'premium_key_2']:
        return '1000/h'
    elif api_key:
        return '100/h'
    return '10/h'  # No API key

class APIKeyRateView(APIView):
    @rate_limit(key='header:X-API-Key', rate=api_key_rate)
    def get(self, request):
        return Response({'message': 'API response'})
```

## Testing DRF Integration

### Unit Tests for Rate Limited Views

```python
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from django_smart_ratelimit.backends import get_backend

class RateLimitedViewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.backend = get_backend()

    def test_rate_limit_enforced(self):
        """Test that rate limits are enforced"""
        self.client.force_authenticate(user=self.user)

        # Make requests up to the limit
        for i in range(5):  # Assuming 5/h rate limit
            response = self.client.post('/api/test/')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Next request should be rate limited
        response = self.client.post('/api/test/')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_different_users_separate_limits(self):
        """Test that different users have separate rate limits"""
        user2 = User.objects.create_user(
            username='testuser2',
            password='testpass123'
        )

        # User 1 hits rate limit
        self.client.force_authenticate(user=self.user)
        for i in range(5):
            response = self.client.post('/api/test/')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # User 2 should still have access
        self.client.force_authenticate(user=user2)
        response = self.client.post('/api/test/')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_rate_limit_reset(self):
        """Test that rate limits reset after time period"""
        self.client.force_authenticate(user=self.user)

        # Hit rate limit
        for i in range(5):
            response = self.client.post('/api/test/')

        # Clear rate limit (for testing)
        self.backend.clear_rate_limit(f'user:{self.user.id}')

        # Should be able to make requests again
        response = self.client.post('/api/test/')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
```

### Integration Tests

```python
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth.models import User
from unittest.mock import patch

class DRFIntegrationTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_viewset_rate_limiting(self):
        """Test rate limiting in ViewSet"""
        self.client.force_authenticate(user=self.user)

        # Test list view rate limiting
        for i in range(100):  # Assuming 100/h rate limit
            response = self.client.get('/api/articles/')
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Next request should be rate limited
        response = self.client.get('/api/articles/')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_authentication_rate_limiting(self):
        """Test authentication endpoint rate limiting"""
        # Try to authenticate multiple times
        for i in range(5):  # Assuming 5/m rate limit
            response = self.client.post('/api/auth/login/', {
                'username': 'testuser',
                'password': 'testpass123'
            })
            self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

        # Next request should be rate limited
        response = self.client.post('/api/auth/login/', {
            'username': 'testuser',
            'password': 'testpass123'
        })
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @patch('django_smart_ratelimit.backends.redis_backend.RedisBackend.check_rate_limit')
    def test_backend_failure_handling(self, mock_check):
        """Test handling of backend failures"""
        mock_check.side_effect = Exception('Backend error')

        self.client.force_authenticate(user=self.user)

        # Should still work when backend fails (graceful degradation)
        response = self.client.get('/api/articles/')
        # Depending on configuration, should either allow or deny
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_503_SERVICE_UNAVAILABLE])
```

## Best Practices

### 1. Choose Appropriate Rate Limits

```python
# Good: Different limits for different operations
@rate_limit(key='user', rate='100/h')  # Read operations
@rate_limit(key='user', rate='20/h')  # Write operations
@rate_limit(key='user', rate='5/h')  # Destructive operations
```

### 2. Use Custom Key Functions

```python
def smart_key(request):
    """Smart key function that handles various scenarios"""
    if request.user.is_authenticated:
        # Use user ID for authenticated users
        return f"user:{request.user.id}"
    else:
        # Use IP for anonymous users
        return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"
```

### 3. Implement Graceful Error Handling

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django_smart_ratelimit.decorator import rate_limit
from django_smart_ratelimit.exceptions import RateLimitExceeded

class GracefulAPIView(APIView):
    @rate_limit(key='user', rate='10/h')
    def get(self, request):
        try:
            # Your API logic here
            return Response({'data': 'success'})
        except RateLimitExceeded as e:
            return Response(
                {
                    'error': 'Rate limit exceeded',
                    'retry_after': e.retry_after,
                    'message': 'Please try again later'
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
```

### 4. Monitor Rate Limit Usage

```python
from django_smart_ratelimit.backends import get_backend
from rest_framework.views import APIView
from rest_framework.response import Response

class RateLimitStatusView(APIView):
    def get(self, request):
        """Get rate limit status for current user"""
        backend = get_backend()
        key = f"user:{request.user.id}"

        # Get current usage (implementation depends on backend)
        usage_info = backend.get_usage_info(key)

        return Response({
            'remaining_requests': usage_info.get('remaining', 0),
            'reset_time': usage_info.get('reset_time'),
            'limit': usage_info.get('limit')
        })
```

### 5. Use Proper HTTP Status Codes

```python
from rest_framework import status
from rest_framework.response import Response

class ProperStatusAPIView(APIView):
    @rate_limit(key='user', rate='10/h')
    def post(self, request):
        # Return appropriate status codes
        if not request.data:
            return Response(
                {'error': 'No data provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Process request
        return Response(
            {'message': 'Created successfully'},
            status=status.HTTP_201_CREATED
        )
```

## Troubleshooting

### Common Issues

1. **Rate Limits Not Working**

   - Check that middleware is properly configured
   - Verify backend configuration
   - Ensure decorator is applied correctly

2. **Too Restrictive Limits**

   - Monitor actual usage patterns
   - Adjust limits based on user feedback
   - Consider different limits for different user types

3. **Backend Connection Issues**

   - Check Redis/database connectivity
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
