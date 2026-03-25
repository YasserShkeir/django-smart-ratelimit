"""Unit tests for the AdaptiveRateLimiter class."""

import threading
from unittest.mock import MagicMock

from django_smart_ratelimit.adaptive import (
    AdaptiveRateLimiter,
    ConnectionCountIndicator,
    CPULoadIndicator,
    CustomLoadIndicator,
    LatencyLoadIndicator,
    LoadIndicator,
    MemoryLoadIndicator,
    create_adaptive_limiter,
    get_adaptive_limiter,
    register_adaptive_limiter,
    unregister_adaptive_limiter,
)


class TestLoadIndicators:
    """Tests for individual load indicators."""

    def test_cpu_load_indicator_with_psutil(self):
        """Test CPU load indicator when psutil is available."""
        indicator = CPULoadIndicator(sample_interval=0.01)

        # Should return a value between 0 and 1
        load = indicator.get_load()
        assert 0.0 <= load <= 1.0

    def test_cpu_load_indicator_name(self):
        """Test CPU load indicator name property."""
        indicator = CPULoadIndicator()
        assert indicator.name == "CPULoadIndicator"

    def test_memory_load_indicator(self):
        """Test memory load indicator."""
        indicator = MemoryLoadIndicator()

        # Should return a value between 0 and 1 (or 0 if psutil unavailable)
        load = indicator.get_load()
        assert 0.0 <= load <= 1.0

    def test_latency_load_indicator_empty(self):
        """Test latency indicator with no recorded latencies."""
        indicator = LatencyLoadIndicator()
        assert indicator.get_load() == 0.0

    def test_latency_load_indicator_below_target(self):
        """Test latency indicator with latencies below target."""
        indicator = LatencyLoadIndicator(target_latency_ms=100.0, max_latency_ms=1000.0)

        # Record latencies below target
        for _ in range(10):
            indicator.record_latency(50.0)

        assert indicator.get_load() == 0.0

    def test_latency_load_indicator_above_max(self):
        """Test latency indicator with latencies above max."""
        indicator = LatencyLoadIndicator(target_latency_ms=100.0, max_latency_ms=1000.0)

        # Record latencies above max
        for _ in range(10):
            indicator.record_latency(2000.0)

        assert indicator.get_load() == 1.0

    def test_latency_load_indicator_interpolation(self):
        """Test latency indicator with latencies in between."""
        indicator = LatencyLoadIndicator(
            target_latency_ms=100.0, max_latency_ms=1000.0, window_size=10
        )

        # Record latencies at 550ms (halfway between 100 and 1000)
        for _ in range(10):
            indicator.record_latency(550.0)

        # Should be approximately 0.5
        load = indicator.get_load()
        assert 0.4 <= load <= 0.6

    def test_latency_load_indicator_window_size(self):
        """Test that latency indicator respects window size."""
        indicator = LatencyLoadIndicator(window_size=5)

        # Record more latencies than window size
        for i in range(10):
            indicator.record_latency(float(i * 100))

        # Only last 5 should be counted
        # Latencies: 500, 600, 700, 800, 900 -> avg = 700
        assert len(indicator._latencies) == 5

    def test_connection_count_indicator_increment_decrement(self):
        """Test connection count indicator increment/decrement."""
        indicator = ConnectionCountIndicator(max_connections=100)

        assert indicator.get_load() == 0.0

        # Increment
        for _ in range(50):
            indicator.increment()

        assert indicator.get_load() == 0.5

        # Decrement
        for _ in range(25):
            indicator.decrement()

        assert indicator.get_load() == 0.25

    def test_connection_count_indicator_max_load(self):
        """Test connection count indicator at max connections."""
        indicator = ConnectionCountIndicator(max_connections=10)

        for _ in range(15):  # More than max
            indicator.increment()

        # Should cap at 1.0
        assert indicator.get_load() == 1.0

    def test_connection_count_indicator_decrement_below_zero(self):
        """Test that connection count doesn't go below zero."""
        indicator = ConnectionCountIndicator(max_connections=100)

        # Try to decrement below zero
        indicator.decrement()
        indicator.decrement()

        assert indicator.get_load() == 0.0

    def test_custom_load_indicator(self):
        """Test custom load indicator with a function."""
        custom_load = MagicMock(return_value=0.75)
        indicator = CustomLoadIndicator(custom_load, name="my_indicator")

        assert indicator.get_load() == 0.75
        assert indicator.name == "my_indicator"
        custom_load.assert_called_once()

    def test_custom_load_indicator_clamps_values(self):
        """Test that custom indicator clamps values to 0-1 range."""
        # Test value above 1
        indicator = CustomLoadIndicator(lambda: 1.5)
        assert indicator.get_load() == 1.0

        # Test value below 0
        indicator = CustomLoadIndicator(lambda: -0.5)
        assert indicator.get_load() == 0.0

    def test_custom_load_indicator_handles_exceptions(self):
        """Test that custom indicator handles exceptions gracefully."""

        def failing_function():
            raise ValueError("Test error")

        indicator = CustomLoadIndicator(failing_function)
        assert indicator.get_load() == 0.0


class TestAdaptiveRateLimiter:
    """Tests for AdaptiveRateLimiter class."""

    def test_init_default_values(self):
        """Test initialization with default values."""
        limiter = AdaptiveRateLimiter(base_limit=100)

        assert limiter.base_limit == 100
        assert limiter.min_limit == 10  # 10% of base
        assert limiter.max_limit == 100  # Same as base
        assert limiter.load_threshold_low == 0.3
        assert limiter.load_threshold_high == 0.7

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        limiter = AdaptiveRateLimiter(
            base_limit=100,
            min_limit=20,
            max_limit=200,
            load_threshold_low=0.2,
            load_threshold_high=0.8,
        )

        assert limiter.base_limit == 100
        assert limiter.min_limit == 20
        assert limiter.max_limit == 200
        assert limiter.load_threshold_low == 0.2
        assert limiter.load_threshold_high == 0.8

    def test_effective_limit_with_zero_load(self):
        """Test effective limit when load is zero (below low threshold)."""
        # Create a mock indicator that always returns 0
        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.get_load.return_value = 0.0
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=100, min_limit=10, max_limit=200, indicators=[mock_indicator]
        )

        # With zero load, should return max_limit
        assert limiter.get_effective_limit() == 200

    def test_effective_limit_with_full_load(self):
        """Test effective limit when load is at maximum."""
        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.get_load.return_value = 1.0
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            min_limit=10,
            max_limit=200,
            indicators=[mock_indicator],
            smoothing_factor=1.0,  # No smoothing for immediate response
            update_interval=0,  # Always update
        )

        # With full load, should return min_limit
        assert limiter.get_effective_limit() == 10

    def test_effective_limit_interpolation(self):
        """Test effective limit interpolation between thresholds."""
        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.get_load.return_value = 0.5  # Halfway
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            min_limit=10,
            max_limit=200,
            load_threshold_low=0.3,
            load_threshold_high=0.7,
            indicators=[mock_indicator],
            smoothing_factor=1.0,
            update_interval=0,
        )

        # 0.5 is halfway between 0.3 and 0.7, so limit should be halfway
        # between 200 and 10: approximately 105
        limit = limiter.get_effective_limit()
        assert 90 <= limit <= 120

    def test_add_indicator(self):
        """Test adding indicators dynamically."""
        limiter = AdaptiveRateLimiter(base_limit=100, indicators=[])

        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.name = "test_indicator"

        limiter.add_indicator(mock_indicator, weight=2.0)

        assert len(limiter._indicators) == 1
        assert limiter._weights["test_indicator"] == 2.0

    def test_remove_indicator(self):
        """Test removing indicators."""
        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.name = "test_indicator"

        limiter = AdaptiveRateLimiter(base_limit=100, indicators=[mock_indicator])
        limiter._weights["test_indicator"] = 1.0

        result = limiter.remove_indicator("test_indicator")
        assert result is True
        assert len(limiter._indicators) == 0

        # Try to remove non-existent indicator
        result = limiter.remove_indicator("non_existent")
        assert result is False

    def test_weighted_load_calculation(self):
        """Test that indicators are properly weighted."""
        mock_indicator1 = MagicMock(spec=LoadIndicator)
        mock_indicator1.get_load.return_value = 0.2
        mock_indicator1.name = "indicator1"

        mock_indicator2 = MagicMock(spec=LoadIndicator)
        mock_indicator2.get_load.return_value = 0.8
        mock_indicator2.name = "indicator2"

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            indicators=[mock_indicator1, mock_indicator2],
            weights={"indicator1": 1.0, "indicator2": 3.0},  # indicator2 has 3x weight
            smoothing_factor=1.0,
            update_interval=0,
        )

        # Combined load = (0.2*1 + 0.8*3) / 4 = 0.65
        limiter.get_effective_limit()  # Trigger update
        load = limiter.get_current_load()
        assert abs(load - 0.65) < 0.01

    def test_smoothing_factor(self):
        """Test that smoothing factor dampens sudden load changes."""
        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.name = "mock"
        # Start with indicator returning constant 0.5
        mock_indicator.get_load.return_value = 0.5

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            indicators=[mock_indicator],
            smoothing_factor=0.5,
            update_interval=0,
        )

        # First call - starts building up load
        limiter.get_effective_limit()
        # With smoothing: new = 0.5*0.5 + 0.5*0 = 0.25
        limiter.get_effective_limit()
        # With smoothing: new = 0.5*0.5 + 0.5*0.25 = 0.375
        limiter.get_effective_limit()
        # Continues to converge toward 0.5

        # After several iterations, should converge toward the raw value
        for _ in range(10):
            limiter.get_effective_limit()

        load = limiter.get_current_load()
        # Should have converged close to 0.5
        assert abs(load - 0.5) < 0.05, f"Expected load ~0.5, got {load}"

        # Now test that a sudden change is dampened
        mock_indicator.get_load.return_value = 1.0
        limiter.get_effective_limit()

        new_load = limiter.get_current_load()
        # With smoothing 0.5 and previous ~0.5, jumping to raw 1.0:
        # new = 0.5*1.0 + 0.5*0.5 = 0.75
        # The load shouldn't immediately jump to 1.0
        assert new_load < 1.0, "Smoothing should prevent immediate jump to raw value"
        assert new_load > load, "Load should have increased"

    def test_update_interval(self):
        """Test that update interval is respected."""
        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.get_load.return_value = 0.5
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            indicators=[mock_indicator],
            update_interval=10.0,  # 10 second interval
        )

        # First call should update
        limiter.get_effective_limit()
        initial_call_count = mock_indicator.get_load.call_count

        # Second call should not update (within interval)
        limiter.get_effective_limit()
        assert mock_indicator.get_load.call_count == initial_call_count

    def test_get_metrics(self):
        """Test getting metrics from limiter."""
        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.get_load.return_value = 0.5
        mock_indicator.name = "test_indicator"

        limiter = AdaptiveRateLimiter(
            base_limit=100, min_limit=10, max_limit=200, indicators=[mock_indicator]
        )

        metrics = limiter.get_metrics()

        assert metrics["base_limit"] == 100
        assert metrics["min_limit"] == 10
        assert metrics["max_limit"] == 200
        assert "effective_limit" in metrics
        assert "current_load" in metrics
        assert "indicators" in metrics
        assert "test_indicator" in metrics["indicators"]

    def test_load_history(self):
        """Test load history tracking."""
        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            indicators=[mock_indicator],
            update_interval=0,
            smoothing_factor=1.0,
        )

        # Generate some history
        for i in range(5):
            mock_indicator.get_load.return_value = i * 0.2
            limiter.get_effective_limit()

        history = limiter.get_load_history()
        assert len(history) == 5

        # Test with 'since' filter
        if history:
            middle_ts = history[2][0]
            filtered = limiter.get_load_history(since=middle_ts)
            assert len(filtered) < len(history)

    def test_thread_safety(self):
        """Test that limiter is thread-safe."""
        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.get_load.return_value = 0.5
        mock_indicator.name = "mock"

        limiter = AdaptiveRateLimiter(
            base_limit=100, indicators=[mock_indicator], update_interval=0
        )

        results = []
        errors = []

        def get_limit():
            try:
                for _ in range(100):
                    limit = limiter.get_effective_limit()
                    results.append(limit)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_limit) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 1000

    def test_no_indicators(self):
        """Test limiter with no indicators."""
        limiter = AdaptiveRateLimiter(base_limit=100, indicators=[])

        # Should return max_limit when no indicators (zero load)
        assert limiter.get_effective_limit() == limiter.max_limit

    def test_indicator_failure_handling(self):
        """Test that indicator failures are handled gracefully."""
        mock_indicator = MagicMock(spec=LoadIndicator)
        mock_indicator.get_load.side_effect = RuntimeError("Test error")
        mock_indicator.name = "failing_indicator"

        limiter = AdaptiveRateLimiter(
            base_limit=100, indicators=[mock_indicator], update_interval=0
        )

        # Should not raise, should use default behavior
        limit = limiter.get_effective_limit()
        assert limit == limiter.max_limit  # Zero effective load


class TestAdaptiveRateLimiterRegistry:
    """Tests for the adaptive rate limiter registry functions."""

    def test_register_and_get(self):
        """Test registering and retrieving a limiter."""
        limiter = AdaptiveRateLimiter(base_limit=100)

        register_adaptive_limiter("test_limiter", limiter)
        retrieved = get_adaptive_limiter("test_limiter")

        assert retrieved is limiter

        # Cleanup
        unregister_adaptive_limiter("test_limiter")

    def test_get_nonexistent(self):
        """Test getting a non-existent limiter."""
        result = get_adaptive_limiter("nonexistent_limiter")
        assert result is None

    def test_unregister(self):
        """Test unregistering a limiter."""
        limiter = AdaptiveRateLimiter(base_limit=100)

        register_adaptive_limiter("test_unregister", limiter)
        result = unregister_adaptive_limiter("test_unregister")

        assert result is True
        assert get_adaptive_limiter("test_unregister") is None

        # Try to unregister again
        result = unregister_adaptive_limiter("test_unregister")
        assert result is False

    def test_create_adaptive_limiter_basic(self):
        """Test create_adaptive_limiter helper."""
        limiter = create_adaptive_limiter(
            "test_create", base_limit=100, min_limit=10, max_limit=200
        )

        assert limiter.base_limit == 100
        assert limiter.min_limit == 10
        assert limiter.max_limit == 200

        # Should be registered
        assert get_adaptive_limiter("test_create") is limiter

        # Cleanup
        unregister_adaptive_limiter("test_create")

    def test_create_adaptive_limiter_with_cpu(self):
        """Test create_adaptive_limiter with CPU indicator."""
        limiter = create_adaptive_limiter(
            "test_cpu", base_limit=100, use_cpu=True, use_memory=False
        )

        # Should have CPU indicator
        indicator_names = [i.name for i in limiter._indicators]
        assert "CPULoadIndicator" in indicator_names

        # Cleanup
        unregister_adaptive_limiter("test_cpu")

    def test_create_adaptive_limiter_with_memory(self):
        """Test create_adaptive_limiter with memory indicator."""
        limiter = create_adaptive_limiter(
            "test_memory", base_limit=100, use_cpu=False, use_memory=True
        )

        # Should have memory indicator
        indicator_names = [i.name for i in limiter._indicators]
        assert "MemoryLoadIndicator" in indicator_names

        # Cleanup
        unregister_adaptive_limiter("test_memory")

    def test_create_adaptive_limiter_with_custom(self):
        """Test create_adaptive_limiter with custom indicators."""
        custom = CustomLoadIndicator(lambda: 0.5, name="custom_test")

        limiter = create_adaptive_limiter(
            "test_custom",
            base_limit=100,
            use_cpu=False,
            use_memory=False,
            custom_indicators=[custom],
        )

        indicator_names = [i.name for i in limiter._indicators]
        assert "custom_test" in indicator_names

        # Cleanup
        unregister_adaptive_limiter("test_custom")


class TestAdaptiveRateLimiterIntegration:
    """Integration tests for adaptive rate limiting."""

    def test_realistic_scenario(self):
        """Test a realistic adaptive rate limiting scenario."""
        # Create a custom indicator that we can control
        current_load = [0.0]  # Use list for mutability in closure

        def get_load():
            return current_load[0]

        indicator = CustomLoadIndicator(get_load, name="controllable")

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            min_limit=10,
            max_limit=200,
            load_threshold_low=0.3,
            load_threshold_high=0.7,
            indicators=[indicator],
            smoothing_factor=1.0,  # No smoothing for predictable tests
            update_interval=0,  # Always update
        )

        # Scenario 1: Low load - should get max limit
        current_load[0] = 0.1
        assert limiter.get_effective_limit() == 200

        # Scenario 2: Medium load - should get interpolated limit
        current_load[0] = 0.5
        limit = limiter.get_effective_limit()
        assert 10 < limit < 200

        # Scenario 3: High load - should get min limit
        current_load[0] = 0.9
        assert limiter.get_effective_limit() == 10

        # Scenario 4: Recovery - load decreases
        current_load[0] = 0.2
        assert limiter.get_effective_limit() == 200

    def test_latency_based_adaptive_limiting(self):
        """Test adaptive limiting based on request latency."""
        latency_indicator = LatencyLoadIndicator(
            target_latency_ms=50.0, max_latency_ms=500.0, window_size=10
        )

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            min_limit=10,
            max_limit=200,
            indicators=[latency_indicator],
            smoothing_factor=1.0,
            update_interval=0,
        )

        # Simulate good latency - should get high limit
        for _ in range(10):
            latency_indicator.record_latency(30.0)

        assert limiter.get_effective_limit() == 200

        # Simulate degrading latency
        for _ in range(10):
            latency_indicator.record_latency(300.0)

        limit = limiter.get_effective_limit()
        assert limit < 200  # Should be reduced

        # Simulate very bad latency
        for _ in range(10):
            latency_indicator.record_latency(600.0)

        assert limiter.get_effective_limit() == 10

    def test_connection_based_adaptive_limiting(self):
        """Test adaptive limiting based on connection count."""
        connection_indicator = ConnectionCountIndicator(max_connections=100)

        limiter = AdaptiveRateLimiter(
            base_limit=100,
            min_limit=10,
            max_limit=200,
            load_threshold_low=0.3,
            load_threshold_high=0.7,
            indicators=[connection_indicator],
            smoothing_factor=1.0,
            update_interval=0,
        )

        # Few connections - high limit
        for _ in range(10):
            connection_indicator.increment()

        assert limiter.get_effective_limit() == 200  # 10% load, below threshold

        # Many connections - low limit
        for _ in range(70):  # Total 80 connections
            connection_indicator.increment()

        assert limiter.get_effective_limit() == 10  # 80% load, above threshold
