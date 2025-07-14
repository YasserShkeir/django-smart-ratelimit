"""
Rate limiting algorithms for Django Smart Ratelimit.

This module provides different algorithms for rate limiting including:
- Token Bucket: Allows burst traffic by maintaining a bucket of tokens
- Sliding Window: Tracks requests in a sliding time window
- Fixed Window: Tracks requests in fixed time windows
"""

from typing import List

from .base import RateLimitAlgorithm
from .token_bucket import TokenBucketAlgorithm

try:
    pass
except ImportError:
    pass

__all__: List[str] = [
    "RateLimitAlgorithm",
    "TokenBucketAlgorithm",
]
