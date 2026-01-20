"""
Leaky Bucket Algorithm implementation for rate limiting.

The leaky bucket algorithm models a bucket that "leaks" at a constant rate.
Requests are added to the bucket, and if the bucket overflows (reaches capacity),
requests are rate limited. This provides smooth, consistent rate limiting.

Key differences from Token Bucket:
- Leaky Bucket: Requests fill the bucket, which drains at constant rate.
                Provides smooth output rate, no bursts allowed.
- Token Bucket: Tokens refill at constant rate, requests consume tokens.
                Allows burst traffic up to bucket capacity.

Use Leaky Bucket when you want to enforce a strict average rate without bursts.
Use Token Bucket when you want to allow bursts while maintaining average rate.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

from .base import RateLimitAlgorithm

logger = logging.getLogger(__name__)


class LeakyBucketAlgorithm(RateLimitAlgorithm):
    """
    Leaky Bucket Algorithm implementation.

    The leaky bucket algorithm maintains a virtual "bucket" that represents
    queued requests. Requests are added to the bucket, and the bucket
    "leaks" (processes requests) at a constant rate. When the bucket is
    full, new requests are rejected.

    This algorithm provides smooth, consistent output rate and prevents
    burst traffic, making it ideal for APIs that need strict rate control.

    Configuration options:
    - bucket_capacity: Maximum size of the bucket (default: same as limit)
    - leak_rate: Requests processed per second (default: limit/period)
    - initial_level: Initial bucket fill level (default: 0)
    - cost_per_request: How much each request fills the bucket (default: 1)

    Example:
        With bucket_capacity=10 and leak_rate=1.0 (1 request/second):
        - If bucket is empty, request is allowed (bucket level becomes 1)
        - If bucket has 9 requests, request is allowed (bucket level becomes 10)
        - If bucket is full (10), request is rejected
        - After 5 seconds, bucket level drops by 5 (leaked out)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize leaky bucket algorithm.

        Args:
            config: Configuration dictionary with algorithm-specific settings
        """
        super().__init__(config)
        self.bucket_capacity = self.config.get("bucket_capacity")
        self.leak_rate = self.config.get("leak_rate")
        self.initial_level = self.config.get("initial_level", 0)
        self.cost_per_request = self.config.get("cost_per_request", 1)

    def is_allowed(
        self, _backend: Any, _key: str, _limit: int, _period: int, **_kwargs: Any
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if request is allowed using leaky bucket algorithm.

        Args:
            _backend: Storage backend instance
            _key: Rate limit key
            _limit: Request limit (used as default bucket capacity)
            _period: Time period in seconds (used to calculate leak rate)
            **_kwargs: Additional parameters including 'request_cost'

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
        bucket_capacity = (
            self.bucket_capacity if self.bucket_capacity is not None else limit
        )
        leak_rate = self.leak_rate or (limit / period)
        request_cost = kwargs.get("request_cost", self.cost_per_request)

        # Handle edge case: zero bucket capacity means no requests allowed
        if bucket_capacity <= 0:
            return False, {
                "bucket_level": 0,
                "bucket_capacity": bucket_capacity,
                "leak_rate": leak_rate,
                "request_cost": request_cost,
                "space_remaining": 0,
                "error": "Invalid bucket capacity",
            }

        # Handle edge case: zero or negative request cost
        if request_cost <= 0:
            return True, {
                "bucket_level": 0,
                "bucket_capacity": bucket_capacity,
                "leak_rate": leak_rate,
                "request_cost": request_cost,
                "space_remaining": bucket_capacity,
                "warning": "No request cost",
            }

        # Use backend-specific implementation if available
        if hasattr(backend, "leaky_bucket_check"):
            return backend.leaky_bucket_check(
                key, bucket_capacity, leak_rate, request_cost
            )
        else:
            # Fallback to generic implementation
            return self._generic_leaky_bucket_check(
                backend, key, bucket_capacity, leak_rate, request_cost
            )

    def get_info(
        self, _backend: Any, _key: str, _limit: int, _period: int, **_kwargs: Any
    ) -> Dict[str, Any]:
        """
        Get current leaky bucket information without adding to the bucket.

        Args:
            _backend: Storage backend instance
            _key: Rate limit key
            _limit: Request limit (used as default bucket capacity)
            _period: Time period in seconds (used to calculate leak rate)
            **_kwargs: Additional parameters

        Returns:
            Dictionary with current leaky bucket state
        """
        # Map parameters to non-prefixed names for consistency
        backend = _backend
        key = _key
        limit = _limit
        period = _period

        bucket_capacity = (
            self.bucket_capacity if self.bucket_capacity is not None else limit
        )
        leak_rate = self.leak_rate or (limit / period)

        if hasattr(backend, "leaky_bucket_info"):
            return backend.leaky_bucket_info(key, bucket_capacity, leak_rate)
        else:
            return self._generic_leaky_bucket_info(
                backend, key, bucket_capacity, leak_rate
            )

    def _generic_leaky_bucket_check(
        self,
        backend: Any,
        key: str,
        bucket_capacity: int,
        leak_rate: float,
        request_cost: int,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Implement generic leaky bucket for backends without native support.

        Note: This implementation is not atomic and should only be used as a fallback.
        For production use, backends should implement atomic leaky bucket operations.
        """
        current_time = self.get_current_time()
        bucket_key = f"{key}:leaky_bucket"

        # Get current bucket state
        try:
            bucket_data_str = backend.get(bucket_key)
            if bucket_data_str:
                bucket_data = json.loads(bucket_data_str)
            else:
                bucket_data = {"level": self.initial_level, "last_leak": current_time}
        except (json.JSONDecodeError, AttributeError):
            bucket_data = {"level": self.initial_level, "last_leak": current_time}

        # Calculate how much has leaked since last update
        time_elapsed = current_time - bucket_data["last_leak"]
        leaked_amount = time_elapsed * leak_rate

        # Update bucket level (cannot go below 0)
        current_level = max(0, bucket_data["level"] - leaked_amount)

        # Check if request can be accepted
        new_level = current_level + request_cost

        if new_level <= bucket_capacity:
            # Request accepted - add to bucket
            new_bucket_data = {"level": new_level, "last_leak": current_time}

            # Set expiration time (bucket empties after level/leak_rate + buffer)
            expiration = (
                int((bucket_capacity / leak_rate) + 60) if leak_rate > 0 else 3600
            )

            try:
                backend.set(bucket_key, json.dumps(new_bucket_data), expiration)
            except Exception:
                # If backend doesn't support expiration, try without it
                backend.set(bucket_key, json.dumps(new_bucket_data))

            space_remaining = bucket_capacity - new_level
            time_until_space = (
                0.0
                if space_remaining > 0
                else (request_cost / leak_rate if leak_rate > 0 else float("inf"))
            )

            return True, {
                "bucket_level": new_level,
                "bucket_capacity": bucket_capacity,
                "leak_rate": leak_rate,
                "request_cost": request_cost,
                "space_remaining": space_remaining,
                "time_until_space": time_until_space,
            }
        else:
            # Bucket would overflow - reject request but update leak time
            bucket_data["level"] = current_level
            bucket_data["last_leak"] = current_time

            expiration = (
                int((bucket_capacity / leak_rate) + 60) if leak_rate > 0 else 3600
            )

            try:
                backend.set(bucket_key, json.dumps(bucket_data), expiration)
            except Exception:
                backend.set(bucket_key, json.dumps(bucket_data))

            # Calculate time until enough space for this request
            overflow = new_level - bucket_capacity
            time_until_space = overflow / leak_rate if leak_rate > 0 else float("inf")

            return False, {
                "bucket_level": current_level,
                "bucket_capacity": bucket_capacity,
                "leak_rate": leak_rate,
                "request_cost": request_cost,
                "space_remaining": max(0, bucket_capacity - current_level),
                "time_until_space": time_until_space,
            }

    def _generic_leaky_bucket_info(
        self, backend: Any, key: str, bucket_capacity: int, leak_rate: float
    ) -> Dict[str, Any]:
        """
        Get leaky bucket info without adding to the bucket.

        Args:
            backend: Storage backend instance
            key: Rate limit key
            bucket_capacity: Maximum bucket size
            leak_rate: Leak rate (requests per second)

        Returns:
            Dictionary with current bucket state
        """
        current_time = self.get_current_time()
        bucket_key = f"{key}:leaky_bucket"

        # Get current bucket state
        try:
            bucket_data_str = backend.get(bucket_key)
            if bucket_data_str:
                bucket_data = json.loads(bucket_data_str)
            else:
                bucket_data = {"level": 0, "last_leak": current_time}
        except (json.JSONDecodeError, AttributeError):
            bucket_data = {"level": 0, "last_leak": current_time}

        # Calculate current level without updating state
        time_elapsed = current_time - bucket_data["last_leak"]
        leaked_amount = time_elapsed * leak_rate
        current_level = max(0, bucket_data["level"] - leaked_amount)

        space_remaining = bucket_capacity - current_level
        time_to_empty = current_level / leak_rate if leak_rate > 0 else 0

        return {
            "bucket_level": current_level,
            "bucket_capacity": bucket_capacity,
            "leak_rate": leak_rate,
            "space_remaining": space_remaining,
            "time_to_empty": time_to_empty,
            "last_leak": bucket_data["last_leak"],
        }

    def reset(self, backend: Any, key: str) -> bool:
        """
        Reset leaky bucket state for a given key.

        Args:
            backend: Storage backend instance
            key: Rate limit key to reset

        Returns:
            True if reset was successful, False otherwise
        """
        bucket_key = f"{key}:leaky_bucket"
        try:
            if hasattr(backend, "delete"):
                return backend.delete(bucket_key)
            return False
        except Exception as e:
            logger.warning(
                f"Failed to reset leaky bucket for key {key}: {e}", exc_info=True
            )
            return False
