"""
Django REST Framework Integration Package

This package provides comprehensive examples and patterns for integrating
Django Smart Ratelimit with Django REST Framework (DRF).

Modules:
- viewsets: Examples of rate limiting in DRF ViewSets
- serializers: Examples of rate limiting in DRF Serializers
- permissions: Examples of rate limiting in DRF Permissions

Usage:
    from examples.drf_integration.viewsets import PostViewSet
    from examples.drf_integration.serializers import PostSerializer
    from examples.drf_integration.permissions import RateLimitedPermission

    # Use in your Django project
    router = DefaultRouter()
    router.register(r'posts', PostViewSet)
"""

__version__ = "0.7.6"
__author__ = "Django Smart Ratelimit Team"

# Import key classes for convenience
try:
    pass

    __all__ = [
        # ViewSets
        "PostViewSet",
        "AdvancedPostViewSet",
        "CommentViewSet",
        "MultiBackendViewSet",
        "ConditionalRateLimitViewSet",
        "CustomErrorHandlingViewSet",
        "MonitoredViewSet",
        # Serializers
        "PostSerializer",
        "AdvancedPostSerializer",
        "CommentSerializer",
        "RateLimitedPostSerializer",
        "ConditionalRateLimitSerializer",
        "FieldRateLimitedSerializer",
        "BulkPostSerializer",
        "BulkPostItemSerializer",
        "ExternalAPISerializer",
        # Permissions
        "RateLimitedPermission",
        "RoleBasedRateLimitedPermission",
        "ResourceSpecificRateLimitedPermission",
        "TimeBasedRateLimitedPermission",
        "CompositeRateLimitedPermission",
        "AdaptiveRateLimitedPermission",
        "BypassableRateLimitedPermission",
    ]

except ImportError:
    # DRF not installed, which is fine for documentation purposes
    __all__ = []
