"""
Redis backend for rate limiting using sliding window algorithm.

This backend uses Redis with Lua scripts to implement atomic sliding window
rate limiting with high performance and accuracy.
"""

import time
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseBackend
from .utils import (
    deserialize_data,
    estimate_backend_memory_usage,
    format_lua_script,
    format_token_bucket_metadata,
    log_backend_operation,
    normalize_key,
    retry_backend_operation,
    serialize_data,
    validate_backend_config,
)

try:
    import redis
except ImportError:
    redis = None


class RedisBackend(BaseBackend):
    """
    Redis backend implementation using sliding window algorithm.

    This backend uses a Lua script to atomically manage sliding window
    counters with automatic cleanup of expired entries.
    """

    # Lua script for sliding window rate limiting
    SLIDING_WINDOW_SCRIPT = """
        local key = KEYS[1]
        local window = tonumber(ARGV[1])
        local limit = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])

        -- Remove expired entries
        redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

        -- Get current count
        local current = redis.call('ZCARD', key)

        if current < limit then
            -- Add current request
            redis.call('ZADD', key, now, now .. ':' .. math.random())
            -- Set expiration
            redis.call('EXPIRE', key, window)
            return current + 1
        else
            return current + 1
        end
    """

    # Lua script for fixed window rate limiting
    # (simpler, more memory efficient)
    FIXED_WINDOW_SCRIPT = """
        local key = KEYS[1]
        local window = tonumber(ARGV[1])
        local limit = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])

        -- Get current count
        local current = redis.call('GET', key)
        if current == false then
            current = 0
        else
            current = tonumber(current)
        end

        -- Increment and set expiration
        local new_count = redis.call('INCR', key)
        if new_count == 1 then
            redis.call('EXPIRE', key, window)
        end

        return new_count
    """

    # Lua script for token bucket algorithm
    TOKEN_BUCKET_SCRIPT = """
        local key = KEYS[1]
        local bucket_size = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local initial_tokens = tonumber(ARGV[3])
        local tokens_requested = tonumber(ARGV[4])
        local current_time = tonumber(ARGV[5])

        -- Get current bucket state
        local bucket_data = redis.call('HMGET', key, 'tokens', 'last_refill')
        local current_tokens = tonumber(bucket_data[1]) or initial_tokens
        local last_refill = tonumber(bucket_data[2]) or current_time

        -- Calculate tokens to add based on time elapsed
        local time_elapsed = current_time - last_refill
        local tokens_to_add = time_elapsed * refill_rate
        current_tokens = math.min(bucket_size, current_tokens + tokens_to_add)

        -- Check if request can be served
        if current_tokens >= tokens_requested then
            -- Consume tokens
            local remaining_tokens = current_tokens - tokens_requested
            redis.call('HMSET', key, 'tokens', remaining_tokens, 'last_refill',
                      current_time)

            -- Set expiration (bucket expires after it could be completely
            -- refilled + buffer)
            local expiration = math.ceil(bucket_size / refill_rate) + 60
            redis.call('EXPIRE', key, expiration)

            -- Return success with metadata
            return {1, remaining_tokens, bucket_size, refill_rate,
                   (bucket_size - remaining_tokens) / refill_rate}
        else
            -- Update last_refill time even if request is denied
            redis.call('HMSET', key, 'tokens', current_tokens, 'last_refill',
                      current_time)

            local expiration = math.ceil(bucket_size / refill_rate) + 60
            redis.call('EXPIRE', key, expiration)

            -- Return failure with metadata
            return {0, current_tokens, bucket_size, refill_rate,
                   (tokens_requested - current_tokens) / refill_rate}
        end
    """  # nosec B105

    # Lua script for token bucket info (without consuming tokens)
    TOKEN_BUCKET_INFO_SCRIPT = """
        local key = KEYS[1]
        local bucket_size = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local current_time = tonumber(ARGV[3])

        -- Get current bucket state
        local bucket_data = redis.call('HMGET', key, 'tokens', 'last_refill')
        local current_tokens = tonumber(bucket_data[1]) or bucket_size
        local last_refill = tonumber(bucket_data[2]) or current_time

        -- Calculate current tokens without updating state
        local time_elapsed = current_time - last_refill
        local tokens_to_add = time_elapsed * refill_rate
        current_tokens = math.min(bucket_size, current_tokens + tokens_to_add)

        -- Return current state
        return {current_tokens, bucket_size, refill_rate,
               math.max(0, (bucket_size - current_tokens) / refill_rate), last_refill}
    """  # nosec B105

    def __init__(
        self,
        enable_circuit_breaker: bool = True,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the Redis backend with connection and scripts."""
        # Initialize parent class with circuit breaker
        super().__init__(enable_circuit_breaker, circuit_breaker_config)

        if redis is None:
            raise ImproperlyConfigured(
                "Redis backend requires the redis package. "
                "Install it with: pip install redis"
            )

        # Get Redis configuration with validation
        redis_config = getattr(settings, "RATELIMIT_REDIS", {})

        # Validate configuration using utility
        validate_backend_config(redis_config, backend_type="redis")

        # Default configuration
        config = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
            "password": None,
            "socket_timeout": 5,
            "socket_connect_timeout": 5,
            "decode_responses": True,
            **redis_config,
        }

        # Initialize Redis connection with retry support
        @retry_backend_operation(max_retries=3, delay=1.0)
        def _connect_redis():
            redis_client = redis.Redis(**config)
            redis_client.ping()  # Test connection
            return redis_client

        try:
            self.redis = _connect_redis()
        except Exception as e:
            raise ImproperlyConfigured(f"Cannot connect to Redis: {e}") from e

        # Load and cache Lua scripts using utility
        self.sliding_window_sha = self._load_script(self.SLIDING_WINDOW_SCRIPT)
        self.fixed_window_sha = self._load_script(self.FIXED_WINDOW_SCRIPT)
        self.token_bucket_sha = self._load_script(self.TOKEN_BUCKET_SCRIPT)
        self.token_bucket_info_sha = self._load_script(self.TOKEN_BUCKET_INFO_SCRIPT)

        # Configuration
        self.algorithm = getattr(settings, "RATELIMIT_ALGORITHM", "sliding_window")
        self.key_prefix = getattr(settings, "RATELIMIT_KEY_PREFIX", "ratelimit:")

        # Log initialization
        log_backend_operation(
            "redis_init",
            f"Redis backend initialized with {self.algorithm} algorithm",
            level="info",
        )

    def _load_script(self, script_content: str) -> str:
        """Load and cache a Lua script using utility formatting."""
        formatted_script = format_lua_script(script_content)
        return self.redis.script_load(formatted_script)

    def incr(self, key: str, period: int) -> int:
        """
        Increment the counter for the given key within the time period.

        Uses either sliding window or fixed window algorithm based on
        configuration.
        """
        # Normalize key using utility
        normalized_key = normalize_key(key, self.key_prefix)
        now = time.time()

        # Log operation start
        start_time = time.time()

        try:
            if self.algorithm == "sliding_window":
                # Use sliding window algorithm
                count = self.redis.evalsha(
                    self.sliding_window_sha,
                    1,
                    normalized_key,
                    period,
                    999999,  # We'll check the limit in Python for flexibility
                    now,
                )
            else:
                # Use fixed window algorithm (default for unknown algorithms)
                count = self.redis.evalsha(
                    self.fixed_window_sha,
                    1,
                    normalized_key,
                    period,
                    999999,  # We'll check the limit in Python for flexibility
                    now,
                )

            # Log successful operation
            log_backend_operation(
                "redis_incr",
                f"Incremented key {key} to count {count}",
                duration=time.time() - start_time,
            )

            return count

        except Exception as e:
            # Log error
            log_backend_operation(
                "redis_incr_error",
                f"Failed to increment key {key}: {e}",
                duration=time.time() - start_time,
                level="error",
            )
            raise

    def reset(self, key: str) -> None:
        """Reset the counter for the given key."""
        normalized_key = normalize_key(key, self.key_prefix)

        start_time = time.time()
        try:
            self.redis.delete(normalized_key)
            log_backend_operation(
                "redis_reset", f"Reset key {key}", duration=time.time() - start_time
            )
        except Exception as e:
            log_backend_operation(
                "redis_reset_error",
                f"Failed to reset key {key}: {e}",
                duration=time.time() - start_time,
                level="error",
            )
            raise

    def get_count(self, key: str) -> int:
        """Get the current count for the given key."""
        normalized_key = normalize_key(key, self.key_prefix)

        try:
            if self.algorithm == "sliding_window":
                # For sliding window, count non-expired entries using utility
                # We don't have window size here, so return total count
                # This could be improved with better API design
                count = self.redis.zcard(normalized_key)

                # Use utility to validate sliding window count if we had
                # window size
                # count = calculate_sliding_window_count(entries, window_size,
                #                                        current_time)

                return count
            else:
                # For fixed window, get the counter value
                count = self.redis.get(normalized_key)
                return int(count) if count else 0
        except Exception as e:
            log_backend_operation(
                "redis_get_count_error",
                f"Failed to get count for key {key}: {e}",
                level="error",
            )
            return 0

    def get_reset_time(self, key: str) -> Optional[int]:
        """Get the timestamp when the key will reset."""
        normalized_key = normalize_key(key, self.key_prefix)

        try:
            ttl = self.redis.ttl(normalized_key)
            if ttl > 0:
                return int(time.time() + ttl)
            else:
                return None
        except Exception as e:
            log_backend_operation(
                "redis_get_reset_time_error",
                f"Failed to get reset time for key {key}: {e}",
                level="error",
            )
            return None

    # Token Bucket Algorithm Implementation

    def token_bucket_check(
        self,
        key: str,
        bucket_size: int,
        refill_rate: float,
        initial_tokens: int,
        tokens_requested: int,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Atomic token bucket check using Redis Lua script.

        Args:
            key: Rate limit key
            bucket_size: Maximum number of tokens in bucket
            refill_rate: Rate at which tokens are added (tokens per second)
            initial_tokens: Initial number of tokens when bucket is created
            tokens_requested: Number of tokens requested for this operation

        Returns:
            Tuple of (is_allowed, metadata_dict)
        """
        normalized_key = normalize_key(f"{key}:token_bucket", self.key_prefix)
        current_time = time.time()

        start_time = time.time()
        try:
            result = self.redis.evalsha(
                self.token_bucket_sha,
                1,
                normalized_key,
                bucket_size,
                refill_rate,
                initial_tokens,
                tokens_requested,
                current_time,
            )

            is_allowed = bool(result[0])
            tokens_remaining = float(result[1])
            bucket_size_returned = int(result[2])
            refill_rate_returned = float(result[3])
            time_to_refill = float(result[4])

            # Format metadata using utility
            metadata = format_token_bucket_metadata(
                tokens_remaining=tokens_remaining,
                tokens_requested=tokens_requested,
                bucket_size=bucket_size_returned,
                refill_rate=refill_rate_returned,
                time_to_refill=time_to_refill,
            )

            # Log operation
            log_backend_operation(
                "redis_token_bucket_check",
                f"Token bucket check for key {key}: allowed={is_allowed}",
                duration=time.time() - start_time,
            )

            return is_allowed, metadata

        except Exception as e:
            log_backend_operation(
                "redis_token_bucket_check_error",
                f"Token bucket Lua script failed for key {key}: {e}",
                duration=time.time() - start_time,
                level="error",
            )
            # If Lua script fails, fall back to generic implementation
            raise RuntimeError(f"Token bucket Lua script failed: {e}") from e

    def token_bucket_info(
        self, key: str, bucket_size: int, refill_rate: float
    ) -> Dict[str, Any]:
        """
        Get token bucket information without consuming tokens.

        Args:
            key: Rate limit key
            bucket_size: Maximum number of tokens in bucket
            refill_rate: Rate at which tokens are added (tokens per second)

        Returns:
            Dictionary with current bucket state
        """
        normalized_key = normalize_key(f"{key}:token_bucket", self.key_prefix)
        current_time = time.time()

        try:
            result = self.redis.evalsha(
                self.token_bucket_info_sha,
                1,
                normalized_key,
                bucket_size,
                refill_rate,
                current_time,
            )

            tokens_remaining = float(result[0])
            bucket_size_returned = int(result[1])
            refill_rate_returned = float(result[2])
            time_to_refill = float(result[3])
            last_refill = float(result[4])

            # Format metadata using utility
            return format_token_bucket_metadata(
                tokens_remaining=tokens_remaining,
                bucket_size=bucket_size_returned,
                refill_rate=refill_rate_returned,
                time_to_refill=time_to_refill,
                last_refill=last_refill,
            )

        except Exception as e:
            log_backend_operation(
                "redis_token_bucket_info_error",
                f"Token bucket info failed for key {key}: {e}",
                level="error",
            )
            # If Lua script fails, return empty state
            return format_token_bucket_metadata(
                tokens_remaining=bucket_size,
                bucket_size=bucket_size,
                refill_rate=refill_rate,
                time_to_refill=0.0,
                last_refill=current_time,
            )

    # Generic storage methods for algorithm implementations

    def get(self, key: str) -> Any:
        """Get value for a key."""
        normalized_key = normalize_key(key, self.key_prefix)

        try:
            value = self.redis.get(normalized_key)
            # Use utility for deserialization
            return deserialize_data(value) if value else None
        except Exception as e:
            log_backend_operation(
                "redis_get_error", f"Failed to get key {key}: {e}", level="error"
            )
            return None

    def set(self, key: str, value: Any, expiration: Optional[int] = None) -> bool:
        """Set value for a key with optional expiration."""
        normalized_key = normalize_key(key, self.key_prefix)

        try:
            # Use utility for serialization
            serialized_value = serialize_data(value)

            if expiration:
                return bool(
                    self.redis.setex(normalized_key, expiration, serialized_value)
                )
            else:
                return bool(self.redis.set(normalized_key, serialized_value))
        except Exception as e:
            log_backend_operation(
                "redis_set_error", f"Failed to set key {key}: {e}", level="error"
            )
            return False

    def delete(self, key: str) -> bool:
        """Delete a key."""
        normalized_key = normalize_key(key, self.key_prefix)

        try:
            return bool(self.redis.delete(normalized_key))
        except Exception as e:
            log_backend_operation(
                "redis_delete_error", f"Failed to delete key {key}: {e}", level="error"
            )
            return False

    def _make_key(self, key: str) -> str:
        """Create the full Redis key with prefix (kept for compatibility)."""
        return normalize_key(key, self.key_prefix)

    def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the Redis connection using backend utilities.

        Returns:
            Dictionary with health status information
        """
        try:
            start_time = time.time()

            # Use retry utility for robust health check
            @retry_backend_operation(max_retries=2, delay=0.5)
            def _perform_health_check():
                self.redis.ping()
                info = self.redis.info()
                return info

            info = _perform_health_check()
            response_time = time.time() - start_time

            # Calculate memory usage estimate
            memory_usage = estimate_backend_memory_usage(
                {"redis_info": info}, backend_type="redis"
            )

            health_data = {
                "status": "healthy",
                "response_time": response_time,
                "redis_version": info.get("redis_version"),
                "connected_clients": info.get("connected_clients"),
                "used_memory": info.get("used_memory"),
                "used_memory_human": info.get("used_memory_human"),
                "estimated_ratelimit_memory": memory_usage,
                "algorithm": self.algorithm,
                "key_prefix": self.key_prefix,
            }

            log_backend_operation(
                "redis_health_check",
                f"Health check successful: {health_data['status']}",
                duration=response_time,
            )

            return health_data

        except Exception as e:
            log_backend_operation(
                "redis_health_check_error",
                f"Health check failed: {e}",
                duration=time.time() - start_time,
                level="error",
            )
            return {"status": "unhealthy", "error": str(e)}
