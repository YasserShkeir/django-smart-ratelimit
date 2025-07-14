"""
Token Bucket Algorithm implementation for rate limiting.

The token bucket algorithm allows for burst traffic by maintaining a bucket
of tokens that refill at a steady rate. Each request consumes tokens from
the bucket. When the bucket is empty, requests are rate limited.

This provides more flexible rate limiting compared to fixed window approaches,
as it allows temporary bursts while maintaining an average rate over time.
"""

import json
import math
from typing import Any, Dict, Optional, Tuple

from .base import RateLimitAlgorithm


class TokenBucketAlgorithm(RateLimitAlgorithm):
    """
    Token Bucket Algorithm implementation.

    The token bucket algorithm maintains a virtual "bucket" of tokens that
    refill at a constant rate. Each request consumes one or more tokens.
    When tokens are available, requests are allowed; when the bucket is
    empty, requests are rate limited.

    Configuration options:
    - bucket_size: Maximum number of tokens in bucket (default: same as limit)
    - refill_rate: Tokens added per second (default: limit/period)
    - initial_tokens: Initial tokens in bucket (default: bucket_size)
    - tokens_per_request: Tokens consumed per request (default: 1)
    - allow_partial: Whether to allow partial token consumption (default: False)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize token bucket algorithm.

        Args:
            config: Configuration dictionary with algorithm-specific settings
        """
        super().__init__(config)
        self.bucket_size = self.config.get("bucket_size")
        self.refill_rate = self.config.get("refill_rate")
        self.initial_tokens = self.config.get("initial_tokens")
        self.tokens_per_request = self.config.get("tokens_per_request", 1)
        self.allow_partial = self.config.get("allow_partial", False)

    def is_allowed(
        self, _backend: Any, _key: str, _limit: int, _period: int, **_kwargs: Any
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if request is allowed using token bucket algorithm.

        Args:
            _backend: Storage backend instance
            _key: Rate limit key
            _limit: Request limit (used as default bucket size)
            _period: Time period in seconds (used to calculate refill rate)
            **_kwargs: Additional parameters including 'tokens_requested'

        Returns:
            Tuple of (is_allowed, metadata_dict)
        """
        # Map parameters to non-prefixed names for consistency
        backend = _backend
        key = _key
        limit = _limit
        period = _period
        kwargs = _kwargs
        # Calculate configuration values
        bucket_size = self.bucket_size if self.bucket_size is not None else limit
        refill_rate = self.refill_rate or (limit / period)
        initial_tokens = self.initial_tokens or bucket_size
        tokens_requested = kwargs.get("tokens_requested", self.tokens_per_request)

        # Handle edge case: zero bucket size means no requests allowed
        if bucket_size <= 0:
            return False, {
                "tokens_remaining": 0,
                "tokens_requested": tokens_requested,
                "bucket_size": bucket_size,
                "refill_rate": refill_rate,
                "error": "Invalid bucket size",
            }

        # Handle edge case: zero or negative tokens requested
        if tokens_requested <= 0:
            return True, {
                "tokens_remaining": bucket_size,
                "tokens_requested": tokens_requested,
                "tokens_consumed": 0,
                "bucket_size": bucket_size,
                "refill_rate": refill_rate,
                "warning": "No tokens requested",
            }

        # Use backend-specific implementation if available
        if hasattr(backend, "token_bucket_check"):
            return backend.token_bucket_check(
                key, bucket_size, refill_rate, initial_tokens, tokens_requested
            )
        else:
            # Fallback to generic implementation
            return self._generic_token_bucket_check(
                backend, key, bucket_size, refill_rate, initial_tokens, tokens_requested
            )

    def get_info(
        self, _backend: Any, _key: str, _limit: int, _period: int, **_kwargs: Any
    ) -> Dict[str, Any]:
        """
        Get current token bucket information without consuming tokens.

        Args:
            _backend: Storage backend instance
            _key: Rate limit key
            _limit: Request limit (used as default bucket size)
            _period: Time period in seconds (used to calculate refill rate)
            **_kwargs: Additional parameters

        Returns:
            Dictionary with current token bucket state
        """
        # Map parameters to non-prefixed names for consistency
        backend = _backend
        key = _key
        limit = _limit
        period = _period
        bucket_size = self.bucket_size or limit
        refill_rate = self.refill_rate or (limit / period)

        if hasattr(backend, "token_bucket_info"):
            return backend.token_bucket_info(key, bucket_size, refill_rate)
        else:
            return self._generic_token_bucket_info(
                backend, key, bucket_size, refill_rate
            )

    def _generic_token_bucket_check(
        self,
        backend: Any,
        key: str,
        bucket_size: int,
        refill_rate: float,
        initial_tokens: int,
        tokens_requested: int,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Implement generic token bucket for backends without native support.

        Note: This implementation is not atomic and should only be used as a fallback.
        For production use, backends should implement atomic token bucket operations.
        """
        current_time = self.get_current_time()
        bucket_key = f"{key}:token_bucket"

        # Get current bucket state
        try:
            bucket_data_str = backend.get(bucket_key)
            if bucket_data_str:
                bucket_data = json.loads(bucket_data_str)
            else:
                bucket_data = {"tokens": initial_tokens, "last_refill": current_time}
        except (json.JSONDecodeError, AttributeError):
            bucket_data = {"tokens": initial_tokens, "last_refill": current_time}

        # Calculate tokens to add based on time elapsed
        time_elapsed = current_time - bucket_data["last_refill"]
        tokens_to_add = time_elapsed * refill_rate

        # Update token count (cannot exceed bucket size)
        current_tokens = min(bucket_size, bucket_data["tokens"] + tokens_to_add)

        # Check if request can be served
        if current_tokens >= tokens_requested:
            # Consume tokens
            remaining_tokens = current_tokens - tokens_requested

            # Update bucket state
            new_bucket_data = {"tokens": remaining_tokens, "last_refill": current_time}

            # Set expiration time (tokens expire after bucket could be
            # completely refilled + buffer)
            expiration = (
                int(math.ceil(bucket_size / refill_rate) + 60)
                if refill_rate > 0
                else 3600
            )

            try:
                backend.set(bucket_key, json.dumps(new_bucket_data), expiration)
            except Exception:
                # If backend doesn't support expiration, try without it
                backend.set(bucket_key, json.dumps(new_bucket_data))

            return True, {
                "tokens_remaining": remaining_tokens,
                "tokens_requested": tokens_requested,
                "bucket_size": bucket_size,
                "refill_rate": refill_rate,
                "time_to_refill": (
                    (bucket_size - remaining_tokens) / refill_rate
                    if refill_rate > 0
                    else 0
                ),
            }
        else:
            # Request cannot be served - update last_refill time but don't
            # consume tokens
            bucket_data["tokens"] = current_tokens
            bucket_data["last_refill"] = current_time

            expiration = (
                int(math.ceil(bucket_size / refill_rate) + 60)
                if refill_rate > 0
                else 3600
            )

            try:
                backend.set(bucket_key, json.dumps(bucket_data), expiration)
            except Exception:
                backend.set(bucket_key, json.dumps(bucket_data))

            return False, {
                "tokens_remaining": current_tokens,
                "tokens_requested": tokens_requested,
                "bucket_size": bucket_size,
                "refill_rate": refill_rate,
                "time_to_refill": (
                    (tokens_requested - current_tokens) / refill_rate
                    if refill_rate > 0
                    else 0
                ),
            }

    def _generic_token_bucket_info(
        self, backend: Any, key: str, bucket_size: int, refill_rate: float
    ) -> Dict[str, Any]:
        """
        Get token bucket info without consuming tokens.

        Args:
            backend: Storage backend instance
            key: Rate limit key
            bucket_size: Maximum tokens in bucket
            refill_rate: Tokens added per second

        Returns:
            Dictionary with current bucket state
        """
        current_time = self.get_current_time()
        bucket_key = f"{key}:token_bucket"

        # Get current bucket state
        try:
            bucket_data_str = backend.get(bucket_key)
            if bucket_data_str:
                bucket_data = json.loads(bucket_data_str)
            else:
                bucket_data = {"tokens": bucket_size, "last_refill": current_time}
        except (json.JSONDecodeError, AttributeError):
            bucket_data = {"tokens": bucket_size, "last_refill": current_time}

        # Calculate current tokens without updating state
        time_elapsed = current_time - bucket_data["last_refill"]
        tokens_to_add = time_elapsed * refill_rate
        current_tokens = min(bucket_size, bucket_data["tokens"] + tokens_to_add)

        return {
            "tokens_remaining": current_tokens,
            "bucket_size": bucket_size,
            "refill_rate": refill_rate,
            "time_to_refill": (
                max(0, (bucket_size - current_tokens) / refill_rate)
                if refill_rate > 0
                else 0
            ),
            "last_refill": bucket_data["last_refill"],
        }

    def reset(self, backend: Any, key: str) -> bool:
        """
        Reset token bucket state for a given key.

        Args:
            backend: Storage backend instance
            key: Rate limit key to reset

        Returns:
            True if reset was successful, False otherwise
        """
        bucket_key = f"{key}:token_bucket"
        try:
            if hasattr(backend, "delete"):
                return backend.delete(bucket_key)
            return False
        except Exception:
            return False
