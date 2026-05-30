"""Regression tests for Redis circuit breaker state key TTL consistency."""

from unittest.mock import Mock, call

from django_smart_ratelimit.circuit_breaker_state import RedisCircuitBreakerState


class TestRedisStateTTLConsistency:
    """Failures/last_failure keys must not outlive the state key."""

    def test_set_state_with_ttl_expires_failure_keys(self):
        """set_state with a TTL applies the same expiry to failure keys."""
        client = Mock()
        storage = RedisCircuitBreakerState(client, key_prefix="circuit:")

        storage.set_state("svc", "open", ttl=120)

        client.setex.assert_called_once_with("circuit:svc:state", 120, "open")
        # The failures and last_failure keys must get the same TTL so they
        # cannot survive the state key and leave a stale failure count.
        client.expire.assert_has_calls(
            [
                call("circuit:svc:failures", 120),
                call("circuit:svc:last_failure", 120),
            ],
            any_order=True,
        )
        assert client.expire.call_count == 2

    def test_set_state_without_ttl_does_not_expire(self):
        """set_state without a TTL leaves keys persistent (unchanged behavior)."""
        client = Mock()
        storage = RedisCircuitBreakerState(client, key_prefix="circuit:")

        storage.set_state("svc", "closed")

        client.set.assert_called_once_with("circuit:svc:state", "closed")
        client.setex.assert_not_called()
        client.expire.assert_not_called()
