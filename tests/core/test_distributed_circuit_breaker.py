import time

import pytest

from django_smart_ratelimit.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerState,
)


class MockPipeline:
    """Mock Redis Pipeline."""

    def __init__(self, client):
        self.client = client
        self.commands = []

    def incr(self, key):
        self.commands.append(("incr", key))
        return self

    def set(self, key, value, **kwargs):
        self.commands.append(("set", key, value))
        return self

    def setex(self, key, time, value):
        self.commands.append(("set", key, value))
        return self

    def execute(self):
        results = []
        for cmd in self.commands:
            if cmd[0] == "incr":
                results.append(self.client.incr(cmd[1]))
            elif cmd[0] == "set":
                results.append(self.client.set(cmd[1], cmd[2]))
        self.commands = []
        return results


class MockSharedRedis:
    """A mock Redis client that shares state between instances."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        val = self.data.get(key)
        if val is None:
            return None
        # mimics redis behavior of returning bytes
        if isinstance(val, int):
            return str(val).encode()
        if isinstance(val, str):
            return val.encode()
        return val

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def setex(self, key, time, value):
        self.data[key] = value
        return True

    def incr(self, key):
        current = self.data.get(key)
        if current is None:
            val = 0
        else:
            try:
                val = int(current)
            except ValueError:
                # If existing value is not int (e.g. bytes from previous set), handle it
                # mock logic to decode bytes if needed
                if isinstance(current, bytes):
                    val = int(current)
                else:
                    val = int(current)

        val += 1
        self.data[key] = val  # Store as int internally, get() handles conversion
        return val

    def delete(self, *keys):
        count = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                count += 1
        return count

    def pipeline(self):
        return MockPipeline(self)


@pytest.fixture
def shared_redis():
    return MockSharedRedis()


def test_distributed_state_sharing(shared_redis):
    """Test that two circuit breakers share state via Redis."""
    config = CircuitBreakerConfig(
        name="distributed_service",
        failure_threshold=2,
        recovery_timeout=60,
        state_backend="redis",
    )

    # Process A
    breaker_a = CircuitBreaker(config, redis_client=shared_redis)

    # Process B
    breaker_b = CircuitBreaker(config, redis_client=shared_redis)

    # Initial state
    assert breaker_a.state == CircuitBreakerState.CLOSED
    assert breaker_b.state == CircuitBreakerState.CLOSED

    # Process A reports failure
    def fail():
        raise ValueError("Boom")

    with pytest.raises(ValueError):
        breaker_a.call(fail)

    # Process B should see failure count 1
    assert breaker_b._failure_count_prop == 1

    # Process B reports failure -> should trip circuit
    with pytest.raises(ValueError):
        breaker_b.call(fail)

    # Both should see OPEN state
    # breaker_b tripped it, so it set state in Redis.
    assert breaker_b.state == CircuitBreakerState.OPEN
    assert breaker_a.state == CircuitBreakerState.OPEN

    # Verify calls are blocked in both
    with pytest.raises(CircuitBreakerError):
        breaker_a.call(lambda: "ok")

    with pytest.raises(CircuitBreakerError):
        breaker_b.call(lambda: "ok")


def test_distributed_recovery(shared_redis):
    """Test distributed recovery behavior."""
    config = CircuitBreakerConfig(
        name="recovery_service",
        failure_threshold=1,
        recovery_timeout=0.1,
        state_backend="redis",
    )

    breaker_a = CircuitBreaker(config, redis_client=shared_redis)
    breaker_b = CircuitBreaker(config, redis_client=shared_redis)

    # Trip circuit
    with pytest.raises(ValueError):
        breaker_a.call(lambda: (_ for _ in ()).throw(ValueError))

    assert breaker_b.state == CircuitBreakerState.OPEN

    # Wait for recovery timeout
    time.sleep(0.2)

    # Process B attempts to call.
    # Logic: is_allowed -> checks state (OPEN) -> checks time.
    # Time passed -> state HALF_OPEN -> returns True.
    # So B enters HALF_OPEN.

    # B succeeds
    assert breaker_b.call(lambda: "success") == "success"

    # B success -> state CLOSED.
    # A should see CLOSED.
    assert breaker_a.state == CircuitBreakerState.CLOSED
