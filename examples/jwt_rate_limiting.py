#!/usr/bin/env python3
"""
JWT-based Rate Limiting Examples

This demonstrates rate limiting based on JWT tokens for API authentication.
JWT tokens allow rate limiting based on user identity, roles, subscription tiers,
and other claims embedded in the token.

🎯 Why JWT Rate Limiting?
- Rate limit per authenticated user (not just IP address)
- Different limits for different user roles (admin/user/guest)
- Subscription-based limits (free/premium/enterprise tiers)
- API key management with embedded rate limit information
- Service-to-service authentication with specific quotas

📦 Installation:
    pip install django-smart-ratelimit[jwt]
    # or manually: pip install PyJWT

⚠️  Security Note:
This example shows patterns for JWT-based rate limiting.
In production, always properly validate JWT signatures and handle errors.

🔧 Configuration:
Add to your Django settings.py:
    JWT_SECRET_KEY = 'your-secret-key-here'
    RATELIMIT_BACKEND = {'backend': 'redis'}  # Recommended for JWT patterns
"""

import base64
import json
from datetime import datetime, timedelta

from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from django_smart_ratelimit import rate_limit

# JWT dependency handling
# Install with: pip install django-smart-ratelimit[jwt]
# or manually: pip install PyJWT
try:
    import jwt  # PyJWT library - handles JSON Web Tokens

    JWT_AVAILABLE = True
except ImportError:
    # JWT is optional - examples will fallback to basic token parsing
    JWT_AVAILABLE = False

    # Create a mock jwt module for demonstration
    class MockJWT:
        @staticmethod
        def decode(*args, **kwargs):
            raise ImportError("PyJWT not installed")

        @staticmethod
        def encode(*args, **kwargs):
            return "mock_token_install_pyjwt"

    jwt = MockJWT()


# Example 1: JWT Subject-based rate limiting
def jwt_subject_key(request, *args, **kwargs):
    """
    Extract user ID from JWT token for rate limiting.

    This allows rate limiting based on the authenticated user
    identified by the JWT token's subject claim.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ")[1]

            # In production, properly verify the JWT signature
            # This is a simplified example for demonstration
            if hasattr(settings, "JWT_SECRET_KEY") and JWT_AVAILABLE:
                # Proper JWT validation
                payload = jwt.decode(
                    token, settings.JWT_SECRET_KEY, algorithms=["HS256"]
                )
                return f"jwt_sub:{payload.get('sub', 'unknown')}"
            else:
                # Decode without verification (for example only)
                payload_part = token.split(".")[1]
                # Add padding if needed
                payload_part += "=" * (4 - len(payload_part) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_part))
                return f"jwt_sub:{payload.get('sub', 'unknown')}"
        except Exception:
            pass

    # Fallback to IP-based limiting
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=jwt_subject_key, rate="200/h")
def jwt_protected_api(request):
    """
    JWT-protected API with token-based rate limiting.

    Users with valid JWT tokens get 200 requests per hour.
    Users without tokens are limited by IP address.
    """
    auth_header = request.headers.get("Authorization", "")
    has_token = auth_header.startswith("Bearer ")

    return JsonResponse(
        {
            "protected_data": "JWT-protected endpoint",
            "has_token": has_token,
            "rate_limit": "200/hour with JWT token, or IP-based limit without",
        }
    )


# Example 2: Role-based rate limiting
def jwt_role_key(request, *args, **kwargs):
    """
    Extract user role from JWT token for role-based rate limiting.

    This allows different rate limits for different user roles.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ")[1]

            # Decode JWT (simplified for example)
            payload_part = token.split(".")[1]
            payload_part += "=" * (4 - len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part))

            # Get role from JWT claims
            role = payload.get("role", "user")
            user_id = payload.get("sub", "unknown")

            return f"role:{role}:user:{user_id}"
        except Exception:
            pass

    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=jwt_role_key, rate="1000/h")  # Admin rate limit
def admin_api(request):
    """
    Admin API with role-based rate limiting.

    Different roles get different rate limits:
    - Admin: 1000/hour
    - Premium: 500/hour
    - Regular: 100/hour
    """
    auth_header = request.headers.get("Authorization", "")
    role = "anonymous"

    if auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ")[1]
            payload_part = token.split(".")[1]
            payload_part += "=" * (4 - len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part))
            role = payload.get("role", "user")
        except Exception:
            pass

    return JsonResponse(
        {
            "admin_data": "Role-based protected endpoint",
            "user_role": role,
            "rate_limit": "Varies by role: admin=1000/h, premium=500/h, user=100/h",
        }
    )


# Example 3: Multi-tier rate limiting based on JWT claims
def jwt_tier_key(request, *args, **kwargs):
    """
    Extract subscription tier from JWT token for tiered rate limiting.

    This allows rate limiting based on subscription level.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ")[1]
            payload_part = token.split(".")[1]
            payload_part += "=" * (4 - len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part))

            # Get subscription tier from JWT claims
            tier = payload.get("tier", "free")
            user_id = payload.get("sub", "unknown")

            return f"tier:{tier}:user:{user_id}"
        except Exception:
            pass

    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


class TieredAPIView(View):
    """
    Class-based view with tiered rate limiting.

    Different subscription tiers get different rate limits.
    """

    @method_decorator(csrf_exempt)
    @method_decorator(rate_limit(key=jwt_tier_key, rate="5000/h"))  # Enterprise
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        """GET endpoint with tiered rate limiting."""
        auth_header = request.headers.get("Authorization", "")
        tier = "free"

        if auth_header.startswith("Bearer "):
            try:
                token = auth_header.split(" ")[1]
                payload_part = token.split(".")[1]
                payload_part += "=" * (4 - len(payload_part) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_part))
                tier = payload.get("tier", "free")
            except Exception:
                pass

        return JsonResponse(
            {
                "tiered_data": "Subscription tier-based endpoint",
                "subscription_tier": tier,
                "rate_limits": {
                    "free": "100/hour",
                    "premium": "1000/hour",
                    "enterprise": "5000/hour",
                },
            }
        )


# Example 4: JWT with refresh token rate limiting
def jwt_refresh_key(request, *args, **kwargs):
    """
    Special key function for JWT refresh endpoints.

    This provides strict rate limiting for token refresh operations.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ")[1]
            payload_part = token.split(".")[1]
            payload_part += "=" * (4 - len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part))

            user_id = payload.get("sub", "unknown")
            return f"refresh:user:{user_id}"
        except Exception:
            pass

    return f"refresh:ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@csrf_exempt
@rate_limit(key=jwt_refresh_key, rate="10/h")  # Strict limit for refresh
def jwt_refresh_token(request):
    """
    JWT refresh token endpoint with strict rate limiting.

    Token refresh is limited to 10 times per hour per user.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # Mock token refresh logic
    if JWT_AVAILABLE:
        new_token = jwt.encode(
            {
                "sub": "user123",
                "exp": datetime.utcnow() + timedelta(hours=1),
                "iat": datetime.utcnow(),
                "role": "user",
                "tier": "premium",
            },
            "secret_key",
            algorithm="HS256",
        )
    else:
        new_token = "mock_token_jwt_not_available"

    return JsonResponse(
        {
            "access_token": new_token,
            "token_type": "bearer",
            "expires_in": 3600,
            "rate_limit": "10 refresh attempts per hour",
        }
    )


# Example 5: Custom JWT validation with rate limiting
def validate_jwt_and_get_key(request, *args, **kwargs):
    """
    Custom JWT validation with comprehensive rate limiting key generation.

    This function validates JWT tokens and creates appropriate rate limiting keys.
    """
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

    try:
        token = auth_header.split(" ")[1]

        # Validate JWT token
        if hasattr(settings, "JWT_SECRET_KEY") and JWT_AVAILABLE:
            payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        else:
            # Decode without verification (example only)
            payload_part = token.split(".")[1]
            payload_part += "=" * (4 - len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part))

        # Check if token is expired
        exp = payload.get("exp")
        if exp and datetime.utcfromtimestamp(exp) < datetime.utcnow():
            return f"expired:ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

        # Create comprehensive key
        user_id = payload.get("sub", "unknown")
        role = payload.get("role", "user")
        tier = payload.get("tier", "free")

        return f"validated:user:{user_id}:role:{role}:tier:{tier}"

    except jwt.ExpiredSignatureError:
        return f"expired:ip:{request.META.get('REMOTE_ADDR', 'unknown')}"
    except jwt.InvalidTokenError:
        return f"invalid:ip:{request.META.get('REMOTE_ADDR', 'unknown')}"
    except Exception:
        return f"error:ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(key=validate_jwt_and_get_key, rate="2000/h")
def comprehensive_jwt_api(request):
    """
    Comprehensive JWT API with full validation and rate limiting.

    This endpoint demonstrates complete JWT handling with rate limiting.
    """
    key = validate_jwt_and_get_key(request)

    # Determine user status from key
    if key.startswith("validated:"):
        status = "authenticated"
        parts = key.split(":")
        user_id = parts[2] if len(parts) > 2 else "unknown"
        role = parts[4] if len(parts) > 4 else "user"
        tier = parts[6] if len(parts) > 6 else "free"
    elif key.startswith("expired:"):
        status = "expired_token"
        user_id = role = tier = None
    elif key.startswith("invalid:"):
        status = "invalid_token"
        user_id = role = tier = None
    else:
        status = "no_token"
        user_id = role = tier = None

    return JsonResponse(
        {
            "status": status,
            "user_id": user_id,
            "role": role,
            "tier": tier,
            "rate_limit_key": key,
            "comprehensive_data": "Fully validated JWT endpoint",
        }
    )


# Example: JWT-based rate limiting with algorithm and skip_if
def jwt_admin_check(request, *args, **kwargs):
    """
    Check if JWT token contains admin role for bypassing rate limits.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ")[1]

            # Decode JWT (simplified for example)
            payload_part = token.split(".")[1]
            payload_part += "=" * (4 - len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part))

            # Check if user has admin role
            roles = payload.get("roles", [])
            return "admin" in roles
        except Exception:
            pass

    return False


@rate_limit(
    key=jwt_subject_key,
    rate="100/h",
    algorithm="sliding_window",
    skip_if=jwt_admin_check,
)
def jwt_api_with_admin_bypass(request):
    """
    JWT API with admin bypass and sliding window algorithm.

    Regular users are limited to 100 requests per hour with smooth
    distribution. Admin users bypass rate limiting entirely.
    """
    auth_header = request.headers.get("Authorization", "")
    is_admin = jwt_admin_check(request)

    return JsonResponse(
        {
            "data": "JWT API with admin bypass",
            "has_token": auth_header.startswith("Bearer "),
            "is_admin": is_admin,
            "algorithm": "sliding_window",
            "rate_limit": "No limit for admin, 100/h sliding window for others",
        }
    )


# Example: Role-based rate limiting with different algorithms
def jwt_role_key(request, *args, **kwargs):
    """
    Generate rate limiting key based on JWT role.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ")[1]
            payload_part = token.split(".")[1]
            payload_part += "=" * (4 - len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part))

            user_id = payload.get("sub", "unknown")
            roles = payload.get("roles", ["user"])
            primary_role = roles[0] if roles else "user"

            return f"jwt_role:{primary_role}:user:{user_id}"
        except Exception:
            pass

    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"


@rate_limit(
    key=jwt_role_key,
    rate="1000/h",
    algorithm="fixed_window",
    skip_if=lambda request: "premium" in str(jwt_role_key(request)),
)
def jwt_role_based_api(request):
    """
    JWT API with role-based rate limiting.

    Different roles get different limits, premium users bypass limits.
    Uses fixed window to allow burst requests for batch operations.
    """
    role_key = jwt_role_key(request)
    is_premium = "premium" in role_key

    return JsonResponse(
        {
            "data": "Role-based JWT rate limiting",
            "role_key": role_key,
            "is_premium": is_premium,
            "algorithm": "fixed_window",
            "rate_limit": "No limit for premium, 1000/h fixed window for others",
        }
    )


# Django URLs configuration example
"""
# urls.py

from django.urls import path
from . import jwt_rate_limiting

urlpatterns = [
    # JWT-based rate limiting
    path('api/jwt/protected/', jwt_rate_limiting.jwt_protected_api, name='jwt_protected'),
    path('api/jwt/admin/', jwt_rate_limiting.admin_api, name='jwt_admin'),
    path('api/jwt/tiered/', jwt_rate_limiting.TieredAPIView.as_view(), name='jwt_tiered'),
    path('api/jwt/refresh/', jwt_rate_limiting.jwt_refresh_token, name='jwt_refresh'),
    path('api/jwt/comprehensive/', jwt_rate_limiting.comprehensive_jwt_api, name='jwt_comprehensive'),
]
"""

# Django settings configuration example
"""
# settings.py

# JWT Configuration
JWT_SECRET_KEY = 'your-secret-key-here'
JWT_ALGORITHM = 'HS256'
JWT_ACCESS_TOKEN_LIFETIME = 3600  # 1 hour
JWT_REFRESH_TOKEN_LIFETIME = 86400  # 24 hours

# Rate limiting for different JWT tiers
RATELIMIT_MIDDLEWARE = {
    'DEFAULT_RATE': '100/h',
    'BACKEND': 'redis',
    'BLOCK': True,
    'RATE_LIMITS': {
        # JWT-based endpoints
        '/api/jwt/protected/': '200/h',
        '/api/jwt/admin/': '1000/h',
        '/api/jwt/tiered/': '5000/h',
        '/api/jwt/refresh/': '10/h',
        '/api/jwt/comprehensive/': '2000/h',
    },
}
"""

if __name__ == "__main__":
    print("JWT Rate Limiting Examples")
    print("=" * 40)
    print("This file demonstrates JWT-based rate limiting patterns.")
    print("Install required packages: pip install PyJWT")
    print("Configure JWT_SECRET_KEY in your Django settings.")
