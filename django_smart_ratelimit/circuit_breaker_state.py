"""Circuit Breaker State Storage abstractions."""

import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class CircuitBreakerStateStorage(ABC):
    """Abstract state storage for circuit breaker."""

    @abstractmethod
    def get_failure_count(self, name: str) -> int:
        """Get current failure count."""

    @abstractmethod
    def increment_failure(self, name: str) -> int:
        """Increment failure count. Returns new count."""

    @abstractmethod
    def reset_failures(self, name: str) -> None:
        """Reset failure count to zero."""

    @abstractmethod
    def get_state(self, name: str) -> str:
        """Get current state (closed, open, half_open)."""

    @abstractmethod
    def set_state(self, name: str, state: str, ttl: Optional[int] = None) -> None:
        """Set current state."""

    @abstractmethod
    def get_last_failure_time(self, name: str) -> Optional[float]:
        """Get timestamp of last failure."""

    @abstractmethod
    def get_half_open_calls(self, name: str) -> int:
        """Get number of calls in half-open state."""

    @abstractmethod
    def increment_half_open_calls(self, name: str) -> int:
        """Increment half-open call count. Returns new count."""

    @abstractmethod
    def reset_half_open_calls(self, name: str) -> None:
        """Reset half-open call count to zero."""


class MemoryCircuitBreakerState(CircuitBreakerStateStorage):
    """In-memory state storage (per-process)."""

    def __init__(self) -> None:
        """Initialize empty state storage with thread lock."""
        self._failures: Dict[str, int] = {}
        self._states: Dict[str, str] = {}
        self._last_failures: Dict[str, float] = {}
        self._half_open_calls: Dict[str, int] = {}
        self._lock = threading.Lock()

    def get_failure_count(self, name: str) -> int:
        """Get current failure count for a circuit breaker."""
        with self._lock:
            return self._failures.get(name, 0)

    def increment_failure(self, name: str) -> int:
        """Increment failure count and update last failure timestamp."""
        with self._lock:
            self._failures[name] = self._failures.get(name, 0) + 1
            self._last_failures[name] = time.time()
            return self._failures[name]

    def reset_failures(self, name: str) -> None:
        """Reset failure count to zero."""
        with self._lock:
            self._failures[name] = 0

    def get_state(self, name: str) -> str:
        """Get current state (open/closed/half-open)."""
        with self._lock:
            return self._states.get(name, "closed")

    def set_state(self, name: str, state: str, ttl: Optional[int] = None) -> None:
        """Set state."""
        with self._lock:
            self._states[name] = state

    def get_last_failure_time(self, name: str) -> Optional[float]:
        """Get timestamp of last failure."""
        with self._lock:
            return self._last_failures.get(name)

    def get_half_open_calls(self, name: str) -> int:
        """Get number of calls in half-open state."""
        with self._lock:
            return self._half_open_calls.get(name, 0)

    def increment_half_open_calls(self, name: str) -> int:
        """Increment half-open call count."""
        with self._lock:
            self._half_open_calls[name] = self._half_open_calls.get(name, 0) + 1
            return self._half_open_calls[name]

    def reset_half_open_calls(self, name: str) -> None:
        """Reset half-open call count to zero."""
        with self._lock:
            self._half_open_calls[name] = 0


class RedisCircuitBreakerState(CircuitBreakerStateStorage):
    """Redis-backed state storage (distributed)."""

    def __init__(self, redis_client: Any, key_prefix: str = "circuit:") -> None:
        """Initialize with redis client and key prefix."""
        self._redis = redis_client
        self._prefix = key_prefix

    def _key(self, name: str, suffix: str) -> str:
        return f"{self._prefix}{name}:{suffix}"

    def get_failure_count(self, name: str) -> int:
        """Get current failure count from Redis."""
        val = self._redis.get(self._key(name, "failures"))
        return int(val) if val else 0

    def increment_failure(self, name: str) -> int:
        """Increment failure count and update last failure timestamp using pipeline."""
        pipe = self._redis.pipeline()
        pipe.incr(self._key(name, "failures"))
        # We need to set last failure time
        pipe.set(self._key(name, "last_failure"), time.time())
        results = pipe.execute()
        return results[0]

    def reset_failures(self, name: str) -> None:
        """Reset failure count to zero in Redis."""
        self._redis.set(self._key(name, "failures"), 0)

    def get_state(self, name: str) -> str:
        """Get current state from Redis."""
        val = self._redis.get(self._key(name, "state"))
        if not val:
            return "closed"
        return val.decode() if isinstance(val, bytes) else val

    def set_state(self, name: str, state: str, ttl: Optional[int] = None) -> None:
        """Set state in Redis with optional TTL."""
        key = self._key(name, "state")
        if ttl:
            self._redis.setex(key, ttl, state)
        else:
            self._redis.set(key, state)

    def get_last_failure_time(self, name: str) -> Optional[float]:
        """Get last failure timestamp from Redis."""
        val = self._redis.get(self._key(name, "last_failure"))
        return float(val) if val else None

    def get_half_open_calls(self, name: str) -> int:
        """Get number of calls in half-open state from Redis."""
        val = self._redis.get(self._key(name, "half_open_calls"))
        return int(val) if val else 0

    def increment_half_open_calls(self, name: str) -> int:
        """Increment half-open call count in Redis."""
        return self._redis.incr(self._key(name, "half_open_calls"))

    def reset_half_open_calls(self, name: str) -> None:
        """Reset half-open call count to zero in Redis."""
        self._redis.set(self._key(name, "half_open_calls"), 0)
