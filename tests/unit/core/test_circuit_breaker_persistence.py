"""Tests for circuit breaker persistence."""

from django.test import TestCase

from django_smart_ratelimit.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
    circuit_breaker_registry,
)


class TestCircuitBreakerStatePersistence(TestCase):
    """Test circuit breaker state persistence behavior."""

    def setUp(self):
        super().setUp()
        circuit_breaker_registry.reset_all()
        circuit_breaker_registry._breakers.clear()

    def tearDown(self):
        circuit_breaker_registry.reset_all()
        circuit_breaker_registry._breakers.clear()
        super().tearDown()

    def test_circuit_breaker_state_not_persisted(self):
        """Document that state is not persisted across instances."""
        config = CircuitBreakerConfig(failure_threshold=2, name="test_breaker")
        cb1 = CircuitBreaker(config)

        def failing_func():
            raise Exception("Failure")

        # Trip the breaker
        for _ in range(3):
            try:
                cb1.call(failing_func)
            except Exception:
                pass

        self.assertEqual(cb1.state, CircuitBreakerState.OPEN)

        # New instance doesn't share state
        cb2 = CircuitBreaker(config)
        self.assertEqual(cb2.state, CircuitBreakerState.CLOSED)
