"""
Rate limiting algorithms for Django Smart Ratelimit.

This module provides different algorithms for rate limiting including:
- Token Bucket: Allows burst traffic by maintaining a bucket of tokens
- Leaky Bucket: Smooths traffic by processing at constant rate (no bursts)
- Sliding Window: Tracks requests in a sliding time window
- Fixed Window: Tracks requests in fixed time windows
"""

from typing import List

from .base import RateLimitAlgorithm
from .leaky_bucket import LeakyBucketAlgorithm
from .token_bucket import TokenBucketAlgorithm

__all__: List[str] = [
    "RateLimitAlgorithm",
    "TokenBucketAlgorithm",
    "LeakyBucketAlgorithm",
]
