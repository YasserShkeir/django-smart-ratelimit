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

__version__ = "1.0.0"
__author__ = "Django Smart Ratelimit Team"

# Import key classes for convenience
try:
    from .permissions import (
        AdaptiveRateLimitedPermission,
        BypassableRateLimitedPermission,
        CompositeRateLimitedPermission,
        RateLimitedPermission,
        ResourceSpecificRateLimitedPermission,
        RoleBasedRateLimitedPermission,
        TimeBasedRateLimitedPermission,
    )
    from .serializers import (
        AdvancedPostSerializer,
        BulkPostItemSerializer,
        BulkPostSerializer,
        CommentSerializer,
        ConditionalRateLimitSerializer,
        ExternalAPISerializer,
        FieldRateLimitedSerializer,
        PostSerializer,
        RateLimitedPostSerializer,
    )
    from .viewsets import (
        AdvancedPostViewSet,
        CommentViewSet,
        ConditionalRateLimitViewSet,
        CustomErrorHandlingViewSet,
        MonitoredViewSet,
        MultiBackendViewSet,
        PostViewSet,
    )

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
