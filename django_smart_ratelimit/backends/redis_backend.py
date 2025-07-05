"""
Redis backend for rate limiting using sliding window algorithm.

This backend uses Redis with Lua scripts to implement atomic sliding window
rate limiting with high performance and accuracy.
"""

import time
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseBackend

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

    def __init__(self):
        """Initialize the Redis backend with connection and scripts."""
        if redis is None:
            raise ImproperlyConfigured(
                "Redis backend requires the redis package. "
                "Install it with: pip install redis"
            )

        # Get Redis configuration
        redis_config = getattr(settings, "RATELIMIT_REDIS", {})

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

        # Initialize Redis connection
        self.redis = redis.Redis(**config)

        # Test connection
        try:
            self.redis.ping()
        except Exception as e:
            raise ImproperlyConfigured(f"Cannot connect to Redis: {e}") from e

        # Load Lua scripts
        self.sliding_window_sha = self.redis.script_load(self.SLIDING_WINDOW_SCRIPT)
        self.fixed_window_sha = self.redis.script_load(self.FIXED_WINDOW_SCRIPT)

        # Configuration
        self.algorithm = getattr(settings, "RATELIMIT_ALGORITHM", "sliding_window")
        self.key_prefix = getattr(settings, "RATELIMIT_KEY_PREFIX", "ratelimit:")

    def incr(self, key: str, period: int) -> int:
        """
        Increment the counter for the given key within the time period.

        Uses either sliding window or fixed window algorithm based on
        configuration.
        """
        full_key = self._make_key(key)
        now = time.time()

        if self.algorithm == "sliding_window":
            # Use sliding window algorithm
            count = self.redis.evalsha(
                self.sliding_window_sha,
                1,
                full_key,
                period,
                999999,  # We'll check the limit in Python for flexibility
                now,
            )
        else:
            # Use fixed window algorithm (default for unknown algorithms)
            count = self.redis.evalsha(
                self.fixed_window_sha,
                1,
                full_key,
                period,
                999999,  # We'll check the limit in Python for flexibility
                now,
            )

        return count

    def reset(self, key: str) -> None:
        """Reset the counter for the given key."""
        full_key = self._make_key(key)
        self.redis.delete(full_key)

    def get_count(self, key: str) -> int:
        """Get the current count for the given key."""
        full_key = self._make_key(key)

        if self.algorithm == "sliding_window":
            # For sliding window, count non-expired entries
            # We don't know the window size here, so we'll return the
            # total count. This is a limitation of the current design.
            return self.redis.zcard(full_key)
        else:
            # For fixed window, get the counter value
            count = self.redis.get(full_key)
            return int(count) if count else 0

    def get_reset_time(self, key: str) -> Optional[int]:
        """Get the timestamp when the key will reset."""
        full_key = self._make_key(key)
        ttl = self.redis.ttl(full_key)

        if ttl > 0:
            return int(time.time() + ttl)
        else:
            return None

    def _make_key(self, key: str) -> str:
        """Create the full Redis key with prefix."""
        return f"{self.key_prefix}{key}"

    def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the Redis connection.

        Returns:
            Dictionary with health status information
        """
        try:
            start_time = time.time()
            self.redis.ping()
            response_time = time.time() - start_time

            info = self.redis.info()

            return {
                "status": "healthy",
                "response_time": response_time,
                "redis_version": info.get("redis_version"),
                "connected_clients": info.get("connected_clients"),
                "used_memory": info.get("used_memory"),
                "used_memory_human": info.get("used_memory_human"),
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
