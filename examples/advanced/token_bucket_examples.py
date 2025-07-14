"""
Token Bucket Algorithm Usage Examples

This file demonstrates how to use the token bucket algorithm for rate limiting
with burst capability in Django applications.

The token bucket algorithm allows for temporary bursts of traffic while maintaining
an average rate limit over time, making it ideal for APIs that need to handle
occasional spikes in usage.
"""


from django.http import HttpRequest, HttpResponse, JsonResponse

from django_smart_ratelimit.decorator import rate_limit


# Example 1: Basic token bucket with burst capability
@rate_limit(
    key='api_key:{_request.headers.get("X-API-Key", "anonymous")}',
    rate="100/m",  # 100 requests per minute baseline
    algorithm="token_bucket",
    algorithm_config={
        "bucket_size": 200,  # Allow bursts up to 200 requests
    },
)
def api_endpoint(_request: HttpRequest) -> JsonResponse:
    """API endpoint with burst capability for API key based rate limiting."""
    return JsonResponse(
        {"message": "API response", "data": {"timestamp": "2025-01-01T00:00:00Z"}}
    )


# Example 2: User-based rate limiting with custom refill rate
@rate_limit(
    key="user:{_request.user.id}",
    rate="50/m",  # 50 requests per minute baseline
    algorithm="token_bucket",
    algorithm_config={
        "bucket_size": 100,  # Allow bursts up to 100 requests
        "refill_rate": 2.0,  # Refill at 2 tokens per second (120/minute)
    },
)
def user_dashboard(_request: HttpRequest) -> HttpResponse:
    """User dashboard with generous burst allowance."""
    return HttpResponse(f"Welcome, {_request.user.username}!")


# Example 3: IP-based rate limiting for public endpoints
@rate_limit(
    key='ip:{_request.META.get("REMOTE_ADDR")}',
    rate="10/m",  # 10 requests per minute baseline
    algorithm="token_bucket",
    algorithm_config={
        "bucket_size": 30,  # Allow short bursts
        "initial_tokens": 30,  # Start with full bucket
    },
)
def public_api(_request: HttpRequest) -> JsonResponse:
    """Public API endpoint with burst protection."""
    return JsonResponse({"status": "ok", "public": True})


# Example 4: Premium user with higher limits
@rate_limit(
    key="premium_user:{_request.user.id}",
    rate="500/m",  # 500 requests per minute baseline
    algorithm="token_bucket",
    algorithm_config={
        "bucket_size": 1000,  # Allow large bursts for premium users
        "refill_rate": 10.0,  # Fast refill rate
    },
)
def premium_api(_request: HttpRequest) -> JsonResponse:
    """Premium API with high burst capability."""
    return JsonResponse(
        {"tier": "premium", "rate_limit": "high", "burst_allowed": True}
    )


# Example 5: File upload with token consumption per MB
@rate_limit(
    key="upload:{_request.user.id}",
    rate="100/h",  # 100 MB per hour baseline
    algorithm="token_bucket",
    algorithm_config={
        "bucket_size": 500,  # Allow uploading up to 500 MB in bursts
    },
)
def file_upload(_request: HttpRequest) -> JsonResponse:
    """
    File upload endpoint that consumes tokens based on file size.

    Note: You would need to modify the decorator call to pass
    tokens_requested based on file size in MB.
    """
    # In a real implementation, you'd calculate file size and pass it as tokens_requested
    # For example: tokens_requested = file_size_mb
    return JsonResponse({"upload": "success"})


# Example 6: Different algorithms for comparison
@rate_limit(
    key="comparison_fixed:{_request.user.id}",
    rate="60/m",
    algorithm="fixed_window",  # Traditional fixed window (no bursts)
)
def fixed_window_endpoint(_request: HttpRequest) -> JsonResponse:
    """Endpoint using fixed window (traditional rate limiting)."""
    return JsonResponse({"algorithm": "fixed_window"})


@rate_limit(
    key="comparison_token:{_request.user.id}",
    rate="60/m",
    algorithm="token_bucket",
    algorithm_config={"bucket_size": 120},  # Same rate but with burst capability
)
def token_bucket_endpoint(_request: HttpRequest) -> JsonResponse:
    """Endpoint using token bucket (with burst capability)."""
    return JsonResponse({"algorithm": "token_bucket"})


# Example 7: Conditional rate limiting with skip_if
def is_admin_user(_request: HttpRequest) -> bool:
    """Skip rate limiting for admin users."""
    return hasattr(_request, "user") and _request.user.is_staff


@rate_limit(
    key="api:{_request.user.id}",
    rate="100/m",
    algorithm="token_bucket",
    algorithm_config={"bucket_size": 200},
    skip_if=is_admin_user,
)
def admin_api(_request: HttpRequest) -> JsonResponse:
    """API that skips rate limiting for admin users."""
    return JsonResponse({"admin_access": _request.user.is_staff})


# Example 8: Non-blocking rate limiting (log but don't block)
@rate_limit(
    key="analytics:{_request.user.id}",
    rate="1000/m",
    algorithm="token_bucket",
    algorithm_config={"bucket_size": 2000},
    block=False,  # Don't block requests, just add headers
)
def analytics_endpoint(_request: HttpRequest) -> JsonResponse:
    """
    Analytics endpoint that logs rate limit violations but doesn't block.
    Useful for monitoring and alerting.
    """
    return JsonResponse({"analytics": "data"})


# Example configuration for different backends
"""
# settings.py configuration examples:

# Use Redis backend for production (recommended)
RATELIMIT_BACKEND = 'django_smart_ratelimit.backends.redis_backend.RedisBackend'
RATELIMIT_BACKEND_CONFIG = {
    'redis_url': 'redis://localhost:6379/0',
    'key_prefix': 'rl:',
}

# Use Memory backend for development/testing
RATELIMIT_BACKEND = 'django_smart_ratelimit.backends.memory.MemoryBackend'

# Use Database backend (fallback option)
RATELIMIT_BACKEND = 'django_smart_ratelimit.backends.database.DatabaseBackend'
"""

# Token bucket configuration guidelines:
"""
Token Bucket Configuration Guidelines:

1. bucket_size:
   - Should be larger than your base rate to allow bursts
   - Typical ratio: 1.5x to 3x the base rate
   - For APIs: Consider typical client retry patterns

2. refill_rate:
   - Defaults to limit/period (matches your base rate)
   - Can be set higher for faster recovery
   - Lower values provide more controlled burst recovery

3. initial_tokens:
   - Defaults to bucket_size (start with full bucket)
   - Can be set lower for "warm-up" behavior
   - Useful for new users or rate limit resets

4. Algorithm comparison:
   - fixed_window: Strict limits, no bursts, simple
   - sliding_window: Smooth limiting, no bursts, more complex
   - token_bucket: Allows bursts, flexible, good for APIs

5. Use cases for token bucket:
   - APIs with bursty traffic patterns
   - File uploads/downloads
   - Batch processing endpoints
   - User-facing applications with temporary spikes
   - Premium tiers with higher burst allowances
"""
