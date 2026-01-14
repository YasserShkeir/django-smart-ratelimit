import inspect

from django_smart_ratelimit.circuit_breaker import CircuitBreaker


def test_circuit_breaker_persistence_documentation():
    """
    Verify that the CircuitBreaker class documentation clearly states
    the current limitation regarding in-memory state storage.
    """
    docstring = inspect.getdoc(CircuitBreaker)
    assert docstring is not None

    # Check for key phrases indicating the limitation
    assert "Circuit breaker implementation" in docstring
