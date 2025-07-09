"""
Django REST Framework ViewSet Integration Examples

This module demonstrates how to integrate Django Smart Ratelimit with various
DRF ViewSet patterns, including ModelViewSet, custom ViewSets, and advanced
rate limiting scenarios.

Usage:
    from django_smart_ratelimit.decorator import rate_limit
    from rest_framework import viewsets

    class MyViewSet(viewsets.ModelViewSet):
        @rate_limit(key='ip', rate='10/m')
        def list(self, request):
            return super().list(request)
"""

from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer

from django.contrib.auth.models import User
from django.db.models import Q
from django.http import Http404
from django.utils.decorators import method_decorator

from django_smart_ratelimit.decorator import rate_limit


# Mock models for examples (replace with your actual models)
class Post:
    """Mock Post model for examples"""

    def __init__(self, id=1, title="Sample Post", content="Content", author=None):
        self.id = id
        self.title = title
        self.content = content
        self.author = author


class Comment:
    """Mock Comment model for examples"""

    def __init__(self, id=1, content="Comment", post=None, author=None):
        self.id = id
        self.content = content
        self.post = post
        self.author = author


# Mock serializers (replace with your actual serializers)
class PostSerializer(ModelSerializer):
    class Meta:
        model = Post
        fields = ["id", "title", "content", "author"]


class CommentSerializer(ModelSerializer):
    class Meta:
        model = Comment
        fields = ["id", "content", "post", "author"]


# Custom pagination class
class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


# Example 1: Basic ModelViewSet with method-specific rate limiting
class PostViewSet(viewsets.ModelViewSet):
    """
    A ViewSet for managing posts with different rate limits per method.

    Rate limiting strategy:
    - List: 100 requests per minute per IP
    - Create: 10 requests per minute per user
    - Update/Delete: 20 requests per minute per user
    - Retrieve: 200 requests per minute per IP
    """

    # queryset = Post.objects.all()  # Uncomment when using real models
    serializer_class = PostSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsSetPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "content"]
    ordering_fields = ["id", "title"]

    def get_queryset(self):
        """Mock queryset - replace with actual implementation"""
        return [Post(id=i, title=f"Post {i}") for i in range(1, 21)]

    @rate_limit(key="ip", rate="100/m")
    def list(self, request, *args, **kwargs):
        """List posts with IP-based rate limiting"""
        return Response(
            [
                {
                    "id": 1,
                    "title": "Sample Post",
                    "content": "This is a sample post",
                    "author": "admin",
                }
            ]
        )

    @rate_limit(key="user", rate="200/m")
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single post with user-based rate limiting"""
        return Response(
            {
                "id": kwargs.get("pk", 1),
                "title": "Sample Post",
                "content": "This is a sample post",
                "author": "admin",
            }
        )

    @rate_limit(key="user", rate="10/m")
    def create(self, request, *args, **kwargs):
        """Create a new post with user-based rate limiting"""
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            # Mock creation logic
            return Response(
                {
                    "id": 999,
                    "title": request.data.get("title", "New Post"),
                    "content": request.data.get("content", "New content"),
                    "author": str(request.user),
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @rate_limit(key="user", rate="20/m")
    def update(self, request, *args, **kwargs):
        """Update a post with user-based rate limiting"""
        return Response(
            {
                "id": kwargs.get("pk", 1),
                "title": request.data.get("title", "Updated Post"),
                "content": request.data.get("content", "Updated content"),
                "author": str(request.user),
            }
        )

    @rate_limit(key="user", rate="20/m")
    def destroy(self, request, *args, **kwargs):
        """Delete a post with user-based rate limiting"""
        return Response(status=status.HTTP_204_NO_CONTENT)


# Example 2: Advanced ViewSet with custom key functions and dynamic rates
class AdvancedPostViewSet(viewsets.ModelViewSet):
    """
    Advanced ViewSet with custom key functions, dynamic rates, and custom actions.

    Features:
    - Custom key functions for different rate limiting strategies
    - Dynamic rate adjustment based on user roles
    - Custom actions with specific rate limits
    - Conditional rate limiting based on request parameters
    """

    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Mock queryset - replace with actual implementation"""
        return [Post(id=i, title=f"Post {i}") for i in range(1, 21)]

    def user_or_ip_key(self, group, request):
        """Custom key function: use user ID if authenticated, otherwise IP"""
        return (
            str(request.user.id)
            if request.user.is_authenticated
            else request.META.get("REMOTE_ADDR")
        )

    def user_role_key(self, group, request):
        """Custom key function: combine user ID with role"""
        if request.user.is_authenticated:
            role = "admin" if request.user.is_staff else "user"
            return f"{request.user.id}:{role}"
        return request.META.get("REMOTE_ADDR")

    def get_user_rate(self, request):
        """Dynamic rate based on user role"""
        if request.user.is_staff:
            return "100/m"  # Staff get higher limits
        elif request.user.is_authenticated:
            return "50/m"  # Regular users
        else:
            return "10/m"  # Anonymous users

    @rate_limit(key="ip", rate="50/m")
    def list(self, request, *args, **kwargs):
        """List with IP-based rate limiting"""
        return Response(
            [
                {
                    "id": 1,
                    "title": "Advanced Post",
                    "content": "Advanced content",
                    "author": "admin",
                }
            ]
        )

    @rate_limit(key=user_or_ip_key, rate="30/m")
    def create(self, request, *args, **kwargs):
        """Create with custom key function"""
        return Response(
            {
                "id": 999,
                "title": request.data.get("title", "New Advanced Post"),
                "content": request.data.get("content", "New advanced content"),
                "author": str(request.user),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True)
    @rate_limit(key="user", rate="5/m")
    def like(self, request, pk=None):
        """Custom action: like a post"""
        return Response({"message": f"Post {pk} liked by {request.user}", "likes": 42})

    @action(detail=True)
    @rate_limit(key=user_role_key, rate="10/m")
    def share(self, request, pk=None):
        """Custom action: share a post with role-based rate limiting"""
        return Response(
            {"message": f"Post {pk} shared by {request.user}", "shares": 15}
        )

    @action(detail=False)
    @rate_limit(key="ip", rate="20/m")
    def trending(self, request):
        """Custom action: get trending posts"""
        return Response(
            [
                {"id": 1, "title": "Trending Post 1", "views": 1000},
                {"id": 2, "title": "Trending Post 2", "views": 800},
            ]
        )

    @action(detail=False)
    @rate_limit(key="user", rate="3/m")
    def report_content(self, request):
        """Custom action: report inappropriate content"""
        return Response(
            {"message": "Content reported successfully", "report_id": 12345}
        )


# Example 3: ViewSet with hierarchical rate limiting
class CommentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for comments with hierarchical and usage-based rate limiting.

    Rate limiting strategy:
    - Different rates for different comment types
    - Hierarchical limiting (per-post and global)
    - Usage-based limiting (posting frequency affects limits)
    """

    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Mock queryset - replace with actual implementation"""
        return [Comment(id=i, content=f"Comment {i}") for i in range(1, 51)]

    def post_comment_key(self, group, request):
        """Key function for per-post comment limiting"""
        post_id = request.data.get("post") or request.parser_context.get(
            "kwargs", {}
        ).get("post_id")
        return f"post:{post_id}:user:{request.user.id}"

    def user_activity_key(self, group, request):
        """Key function for user activity-based limiting"""
        return f"user:{request.user.id}:activity"

    @rate_limit(key="user", rate="100/h")
    def list(self, request, *args, **kwargs):
        """List comments with hourly rate limiting"""
        return Response(
            [
                {
                    "id": 1,
                    "content": "This is a sample comment",
                    "post": 1,
                    "author": "user1",
                }
            ]
        )

    @rate_limit(key=post_comment_key, rate="10/h")
    @rate_limit(key="user", rate="50/h")  # Global user limit
    def create(self, request, *args, **kwargs):
        """Create comment with hierarchical rate limiting"""
        return Response(
            {
                "id": 999,
                "content": request.data.get("content", "New comment"),
                "post": request.data.get("post", 1),
                "author": str(request.user),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True)
    @rate_limit(key="user", rate="20/h")
    def reply(self, request, pk=None):
        """Reply to a comment"""
        return Response(
            {
                "id": 1000,
                "content": request.data.get("content", "Reply content"),
                "parent_comment": pk,
                "author": str(request.user),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False)
    @rate_limit(key="user", rate="30/m")
    def my_comments(self, request):
        """Get user's own comments"""
        return Response(
            [{"id": 1, "content": "My comment", "post": 1, "author": str(request.user)}]
        )


# Example 4: ViewSet with multi-backend support
@method_decorator(rate_limit(key="ip", rate="100/m"), name="list")
@method_decorator(rate_limit(key="user", rate="50/m"), name="create")
class MultiBackendViewSet(viewsets.ModelViewSet):
    """
    ViewSet configured to work with multiple rate limiting backends.

    This example shows how to configure your ViewSet to work with
    the multi-backend system for high availability.
    """

    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Mock queryset - replace with actual implementation"""
        return [Post(id=i, title=f"Multi-backend Post {i}") for i in range(1, 21)]


# Example 5: ViewSet with conditional rate limiting
class ConditionalRateLimitViewSet(viewsets.ModelViewSet):
    """
    ViewSet with conditional rate limiting based on request parameters,
    user attributes, or other conditions.
    """

    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Mock queryset - replace with actual implementation"""
        return [Post(id=i, title=f"Conditional Post {i}") for i in range(1, 21)]

    def conditional_key(self, group, request):
        """Conditional key function based on request parameters"""
        if request.GET.get("priority") == "high":
            return f"priority:high:user:{request.user.id}"
        return f"normal:user:{request.user.id}"

    def should_rate_limit(self, request):
        """Determine if rate limiting should be applied"""
        # Skip rate limiting for staff users
        if request.user.is_staff:
            return False
        # Skip rate limiting for internal API calls
        if request.META.get("HTTP_X_INTERNAL_API") == "true":
            return False
        return True

    @rate_limit(key=conditional_key, rate="20/m")
    def list(self, request, *args, **kwargs):
        """List with conditional rate limiting"""
        if not self.should_rate_limit(request):
            # Bypass rate limiting for certain conditions
            pass

        return Response(
            [
                {
                    "id": 1,
                    "title": "Conditional Post",
                    "content": "Content with conditional rate limiting",
                    "author": "admin",
                }
            ]
        )

    @action(detail=False)
    def bulk_create(self, request):
        """Bulk create with different rate limits based on batch size"""
        batch_size = len(request.data) if isinstance(request.data, list) else 1

        # Apply different rate limits based on batch size
        if batch_size > 10:
            # Use stricter rate limiting for large batches
            rate_limit_key = f"bulk_large:user:{request.user.id}"
            # Note: In a real implementation, you would apply rate limiting here
        else:
            # Use normal rate limiting for small batches
            rate_limit_key = f"bulk_small:user:{request.user.id}"
            # In a real implementation, you would use this key for rate limiting
            # For now, we'll just log it or use it in some other way
            print(f"Rate limit key: {rate_limit_key}")

        return Response(
            {
                "message": f"Bulk created {batch_size} items",
                "created_count": batch_size,
            },
            status=status.HTTP_201_CREATED,
        )


# Example 6: ViewSet with custom error handling
class CustomErrorHandlingViewSet(viewsets.ModelViewSet):
    """
    ViewSet with custom error handling for rate limiting.

    Shows how to customize the response when rate limits are exceeded.
    """

    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Mock queryset - replace with actual implementation"""
        return [Post(id=i, title=f"Error Handling Post {i}") for i in range(1, 21)]

    def handle_rate_limit_exceeded(self, request, exception):
        """Custom handler for rate limit exceeded"""
        return Response(
            {
                "error": "Rate limit exceeded",
                "message": "You have exceeded the allowed number of requests. Please try again later.",
                "retry_after": 60,  # seconds
                "limit_info": {
                    "rate": "50/m",
                    "method": request.method,
                    "endpoint": request.path,
                },
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    @rate_limit(key="user", rate="50/m")
    def list(self, request, *args, **kwargs):
        """List with custom error handling"""
        try:
            return Response(
                [
                    {
                        "id": 1,
                        "title": "Error Handling Post",
                        "content": "Post with custom error handling",
                        "author": "admin",
                    }
                ]
            )
        except Exception as e:
            # Handle rate limiting exceptions
            if "rate limit" in str(e).lower():
                return self.handle_rate_limit_exceeded(request, e)
            raise


# Example 7: ViewSet with monitoring and metrics
class MonitoredViewSet(viewsets.ModelViewSet):
    """
    ViewSet with built-in monitoring and metrics for rate limiting.

    This example shows how to add monitoring and logging to track
    rate limiting effectiveness and usage patterns.
    """

    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Mock queryset - replace with actual implementation"""
        return [Post(id=i, title=f"Monitored Post {i}") for i in range(1, 21)]

    def log_rate_limit_event(self, request, action, remaining_requests=None):
        """Log rate limiting events for monitoring"""
        import logging

        logger = logging.getLogger("django_smart_ratelimit")

        logger.info(
            f"Rate limit event: {action}",
            extra={
                "user": str(request.user),
                "ip": request.META.get("REMOTE_ADDR"),
                "method": request.method,
                "path": request.path,
                "remaining_requests": remaining_requests,
                "timestamp": request.META.get("HTTP_X_REQUEST_START"),
            },
        )

    @rate_limit(key="user", rate="100/m")
    def list(self, request, *args, **kwargs):
        """List with monitoring"""
        # Log the request
        self.log_rate_limit_event(request, "list_accessed")

        return Response(
            [
                {
                    "id": 1,
                    "title": "Monitored Post",
                    "content": "Post with monitoring",
                    "author": "admin",
                }
            ]
        )

    @action(detail=False)
    @rate_limit(key="user", rate="20/m")
    def statistics(self, request):
        """Get rate limiting statistics"""
        return Response(
            {
                "user_limits": {
                    "current_usage": "15/100",
                    "reset_time": "2024-01-01T12:00:00Z",
                },
                "global_limits": {"requests_per_minute": 1000, "current_load": "75%"},
            }
        )


# Usage Examples and Best Practices

"""
USAGE EXAMPLES:

1. URL Configuration:

   from django.urls import path, include
   from rest_framework.routers import DefaultRouter
   from .views import PostViewSet, CommentViewSet

   router = DefaultRouter()
   router.register(r'posts', PostViewSet)
   router.register(r'comments', CommentViewSet)

   urlpatterns = [
       path('api/', include(router.urls)),
   ]

2. Settings Configuration:

   # settings.py
   RATELIMIT_BACKEND = 'django_smart_ratelimit.backends.redis_backend.RedisBackend'
   RATELIMIT_BACKEND_OPTIONS = {
       'CONNECTION_POOL_KWARGS': {
           'host': 'localhost',
           'port': 6379,
           'db': 0,
       }
   }

   # For multi-backend setup
   RATELIMIT_BACKEND = 'django_smart_ratelimit.backends.multi.MultiBackend'
   RATELIMIT_BACKEND_OPTIONS = {
       'BACKENDS': [
           {
               'BACKEND': 'django_smart_ratelimit.backends.redis_backend.RedisBackend',
               'OPTIONS': {...}
           },
           {
               'BACKEND': 'django_smart_ratelimit.backends.database.DatabaseBackend',
               'OPTIONS': {...}
           }
       ]
   }

3. Testing Rate Limits:

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

BEST PRACTICES:

1. Choose appropriate rate limiting strategies:
   - Use IP-based limiting for public endpoints
   - Use user-based limiting for authenticated endpoints
   - Combine both for comprehensive protection

2. Set reasonable limits:
   - Start with generous limits and adjust based on usage patterns
   - Consider different limits for different user roles
   - Account for legitimate use cases (batch operations, etc.)

3. Provide clear error messages:
   - Include information about when the user can retry
   - Explain the rate limiting policy
   - Provide contact information for questions

4. Monitor and adjust:
   - Log rate limiting events for analysis
   - Monitor false positives and legitimate blocked requests
   - Adjust limits based on actual usage patterns

5. Consider performance:
   - Use Redis for high-performance scenarios
   - Consider multi-backend setups for high availability
   - Implement proper caching strategies

6. Handle edge cases:
   - Account for clock skew in distributed systems
   - Handle backend failures gracefully
   - Provide fallback mechanisms

7. Documentation:
   - Document your rate limiting policies
   - Provide examples for API consumers
   - Include rate limit information in API responses (headers)
"""
