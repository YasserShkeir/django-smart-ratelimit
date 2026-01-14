"""
Redis backend for rate limiting using sliding window algorithm.

This backend uses Redis with Lua scripts to implement atomic sliding window
rate limiting with high performance and accuracy.
"""

import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from django.core.exceptions import ImproperlyConfigured

from ..exceptions import BackendConnectionError, BackendError, CircuitBreakerError
from ..messages import ERROR_BACKEND_UNAVAILABLE
from .base import BaseBackend
from .utils import (
    calculate_expiry,
    deserialize_data,
    estimate_backend_memory_usage,
    format_lua_script,
    format_token_bucket_metadata,
    get_current_timestamp,
    get_time_bucket_key_suffix,
    log_backend_operation,
    normalize_key,
    serialize_data,
    validate_backend_config,
    with_retry,
)

try:
    import redis
    from redis.connection import ConnectionPool
except ImportError:
    redis = None
    ConnectionPool = None


class RedisBackend(BaseBackend):
    """
    Redis backend implementation using sliding window algorithm.

    This backend uses a Lua script to atomically manage sliding window
    counters with automatic cleanup of expired entries.
    """

    # Class-level connection pool for reusing connections across instances
    _pools: Dict[str, Any] = {}
    _pools_lock = threading.Lock()

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
        fail_open: Optional[bool] = None,
        **kwargs: Any,
    ):
        """Initialize the Redis backend with connection pooling."""
        # Get Redis configuration with validation
        from django_smart_ratelimit.config import get_settings

        settings = get_settings()

        if fail_open is None:
            fail_open = settings.fail_open

        # Initialize parent class with circuit breaker
        super().__init__(
            enable_circuit_breaker=enable_circuit_breaker,
            circuit_breaker_config=circuit_breaker_config,
            fail_open=fail_open,
            **kwargs,
        )

        if redis is None:
            raise ImproperlyConfigured(
                "Redis backend requires the redis package. "
                "Install it with: pip install redis"
            )

        redis_config = settings.redis_config

        # Validate configuration using utility
        validate_backend_config(redis_config, backend_type="redis")

        # Default configuration
        self.config = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
            "password": None,
            "socket_timeout": 5,
            "socket_connect_timeout": 5,
            "decode_responses": True,
            **redis_config,
        }

        # Extract URL if present, otherwise use config
        url = kwargs.get("url") or redis_config.get("url")

        try:
            # Get or create connection pool
            self._pool = self._get_or_create_pool(url, **self.config)
            self.redis = redis.Redis(connection_pool=self._pool)

            # Initial verification
            self._check_connection(raise_exception=True)

        except Exception as e:
            if self.fail_open:
                log_backend_operation(
                    "redis_init_failed",
                    f"Failed to connect to Redis, failing open: {e}",
                    level="error",
                )
                self.redis = None
            else:
                raise ImproperlyConfigured(f"Cannot connect to Redis: {e}") from e

        # Load and cache Lua scripts using utility
        if self.redis:
            self.sliding_window_sha = self._load_script(self.SLIDING_WINDOW_SCRIPT)
            self.fixed_window_sha = self._load_script(self.FIXED_WINDOW_SCRIPT)
            self.token_bucket_sha = self._load_script(self.TOKEN_BUCKET_SCRIPT)
            self.token_bucket_info_sha = self._load_script(
                self.TOKEN_BUCKET_INFO_SCRIPT
            )
        else:
            self.sliding_window_sha = ""
            self.fixed_window_sha = ""
            self.token_bucket_sha = ""  # nosec B105 - not a password, SHA cache init
            self.token_bucket_info_sha = (
                ""  # nosec B105 - not a password, SHA cache init
            )

        # Configuration
        self.algorithm = settings.default_algorithm
        self.key_prefix = settings.key_prefix

        # Log initialization
        log_backend_operation(
            "redis_init",
            f"Redis backend initialized with {self.algorithm} algorithm",
            level="info",
        )

    @classmethod
    def _get_or_create_pool(cls, url: Optional[str], **kwargs: Any) -> Any:
        """Get or create a connection pool."""
        # Remove None values and keys that shouldn't be part of identity
        # Redis-py config keys: host, port, db, password, etc.
        # If url is provided, use from_url.

        # Consistent key generation
        pool_key_parts = [f"url={url}"] if url else []
        for k, v in sorted(kwargs.items()):
            if k not in (
                "decode_responses",
            ):  # pool doesn't care about decode_responses usually?
                # Actually it does. Connection needs to know encoding.
                pool_key_parts.append(f"{k}={v}")

        pool_key = "|".join(pool_key_parts)

        with cls._pools_lock:
            if pool_key not in cls._pools:
                if url:
                    cls._pools[pool_key] = ConnectionPool.from_url(url, **kwargs)
                else:
                    cls._pools[pool_key] = ConnectionPool(**kwargs)
            return cls._pools[pool_key]

    def _check_connection(self, raise_exception: bool = False) -> bool:
        """Check if Redis connection is healthy."""
        try:
            self.redis.ping()
            return True
        except (redis.RedisError, AttributeError) as e:
            if raise_exception:
                raise e
            return False

    def _reconnect(self) -> None:
        """Attempt to reconnect to Redis."""
        try:
            if self._pool:
                self._pool.disconnect()  # Reset connections
            # Redis client automatically uses the pool, so resetting pool is enough?
            # Or create new client?
            self.redis = redis.Redis(connection_pool=self._pool)
        except Exception:
            # log but don't crash
            pass  # nosec B110 - intentional resilient error handling

    def _execute_with_retry(self, operation: Callable, max_retries: int = 3) -> Any:
        """Execute Redis operation with retry and reconnection."""
        if self.redis is None:
            if self.fail_open:
                return None  # Or handled by caller?
            raise BackendError("Redis client is not initialized")

        last_error = None
        for attempt in range(max_retries):
            try:
                return operation()
            except (redis.ConnectionError, redis.TimeoutError) as e:
                last_error = e
                self._reconnect()
            except redis.RedisError as e:
                raise BackendError(f"Redis error: {e}") from e

        if self.fail_open:
            return None  # Fallback?

        raise BackendConnectionError(
            f"Redis operation failed after {max_retries} attempts",
            original_exception=last_error,
        )

    def _load_script(self, script_content: str) -> str:
        """Load and cache a Lua script using utility formatting."""
        if self.redis is None:
            return ""
        formatted_script = format_lua_script(script_content)
        return self.redis.script_load(formatted_script)

    def _eval_lua(
        self,
        sha_attr: str,
        script_content: str,
        numkeys: int,
        *args: Any,
    ) -> Any:
        """Evaluate a cached Lua script, reloading on NoScriptError."""
        if self.redis is None:
            if self.fail_open:
                return 0  # Or appropriate safe value?
            raise ImproperlyConfigured("Redis client is not initialized")

        def _do_eval():
            sha = getattr(self, sha_attr)
            return self.redis.evalsha(sha, numkeys, *args)

        try:
            # Wrap in retry logic
            return self._execute_with_retry(_do_eval)
        except redis.exceptions.NoScriptError:
            # Reload script and retry once
            # Note: _execute_with_retry might have retried connection errors,
            # but NoScriptError comes from successful connection but missing script.
            log_backend_operation(
                "redis_reload_script",
                "Reloading Lua script after NoScriptError",
                level="warning",
                script=sha_attr,
            )
            new_sha = self._load_script(script_content)
            setattr(self, sha_attr, new_sha)

            # Retry the eval with new SHA (also wrapped in retry for connection safety)
            def _do_eval_retry():
                return self.redis.evalsha(new_sha, numkeys, *args)

            return self._execute_with_retry(_do_eval_retry)

    def incr(self, key: str, period: int) -> int:
        """
        Increment the counter for the given key within the time period.

        Wraps the internal logic with Circuit Breaker and Error Handling.
        """
        start_time = get_current_timestamp()

        try:
            # Wrap internal call with Circuit Breaker if enabled
            if self._circuit_breaker:
                # circuit_breaker.call expects a callable and args
                count = self._circuit_breaker.call(
                    self._incr_unsafe, key, period, start_time
                )
            else:
                count = self._incr_unsafe(key, period, start_time)

            return count

        except Exception as e:
            # Handle both Redis errors (propagated) and CircuitBreakerError
            # Check if this was a Circuit Breaker Open event
            is_cb_open = "Circuit breaker is open" in str(e)

            log_backend_operation(
                "redis_incr_error",
                f"Failed to increment key {key}: {e}",
                duration=get_current_timestamp() - start_time,
                level="error",
                extra={"circuit_breaker_open": is_cb_open},
            )

            # Use standardized error handling (Fail Open/Closed logic)
            # If fail_open is True, returns 0 (allowed).
            # If fail_open is False, raises BackendError.
            allowed, meta = self._handle_backend_error("incr", key, e)
            return 0 if allowed else 9999

    def _incr_unsafe(self, key: str, period: int, start_time: float) -> int:
        """
        Internal increment logic that RAISES exceptions on failure.
        This allows Circuit Breaker to detect failures.
        """
        # Normalize key using utility
        normalized_key = normalize_key(key, self.key_prefix)
        now = get_current_timestamp()

        if self.algorithm == "sliding_window":
            # Use sliding window algorithm
            count = self._eval_lua(
                "sliding_window_sha",
                self.SLIDING_WINDOW_SCRIPT,
                1,
                normalized_key,
                period,
                999999,  # We'll check the limit in Python for flexibility
                now,
            )
        else:
            # Use fixed window algorithm (default for unknown algorithms)
            # For clock-aligned mode, append time bucket suffix to key
            # This causes keys to rotate at clock boundaries
            bucket_suffix = get_time_bucket_key_suffix(period)
            fixed_key = normalized_key + bucket_suffix

            count = self._eval_lua(
                "fixed_window_sha",
                self.FIXED_WINDOW_SCRIPT,
                1,
                fixed_key,
                period,
                999999,  # We'll check the limit in Python for flexibility
                now,
            )

        # Log successful operation
        log_backend_operation(
            "redis_incr",
            f"Incremented key {key} to count {count}",
            duration=get_current_timestamp() - start_time,
        )

        return count

    def reset(self, key: str) -> None:
        """Reset the counter for the given key."""
        normalized_key = normalize_key(key, self.key_prefix)

        start_time = get_current_timestamp()
        try:
            self.redis.delete(normalized_key)
            log_backend_operation(
                "redis_reset",
                f"Reset key {key}",
                duration=get_current_timestamp() - start_time,
            )
        except Exception as e:
            log_backend_operation(
                "redis_reset_error",
                f"Failed to reset key {key}: {e}",
                duration=get_current_timestamp() - start_time,
                level="error",
            )
            allowed, meta = self._handle_backend_error("reset", key, e)
            if not allowed:
                raise BackendError(ERROR_BACKEND_UNAVAILABLE) from e

    def get_count(self, key: str, period: int = 60) -> int:
        """
        Get the current count for the given key.

        Args:
            key: The rate limit key
            period: Time period in seconds (default: 60)

        Returns:
            Current count (0 if key doesn't exist)
        """
        normalized_key = normalize_key(key, self.key_prefix)

        try:
            if self.algorithm == "sliding_window":
                # For sliding window, count entries within the window
                now = get_current_timestamp()
                window_start = now - period
                return self.redis.zcount(normalized_key, window_start, "+inf")
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
            allowed, meta = self._handle_backend_error("get_count", key, e)
            return 0 if allowed else 9999

    def get_reset_time(self, key: str) -> Optional[int]:
        """Get the timestamp when the key will reset."""
        normalized_key = normalize_key(key, self.key_prefix)

        try:
            ttl = self.redis.ttl(normalized_key)
            if ttl > 0:
                return int(calculate_expiry(get_current_timestamp(), ttl))
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
        current_time = get_current_timestamp()

        start_time = get_current_timestamp()
        try:
            result = self._eval_lua(
                "token_bucket_sha",
                self.TOKEN_BUCKET_SCRIPT,
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
                duration=get_current_timestamp() - start_time,
            )

            return is_allowed, metadata

        except Exception as e:
            log_backend_operation(
                "redis_token_bucket_check_error",
                f"Token bucket Lua script failed for key {key}: {e}",
                duration=get_current_timestamp() - start_time,
                level="error",
            )
            if self.fail_open:
                # Return allowed with dummy metadata
                metadata = format_token_bucket_metadata(
                    tokens_remaining=float(bucket_size),  # Assume full
                    tokens_requested=tokens_requested,
                    bucket_size=float(bucket_size),
                    refill_rate=float(refill_rate),
                    time_to_refill=0.0,
                )
                return True, metadata
            # If Lua script fails, fall back to generic implementation
            raise BackendError(ERROR_BACKEND_UNAVAILABLE) from e

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
        current_time = get_current_timestamp()

        try:
            result = self._eval_lua(
                "token_bucket_info_sha",
                self.TOKEN_BUCKET_INFO_SCRIPT,
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

    def check_batch(
        self,
        checks: List[Dict[str, Any]],
    ) -> List[Tuple[bool, Dict]]:
        """
        Check multiple rate limits at once using Redis pipeline.

        Args:
            checks: List of dicts with 'key', 'limit', 'period'

        Returns:
            List of (allowed, metadata) tuples
        """
        if not self.redis:
            return super().check_batch(checks)

        results = []
        now = get_current_timestamp()

        try:
            with self.redis.pipeline() as pipe:
                for check in checks:
                    key = check["key"]
                    period = check["period"]
                    normalized_key = normalize_key(key, self.key_prefix)

                    sha = (
                        self.sliding_window_sha
                        if self.algorithm == "sliding_window"
                        else self.fixed_window_sha
                    )

                    # Use large limit to just get count, actual check in Python
                    pipe.evalsha(sha, 1, normalized_key, period, 999999, now)

                # Execute pipeline
                pipeline_results = pipe.execute()

                # Process results
                for i, count in enumerate(pipeline_results):
                    # Handle potential script errors in pipeline
                    if isinstance(count, Exception):
                        raise count

                    limit = checks[i]["limit"]
                    # Ensure count is integer
                    count = int(count)
                    allowed = count <= limit
                    results.append((allowed, {"count": count}))

                # Log batch success
                log_backend_operation(
                    "redis_batch_check",
                    f"Batch checked {len(checks)} keys",
                    duration=get_current_timestamp() - now,
                )

                return results

        except Exception as e:
            log_backend_operation(
                "redis_batch_error",
                f"Redis batch check failed (falling back to sequential): {e}",
                level="error",
            )
            # If pipeline fails (e.g. NOSCRIPT), fallback to sequential safe implementation
            return super().check_batch(checks)

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
            start_time = get_current_timestamp()

            # Use retry utility for robust health check
            @with_retry(max_retries=2, delay=0.5)
            def _perform_health_check():
                self.redis.ping()
                info = self.redis.info()
                return info

            info = _perform_health_check()
            response_time = get_current_timestamp() - start_time

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
                duration=get_current_timestamp() - start_time,
                level="error",
            )
            return {"status": "unhealthy", "error": str(e)}


class AsyncRedisBackend(BaseBackend):
    """
    Async Redis backend using redis-py asyncio support.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the async Redis backend."""
        super().__init__(**kwargs)
        import threading

        self._thread_local = threading.local()

        # Validate configuration
        if redis is None:
            raise ImproperlyConfigured("redis-py is required for AsyncRedisBackend")

        redis_config = kwargs.get("redis_config", {})
        # Load from settings if not provided (similar to RedisBackend)
        if not redis_config:
            from django_smart_ratelimit.config import get_settings

            redis_config = getattr(get_settings(), "redis_config", {}) or {}

        self.config = {
            "host": "localhost",
            "port": 6379,
            "db": 0,
            "password": None,
            "decode_responses": True,
            **redis_config,
        }

        # Remove keys that might have leaked into config but aren't valid for Redis client
        self.config.pop("algorithm", None)
        self.config.pop("key_prefix", None)

        self.url = kwargs.get("url") or redis_config.get("url")
        # self.client is now managed via thread_local property
        self.key_prefix = kwargs.get("key_prefix", "rl:")
        self.algorithm = kwargs.get("algorithm", "sliding_window")

        # Scripts
        self.sliding_window_sha = ""
        self.fixed_window_sha = ""

    @property
    def client(self):
        return getattr(self._thread_local, "client", None)

    @client.setter
    def client(self, value):
        self._thread_local.client = value

    async def _get_client(self):
        """Get or create async redis client."""
        import asyncio

        from redis import asyncio as aioredis

        # Check if client needs to be reset due to closed event loop
        if self.client:
            try:
                current_loop = asyncio.get_running_loop()

                # Check connection pool loop
                client_pool = getattr(self.client, "connection_pool", None)
                client_loop = (
                    getattr(client_pool, "loop", None) if client_pool else None
                )

                should_reset = False

                # If we have a tracked loop and it's different from current
                if client_loop and client_loop != current_loop:
                    should_reset = True

                # If the tracked loop is closed
                if client_loop and client_loop.is_closed():
                    should_reset = True

                if should_reset:
                    # Do NOT call aclose() here as it might try to use the wrong loop
                    # Just abandon the reference and let GC handle it
                    self.client = None
            except Exception:
                # If verification fails, reset
                self.client = None

        if self.client is None:
            # Ensure config is clean for redis-py
            clean_config = {
                k: v
                for k, v in self.config.items()
                if k not in ["algorithm", "key_prefix"]
            }

            if self.url:
                self.client = aioredis.from_url(self.url, **clean_config)
            else:
                self.client = aioredis.Redis(**clean_config)

            # Load scripts
            try:
                self.sliding_window_sha = await self._load_script(
                    self.client, RedisBackend.SLIDING_WINDOW_SCRIPT
                )
                self.fixed_window_sha = await self._load_script(
                    self.client, RedisBackend.FIXED_WINDOW_SCRIPT
                )
            except Exception:
                # Handle connection error during init
                pass  # nosec B110 - intentional resilient error handling

        return self.client

    async def _load_script(self, client, script_content: str) -> str:
        """Load Lua script into Redis."""
        return await client.script_load(format_lua_script(script_content))

    async def aincr(self, key: str, period: int) -> int:
        """Async increment."""
        try:
            # Check Circuit Breaker
            if self._circuit_breaker:
                self._circuit_breaker._check_reset_timeout()
                if not self._circuit_breaker.is_allowed():
                    self._circuit_breaker._stats.record_failure()
                    raise CircuitBreakerError("Circuit breaker is open")

            client = await self._get_client()
            normalized_key = normalize_key(key, self.key_prefix)
            now = get_current_timestamp()

            if self.algorithm == "sliding_window":
                sha = self.sliding_window_sha
                # args: normalized_key, period, limit, now
                res = await client.evalsha(sha, 1, normalized_key, period, 999999, now)
            else:
                sha = self.fixed_window_sha
                res = await client.evalsha(sha, 1, normalized_key, period, 999999, now)

            # Report Success
            if self._circuit_breaker:
                self._circuit_breaker.report_success()

            return res

        except Exception as e:
            # Report Failure to Circuit Breaker (if not already Open)
            if self._circuit_breaker and not isinstance(e, CircuitBreakerError):
                try:
                    self._circuit_breaker.report_failure()
                except Exception:
                    # Ignore errors during failure reporting to prevent masking original error
                    pass  # nosec B110 - intentional resilient error handling

            # Critical: Invalidate client on error to prevent sticky broken sockets/loops
            self.client = None

            extra = {}
            if isinstance(e, CircuitBreakerError):
                extra["circuit_breaker_open"] = True

            log_backend_operation(
                "async_incr_error", str(e), level="error", extra=extra
            )

            if self.fail_open:
                return 0  # Allow
            return 999999  # Block

    # Implement abstract methods
    def incr(self, key: str, period: int) -> int:
        """
        Sync wrapper for aincr to support sync views.
        """
        from asgiref.sync import async_to_sync

        return async_to_sync(self.aincr)(key, period)

    def get_count(self, key: str, period: int = 60) -> int:
        raise NotImplementedError("Use aget_count for AsyncRedisBackend")

    def reset(self, key: str) -> None:
        raise NotImplementedError("Use areset for AsyncRedisBackend")

    def get_reset_time(self, key: str) -> Optional[int]:
        raise NotImplementedError("Use aget_reset_time for AsyncRedisBackend")
