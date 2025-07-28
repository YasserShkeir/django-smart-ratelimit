"""
Django REST Framework Permission Integration Examples

This module demonstrates how to integrate Django Smart Ratelimit with DRF
permissions, including rate limiting within permission classes, custom
permissions that consider rate limits, and advanced permission patterns.

Usage:
    from django_smart_ratelimit import rate_limit
    from rest_framework.permissions import BasePermission

    class RateLimitedPermission(BasePermission):
        def has_permission(self, _request: Request, _view: APIView) -> bool:
            # Apply rate limiting within permission check
            return True
"""

from typing import Any

from rest_framework.exceptions import Throttled
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from django.core.cache import cache
from django.utils import timezone


# Example 1: Basic permission with rate limiting
class RateLimitedPermission(BasePermission):
    """
    Basic permission that incorporates rate limiting into permission checks.

    This permission class demonstrates how to integrate rate limiting
    directly into permission logic, allowing for more sophisticated
    access control patterns.
    """

    def has_permission(self, _request: Request, _view: APIView) -> bool:
        """
        Check if user has permission with rate limiting considerations.

        This method combines traditional permission checks with rate limiting
        to provide comprehensive access control.
        """
        # Basic authentication check
        if not _request.user.is_authenticated:
            return False

        # Check rate limits before proceeding with expensive permission checks
        if self._check_rate_limit(_request):
            return self._has_base_permission(_request, _view)

        # Rate limit exceeded
        raise Throttled(detail="Rate limit exceeded for permission check")

    def has_object_permission(
        self, _request: Request, _view: APIView, _obj: Any
    ) -> bool:
        """
        Check object-level permissions with rate limiting.

        This method demonstrates how to apply rate limiting to
        object-level permission checks, which can be expensive.
        """
        # Check rate limits for object permission checks
        if not self._check_object_rate_limit(_request, _obj):
            raise Throttled(detail="Rate limit exceeded for object permission check")

        return self._has_base_object_permission(_request, _view, _obj)

    def _check_rate_limit(self, _request: Request) -> bool:
        """Check general rate limits for permission checks."""
        # In a real implementation, you would use the rate limiting backend
        # to check if the user has exceeded their rate limit
        user_key = f"permission_check:{_request.user.id}"

        # Simulate rate limit check
        current_count = cache.get(user_key, 0)
        if current_count >= 100:  # 100 permission checks per minute
            return False

        cache.set(user_key, current_count + 1, 60)  # 1 minute timeout
        return True

    def _check_object_rate_limit(self, _request: Request, _obj: Any) -> bool:
        """Check rate limits for object permission checks."""
        # Object permission checks might be more expensive
        user_key = f"object_permission_check:{_request.user.id}"

        # Simulate rate limit check with lower limit
        current_count = cache.get(user_key, 0)
        if current_count >= 50:  # 50 object permission checks per minute
            return False

        cache.set(user_key, current_count + 1, 60)
        return True

    def _has_base_permission(self, _request: Request, _view: APIView) -> bool:
        """Base permission logic (expensive operations)."""
        # Simulate expensive permission check
        # This might involve database queries, external API calls, etc.
        return True

    def _has_base_object_permission(
        self, _request: Request, _view: APIView, _obj: Any
    ) -> bool:
        """Base object permission logic (expensive operations)."""
        # Simulate expensive object permission check
        return True


# Example 2: Role-based permission with rate limiting
class RoleBasedRateLimitedPermission(BasePermission):
    """
    Role-based permission that applies different rate limits based on user roles.

    This permission class demonstrates how to apply different rate limits
    based on user characteristics such as role, subscription level, etc.
    """

    # Rate limits per role (requests per minute)
    ROLE_RATE_LIMITS = {
        "admin": 1000,
        "staff": 500,
        "premium": 200,
        "regular": 100,
        "anonymous": 20,
    }

    def has_permission(self, _request: Request, _view: APIView) -> bool:
        """Check permission with role-based rate limiting."""
        user_role = self._get_user_role(_request.user)
        rate_limit_value = self.ROLE_RATE_LIMITS.get(user_role, 50)

        if not self._check_role_rate_limit(_request, user_role, rate_limit_value):
            raise Throttled(detail=f"Rate limit exceeded for {user_role} users")

        return self._has_role_permission(_request, _view, user_role)

    def _get_user_role(self, user: Any) -> str:
        """Determine user role."""
        if not user.is_authenticated:
            return "anonymous"
        elif user.is_superuser:
            return "admin"
        elif user.is_staff:
            return "staff"
        elif hasattr(user, "profile") and user.profile.is_premium:
            return "premium"
        else:
            return "regular"

    def _check_role_rate_limit(self, _request: Request, role: str, limit: int) -> bool:
        """Check rate limit for specific role."""
        if _request.user.is_authenticated:
            rate_key = f"role_rate_limit:{role}:{_request.user.id}"
        else:
            rate_key = f"role_rate_limit:{role}:{_request.META.get('REMOTE_ADDR')}"

        current_count = cache.get(rate_key, 0)
        if current_count >= limit:
            return False

        cache.set(rate_key, current_count + 1, 60)
        return True

    def _has_role_permission(
        self, _request: Request, _view: APIView, role: str
    ) -> bool:
        """Check permissions based on role."""
        # Implement role-based permission logic
        if role == "admin":
            return True
        elif role == "staff":
            return self._check_staff_permissions(_request, _view)
        elif role == "premium":
            return self._check_premium_permissions(_request, _view)
        elif role == "regular":
            return self._check_regular_permissions(_request, _view)
        else:
            return self._check_anonymous_permissions(_request, _view)

    def _check_staff_permissions(self, _request: Request, _view: APIView) -> bool:
        """Check staff-specific permissions."""
        return True

    def _check_premium_permissions(self, _request: Request, _view: APIView) -> bool:
        """Check premium user permissions."""
        return True

    def _check_regular_permissions(self, _request: Request, _view: APIView) -> bool:
        """Check regular user permissions."""
        return True

    def _check_anonymous_permissions(self, _request: Request, _view: APIView) -> bool:
        """Check anonymous user permissions."""
        return _request.method in ["GET", "HEAD", "OPTIONS"]


# Example 3: Resource-specific permission with rate limiting
class ResourceSpecificRateLimitedPermission(BasePermission):
    """
    Permission that applies different rate limits based on the resource being accessed.

    This permission class demonstrates how to apply rate limiting based on
    the specific resource or operation being performed.
    """

    # Rate limits per resource type (requests per minute)
    RESOURCE_RATE_LIMITS = {
        "posts": {"GET": 200, "POST": 10, "PUT": 20, "DELETE": 5},
        "comments": {"GET": 500, "POST": 30, "PUT": 50, "DELETE": 10},
        "users": {"GET": 100, "POST": 5, "PUT": 10, "DELETE": 1},
    }

    def has_permission(self, _request: Request, _view: APIView) -> bool:
        """Check permission with resource-specific rate limiting."""
        resource_type = self._get_resource_type(_view)
        method = _request.method

        rate_limit_value = self.RESOURCE_RATE_LIMITS.get(resource_type, {}).get(
            method, 50
        )

        if not self._check_resource_rate_limit(
            _request, resource_type, method, rate_limit_value
        ):
            raise Throttled(
                detail=f"Rate limit exceeded for {resource_type} {method} operations"
            )

        return self._has_resource_permission(_request, _view, resource_type, method)

    def _get_resource_type(self, _view: APIView) -> str:
        """Determine resource type from _view."""
        # Extract resource type from _view class name or other attributes
        view_name = _view.__class__.__name__.lower()
        if "post" in view_name:
            return "posts"
        elif "comment" in view_name:
            return "comments"
        elif "user" in view_name:
            return "users"
        else:
            return "generic"

    def _check_resource_rate_limit(
        self, _request: Request, resource_type: str, method: str, limit: int
    ) -> bool:
        """Check rate limit for specific resource and method."""
        if _request.user.is_authenticated:
            rate_key = (
                f"resource_rate_limit:{resource_type}:{method}:{_request.user.id}"
            )
        else:
            rate_key = f"resource_rate_limit:{resource_type}:{method}:{_request.META.get('REMOTE_ADDR')}"

        current_count = cache.get(rate_key, 0)
        if current_count >= limit:
            return False

        cache.set(rate_key, current_count + 1, 60)
        return True

    def _has_resource_permission(
        self, _request: Request, _view: APIView, resource_type: str, method: str
    ) -> bool:
        """Check permissions for specific resource and method."""
        # Implement resource-specific permission logic
        if resource_type == "posts":
            return self._check_post_permissions(_request, _view, method)
        elif resource_type == "comments":
            return self._check_comment_permissions(_request, _view, method)
        elif resource_type == "users":
            return self._check_user_permissions(_request, _view, method)
        else:
            return True

    def _check_post_permissions(
        self, _request: Request, _view: APIView, method: str
    ) -> bool:
        """Check post-specific permissions."""
        if method in ["GET", "HEAD", "OPTIONS"]:
            return True
        return _request.user.is_authenticated

    def _check_comment_permissions(
        self, _request: Request, _view: APIView, method: str
    ) -> bool:
        """Check comment-specific permissions."""
        if method in ["GET", "HEAD", "OPTIONS"]:
            return True
        return _request.user.is_authenticated

    def _check_user_permissions(
        self, _request: Request, _view: APIView, method: str
    ) -> bool:
        """Check user-specific permissions."""
        if method in ["GET", "HEAD", "OPTIONS"]:
            return _request.user.is_authenticated
        return _request.user.is_staff


# Example 4: Time-based permission with rate limiting
class TimeBasedRateLimitedPermission(BasePermission):
    """
    Permission that applies different rate limits based on time of day or other temporal factors.

    This permission class demonstrates how to apply rate limiting based on
    temporal conditions such as time of day, day of week, etc.
    """

    # Rate limits per time period (requests per minute)
    TIME_BASED_RATE_LIMITS = {
        "peak_hours": {"authenticated": 50, "anonymous": 10},  # 9 AM - 5 PM
        "off_peak_hours": {"authenticated": 100, "anonymous": 20},  # 5 PM - 9 AM
        "weekend": {"authenticated": 200, "anonymous": 50},
    }

    def has_permission(self, _request: Request, _view: APIView) -> bool:
        """Check permission with time-based rate limiting."""
        time_period = self._get_time_period()
        user_type = "authenticated" if _request.user.is_authenticated else "anonymous"

        rate_limit_value = self.TIME_BASED_RATE_LIMITS.get(time_period, {}).get(
            user_type, 50
        )

        if not self._check_time_based_rate_limit(
            _request, time_period, user_type, rate_limit_value
        ):
            raise Throttled(
                detail=f"Rate limit exceeded for {time_period} during {user_type} access"
            )

        return self._has_time_based_permission(_request, _view, time_period)

    def _get_time_period(self) -> str:
        """Determine current time period."""
        now = timezone.now()

        # Check if it's weekend
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return "weekend"

        # Check if it's peak hours (9 AM - 5 PM)
        if 9 <= now.hour < 17:
            return "peak_hours"
        else:
            return "off_peak_hours"

    def _check_time_based_rate_limit(
        self, _request: Request, time_period: str, user_type: str, limit: int
    ) -> bool:
        """Check rate limit for specific time period and user type."""
        if _request.user.is_authenticated:
            rate_key = f"time_rate_limit:{time_period}:{user_type}:{_request.user.id}"
        else:
            rate_key = f"time_rate_limit:{time_period}:{user_type}:{_request.META.get('REMOTE_ADDR')}"

        current_count = cache.get(rate_key, 0)
        if current_count >= limit:
            return False

        cache.set(rate_key, current_count + 1, 60)
        return True

    def _has_time_based_permission(
        self, _request: Request, _view: APIView, time_period: str
    ) -> bool:
        """Check permissions based on time period."""
        if time_period == "peak_hours":
            # Stricter permissions during peak hours
            return _request.user.is_authenticated and _request.user.is_active
        elif time_period == "off_peak_hours":
            # More lenient permissions during off-peak hours
            return True
        else:  # weekend
            # Special weekend permissions
            return True


# Example 5: Composite permission with multiple rate limits
class CompositeRateLimitedPermission(BasePermission):
    """
    Composite permission that combines multiple rate limiting strategies.

    This permission class demonstrates how to combine multiple rate limiting
    approaches for comprehensive access control.
    """

    def has_permission(self, _request: Request, _view: APIView) -> bool:
        """Check permission with multiple rate limiting strategies."""
        # Apply multiple rate limiting checks
        if not self._check_global_rate_limit(_request):
            raise Throttled(detail="Global rate limit exceeded")

        if not self._check_user_rate_limit(_request):
            raise Throttled(detail="User rate limit exceeded")

        if not self._check_ip_rate_limit(_request):
            raise Throttled(detail="IP rate limit exceeded")

        if not self._check_endpoint_rate_limit(_request, _view):
            raise Throttled(detail="Endpoint rate limit exceeded")

        return self._has_composite_permission(_request, _view)

    def _check_global_rate_limit(self, _request: Request) -> bool:
        """Check global system-wide rate limit."""
        global_key = "global_rate_limit"
        current_count = cache.get(global_key, 0)

        if current_count >= 10000:  # 10,000 requests per minute globally
            return False

        cache.set(global_key, current_count + 1, 60)
        return True

    def _check_user_rate_limit(self, _request: Request) -> bool:
        """Check user-specific rate limit."""
        if not _request.user.is_authenticated:
            return True

        user_key = f"user_rate_limit:{_request.user.id}"
        current_count = cache.get(user_key, 0)

        limit = 1000 if _request.user.is_staff else 200
        if current_count >= limit:
            return False

        cache.set(user_key, current_count + 1, 60)
        return True

    def _check_ip_rate_limit(self, _request: Request) -> bool:
        """Check IP-specific rate limit."""
        ip_address = _request.META.get("REMOTE_ADDR")
        ip_key = f"ip_rate_limit:{ip_address}"
        current_count = cache.get(ip_key, 0)

        if current_count >= 500:  # 500 requests per minute per IP
            return False

        cache.set(ip_key, current_count + 1, 60)
        return True

    def _check_endpoint_rate_limit(self, _request: Request, _view: APIView) -> bool:
        """Check endpoint-specific rate limit."""
        endpoint = f"{_view.__class__.__name__}.{_view.action}"
        endpoint_key = f"endpoint_rate_limit:{endpoint}"
        current_count = cache.get(endpoint_key, 0)

        if current_count >= 2000:  # 2,000 requests per minute per endpoint
            return False

        cache.set(endpoint_key, current_count + 1, 60)
        return True

    def _has_composite_permission(self, _request: Request, _view: APIView) -> bool:
        """Check base permissions after rate limiting."""
        # Implement your base permission logic here
        return True


# Example 6: Adaptive permission with dynamic rate limiting
class AdaptiveRateLimitedPermission(BasePermission):
    """
    Adaptive permission that adjusts rate limits based on system conditions.

    This permission class demonstrates how to implement adaptive rate limiting
    that changes based on system load, user behavior, or other factors.
    """

    def has_permission(self, _request: Request, _view: APIView) -> bool:
        """Check permission with adaptive rate limiting."""
        # Get current system conditions
        system_load = self._get_system_load()
        user_behavior_score = self._get_user_behavior_score(_request.user)

        # Calculate adaptive rate limit
        adaptive_rate_limit = self._calculate_adaptive_rate_limit(
            system_load, user_behavior_score, _request.user
        )

        if not self._check_adaptive_rate_limit(_request, adaptive_rate_limit):
            raise Throttled(detail="Adaptive rate limit exceeded")

        return self._has_adaptive_permission(_request, _view, user_behavior_score)

    def _get_system_load(self) -> float:
        """Get current system load."""
        # In a real implementation, this would check actual system metrics
        # such as CPU usage, memory usage, database load, etc.
        return 0.75  # 75% system load

    def _get_user_behavior_score(self, user: Any) -> float:
        """Get user behavior score."""
        if not user.is_authenticated:
            return 0.5  # Neutral score for anonymous users

        # In a real implementation, this would calculate a score based on:
        # - User's history of legitimate vs. suspicious activity
        # - Account age and verification status
        # - Previous rate limiting violations
        # - User engagement patterns
        return 0.8  # Good user behavior score

    def _calculate_adaptive_rate_limit(
        self, system_load: float, behavior_score: float, user: Any
    ) -> int:
        """Calculate adaptive rate limit based on conditions."""
        base_limit = 100  # Base rate limit

        # Adjust based on system load
        if system_load > 0.8:
            base_limit = int(base_limit * 0.5)  # Reduce limits during high load
        elif system_load < 0.3:
            base_limit = int(base_limit * 1.5)  # Increase limits during low load

        # Adjust based on user behavior
        if behavior_score > 0.8:
            base_limit = int(base_limit * 1.2)  # Increase limits for good users
        elif behavior_score < 0.4:
            base_limit = int(base_limit * 0.6)  # Decrease limits for suspicious users

        # Adjust based on user status
        if user.is_authenticated:
            if user.is_staff:
                base_limit = int(base_limit * 2)  # Higher limits for staff
            elif hasattr(user, "profile") and user.profile.is_premium:
                base_limit = int(base_limit * 1.5)  # Higher limits for premium users

        return max(base_limit, 10)  # Ensure minimum limit

    def _check_adaptive_rate_limit(self, _request: Request, limit: int) -> bool:
        """Check adaptive rate limit."""
        if _request.user.is_authenticated:
            rate_key = f"adaptive_rate_limit:{_request.user.id}"
        else:
            rate_key = f"adaptive_rate_limit:{_request.META.get('REMOTE_ADDR')}"

        current_count = cache.get(rate_key, 0)
        if current_count >= limit:
            return False

        cache.set(rate_key, current_count + 1, 60)
        return True

    def _has_adaptive_permission(
        self, _request: Request, _view: APIView, behavior_score: float
    ) -> bool:
        """Check permissions based on adaptive factors."""
        # Implement adaptive permission logic
        if behavior_score < 0.3:
            # Restrict permissions for users with poor behavior scores
            return False

        return True


# Example 7: Permission with rate limiting bypass
class BypassableRateLimitedPermission(BasePermission):
    """
    Permission that allows bypassing rate limits under certain conditions.

    This permission class demonstrates how to implement rate limiting
    with bypass mechanisms for special cases.
    """

    def has_permission(self, _request: Request, _view: APIView) -> bool:
        """Check permission with bypassable rate limiting."""
        # Check if rate limiting should be bypassed
        if self._should_bypass_rate_limit(_request):
            return self._has_base_permission(_request, _view)

        # Apply normal rate limiting
        if not self._check_rate_limit(_request):
            raise Throttled(detail="Rate limit exceeded")

        return self._has_base_permission(_request, _view)

    def _should_bypass_rate_limit(self, _request: Request) -> bool:
        """Determine if rate limiting should be bypassed."""
        # Bypass for superusers
        if _request.user.is_superuser:
            return True

        # Bypass for internal API calls
        if _request.META.get("HTTP_X_INTERNAL_API") == "true":
            return True

        # Bypass for specific IP addresses (e.g., load balancers, monitoring)
        trusted_ips = ["127.0.0.1", "10.0.0.1"]  # Add your trusted IPs
        if _request.META.get("REMOTE_ADDR") in trusted_ips:
            return True

        # Bypass for specific user agents (e.g., monitoring tools)
        user_agent = _request.META.get("HTTP_USER_AGENT", "")
        if "monitoring" in user_agent.lower():
            return True

        # Bypass for emergency access tokens
        if _request.META.get("HTTP_X_EMERGENCY_TOKEN") == "emergency_access_token":
            return True

        return False

    def _check_rate_limit(self, _request: Request) -> bool:
        """Check normal rate limit."""
        if _request.user.is_authenticated:
            rate_key = f"bypassable_rate_limit:{_request.user.id}"
            limit = 200  # Higher limit for authenticated users
        else:
            rate_key = f"bypassable_rate_limit:{_request.META.get('REMOTE_ADDR')}"
            limit = 50  # Lower limit for anonymous users

        current_count = cache.get(rate_key, 0)
        if current_count >= limit:
            return False

        cache.set(rate_key, current_count + 1, 60)
        return True

    def _has_base_permission(self, _request: Request, _view: APIView) -> bool:
        """Check base permissions."""
        # Implement your base permission logic here
        return True


# Usage Examples and Best Practices

"""
USAGE EXAMPLES:

1. ViewSet Integration:

   from rest_framework import viewsets
   from .permissions import RateLimitedPermission

   class PostViewSet(viewsets.ModelViewSet):
       permission_classes = [RateLimitedPermission]

       def get_permissions(self) -> list[BasePermission]:
           if self.action == 'create':
               return [ResourceSpecificRateLimitedPermission()]
           return super().get_permissions()

2. Custom Permission Classes:

   class CustomPermission(BasePermission):
       def has_permission(self, _request: Request, _view: APIView) -> bool:
           # Apply rate limiting
           if not self._check_rate_limit(_request):
               raise Throttled(detail="Rate limit exceeded")

           # Apply custom permission logic
           return self._has_custom_permission(_request, _view)

3. Combining Multiple Permissions:

   class CombinedPermission(BasePermission):
       def has_permission(self, _request: Request, _view: APIView) -> bool:
           # Apply multiple permission checks
           permissions = [
               RateLimitedPermission(),
               RoleBasedRateLimitedPermission(),
               TimeBasedRateLimitedPermission()
           ]

           for permission in permissions:
               if not permission.has_permission(_request, _view):
                   return False

           return True

4. Dynamic Permission Selection:

   class DynamicPermissionViewSet(viewsets.ModelViewSet):
       def get_permissions(self) -> list[BasePermission]:
           if self.action in ['create', 'update', 'destroy']:
               return [ResourceSpecificRateLimitedPermission()]
           elif self.action == 'list':
               return [TimeBasedRateLimitedPermission()]
           else:
               return [RateLimitedPermission()]

BEST PRACTICES:

1. Layer Your Rate Limiting:
   - Apply global rate limits for system protection
   - Apply user-specific rate limits for fair usage
   - Apply resource-specific rate limits for targeted protection

2. Provide Clear Error Messages:
   - Include information about why the _request was denied
   - Provide guidance on when to retry
   - Include relevant rate limit information

3. Consider Different User Types:
   - Apply different rate limits for authenticated vs. anonymous users
   - Consider user roles and subscription levels
   - Account for legitimate high-volume use cases

4. Monitor and Adjust:
   - Track rate limiting effectiveness
   - Monitor false positives and legitimate blocked requests
   - Adjust limits based on actual usage patterns

5. Handle Edge Cases:
   - Provide bypass mechanisms for emergency access
   - Account for legitimate batch operations
   - Handle system maintenance and monitoring

6. Performance Considerations:
   - Use efficient rate limiting backends (Redis, etc.)
   - Cache permission check results when appropriate
   - Minimize expensive operations in permission checks

7. Security Considerations:
   - Don't leak sensitive information in error messages
   - Log rate limiting events for security monitoring
   - Consider distributed rate limiting for scaled deployments

8. Testing:
   - Test rate limiting under various conditions
   - Test bypass mechanisms
   - Test permission combinations
   - Test with realistic load patterns

9. Documentation:
   - Document rate limiting behavior for API consumers
   - Provide examples of appropriate usage patterns
   - Include rate limit information in API documentation

10. Graceful Degradation:
    - Provide fallback mechanisms when rate limiting backends fail
    - Implement circuit breakers for external dependencies
    - Maintain service availability during rate limiting system issues
"""
