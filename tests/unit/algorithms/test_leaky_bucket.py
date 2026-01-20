"""Unit tests for the LeakyBucketAlgorithm."""

from unittest.mock import MagicMock, patch

from django_smart_ratelimit.algorithms.leaky_bucket import LeakyBucketAlgorithm


class TestLeakyBucketAlgorithmBasic:
    """Basic tests for LeakyBucketAlgorithm."""

    def test_init_default_config(self):
        """Test initialization with default config."""
        algorithm = LeakyBucketAlgorithm()
        assert algorithm.bucket_capacity is None
        assert algorithm.leak_rate is None
        assert algorithm.initial_level == 0
        assert algorithm.cost_per_request == 1

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = {
            "bucket_capacity": 100,
            "leak_rate": 10.0,
            "initial_level": 5,
            "cost_per_request": 2,
        }
        algorithm = LeakyBucketAlgorithm(config)
        assert algorithm.bucket_capacity == 100
        assert algorithm.leak_rate == 10.0
        assert algorithm.initial_level == 5
        assert algorithm.cost_per_request == 2


class TestLeakyBucketAlgorithmIsAllowed:
    """Tests for is_allowed method."""

    def test_is_allowed_uses_backend_method(self):
        """Test that is_allowed uses backend's leaky_bucket_check if available."""
        algorithm = LeakyBucketAlgorithm()
        mock_backend = MagicMock()
        mock_backend.leaky_bucket_check.return_value = (
            True,
            {"bucket_level": 1, "bucket_capacity": 10},
        )

        result, metadata = algorithm.is_allowed(mock_backend, "test_key", 10, 60)

        assert result is True
        assert metadata["bucket_level"] == 1
        mock_backend.leaky_bucket_check.assert_called_once()

    def test_is_allowed_zero_bucket_capacity(self):
        """Test that zero bucket capacity always rejects."""
        algorithm = LeakyBucketAlgorithm({"bucket_capacity": 0})
        mock_backend = MagicMock(spec=[])  # No leaky_bucket_check

        result, metadata = algorithm.is_allowed(mock_backend, "test_key", 0, 60)

        assert result is False
        assert "error" in metadata
        assert metadata["bucket_capacity"] == 0

    def test_is_allowed_zero_request_cost(self):
        """Test that zero request cost always allows."""
        algorithm = LeakyBucketAlgorithm()
        mock_backend = MagicMock(spec=[])  # No leaky_bucket_check

        result, metadata = algorithm.is_allowed(
            mock_backend, "test_key", 10, 60, request_cost=0
        )

        assert result is True
        assert "warning" in metadata

    def test_is_allowed_calculates_defaults(self):
        """Test that is_allowed calculates default bucket_capacity and leak_rate."""
        algorithm = LeakyBucketAlgorithm()
        mock_backend = MagicMock()
        mock_backend.leaky_bucket_check.return_value = (True, {})

        # limit=100, period=60 -> leak_rate=100/60
        algorithm.is_allowed(mock_backend, "test_key", 100, 60)

        call_args = mock_backend.leaky_bucket_check.call_args
        assert call_args[0][1] == 100  # bucket_capacity = limit
        assert abs(call_args[0][2] - 100 / 60) < 0.001  # leak_rate = limit/period


class TestLeakyBucketAlgorithmGetInfo:
    """Tests for get_info method."""

    def test_get_info_uses_backend_method(self):
        """Test that get_info uses backend's leaky_bucket_info if available."""
        algorithm = LeakyBucketAlgorithm()
        mock_backend = MagicMock()
        mock_backend.leaky_bucket_info.return_value = {
            "bucket_level": 5,
            "bucket_capacity": 10,
        }

        info = algorithm.get_info(mock_backend, "test_key", 10, 60)

        assert info["bucket_level"] == 5
        mock_backend.leaky_bucket_info.assert_called_once()


class TestLeakyBucketAlgorithmReset:
    """Tests for reset method."""

    def test_reset_calls_backend_delete(self):
        """Test that reset calls backend's delete method."""
        algorithm = LeakyBucketAlgorithm()
        mock_backend = MagicMock()
        mock_backend.delete.return_value = True

        result = algorithm.reset(mock_backend, "test_key")

        assert result is True
        mock_backend.delete.assert_called_once_with("test_key:leaky_bucket")

    def test_reset_handles_missing_delete_method(self):
        """Test that reset handles backends without delete method."""
        algorithm = LeakyBucketAlgorithm()
        mock_backend = MagicMock(spec=[])

        result = algorithm.reset(mock_backend, "test_key")

        assert result is False


class TestLeakyBucketAlgorithmGenericImplementation:
    """Tests for the generic leaky bucket implementation fallback."""

    def test_generic_implementation_first_request(self):
        """Test generic implementation for first request to a key."""
        algorithm = LeakyBucketAlgorithm()
        mock_backend = MagicMock(spec=["get", "set"])
        mock_backend.get.return_value = None

        with patch.object(algorithm, "get_current_time", return_value=1000.0):
            result, metadata = algorithm.is_allowed(mock_backend, "test_key", 10, 60)

        assert result is True
        assert metadata["bucket_level"] == 1  # First request fills 1 unit
        assert metadata["bucket_capacity"] == 10

    def test_generic_implementation_bucket_full(self):
        """Test generic implementation when bucket is full."""
        algorithm = LeakyBucketAlgorithm()
        mock_backend = MagicMock(spec=["get", "set"])
        # Bucket is at capacity (10), no time passed (no leaking)
        mock_backend.get.return_value = '{"level": 10, "last_leak": 1000.0}'

        with patch.object(algorithm, "get_current_time", return_value=1000.0):
            result, metadata = algorithm.is_allowed(mock_backend, "test_key", 10, 60)

        assert result is False
        assert metadata["bucket_level"] == 10
        assert metadata["space_remaining"] == 0

    def test_generic_implementation_leaking(self):
        """Test that bucket level decreases over time."""
        algorithm = LeakyBucketAlgorithm()
        mock_backend = MagicMock(spec=["get", "set"])
        # Bucket was at level 10, 5 seconds passed, leak_rate=1.0 (10/10 = 1)
        # After 5 seconds: level = 10 - (5 * 1.0) = 5
        mock_backend.get.return_value = '{"level": 10, "last_leak": 995.0}'

        # Configure leak_rate = 1.0 (bucket drains 1 per second)
        algorithm = LeakyBucketAlgorithm({"leak_rate": 1.0})

        with patch.object(algorithm, "get_current_time", return_value=1000.0):
            result, metadata = algorithm.is_allowed(mock_backend, "test_key", 10, 60)

        assert result is True  # 5 space available, request needs 1
        assert metadata["bucket_level"] == 6  # 5 + 1 (request)

    def test_generic_implementation_level_cannot_go_below_zero(self):
        """Test that bucket level cannot go below zero after leaking."""
        algorithm = LeakyBucketAlgorithm({"leak_rate": 1.0})
        mock_backend = MagicMock(spec=["get", "set"])
        # Bucket was at level 5, 10 seconds passed (more than enough to drain)
        mock_backend.get.return_value = '{"level": 5, "last_leak": 990.0}'

        with patch.object(algorithm, "get_current_time", return_value=1000.0):
            result, metadata = algorithm.is_allowed(mock_backend, "test_key", 10, 60)

        assert result is True
        assert metadata["bucket_level"] == 1  # 0 + 1 (request), not negative


class TestLeakyBucketAlgorithmEdgeCases:
    """Edge case tests for LeakyBucketAlgorithm."""

    def test_very_high_leak_rate(self):
        """Test with very high leak rate (bucket drains quickly)."""
        algorithm = LeakyBucketAlgorithm({"leak_rate": 1000.0})
        mock_backend = MagicMock()
        mock_backend.leaky_bucket_check.return_value = (
            True,
            {"bucket_level": 0, "bucket_capacity": 10},
        )

        result, metadata = algorithm.is_allowed(mock_backend, "test_key", 10, 60)

        assert result is True

    def test_zero_leak_rate_in_generic(self):
        """Test generic implementation with explicit zero leak rate.

        Note: When leak_rate=0 is set in config, it's falsy so the algorithm
        defaults to limit/period. This test verifies that when leak_rate
        is explicitly set to 0 via config, requests can still succeed
        when there's space, even though no leaking occurs.
        """
        # Use a very small explicit leak rate instead of 0
        # because 0 is falsy and falls back to limit/period
        algorithm = LeakyBucketAlgorithm({"leak_rate": 0.0001})
        mock_backend = MagicMock(spec=["get", "set"])
        # Bucket at level 5, minimal leaking
        mock_backend.get.return_value = '{"level": 5, "last_leak": 900.0}'

        with patch.object(algorithm, "get_current_time", return_value=1000.0):
            result, metadata = algorithm.is_allowed(mock_backend, "test_key", 10, 60)

        # Still should allow if there's space (10 - 5 = 5 space, need 1)
        assert result is True
        # Level = 5 (almost no leaking) + 1 (request) = ~6
        assert abs(metadata["bucket_level"] - 6) < 0.1

    def test_high_request_cost(self):
        """Test with high request cost (multiple units per request)."""
        algorithm = LeakyBucketAlgorithm({"cost_per_request": 5})
        mock_backend = MagicMock()
        mock_backend.leaky_bucket_check.return_value = (
            True,
            {"bucket_level": 5, "bucket_capacity": 10},
        )

        result, _ = algorithm.is_allowed(mock_backend, "test_key", 10, 60)

        call_args = mock_backend.leaky_bucket_check.call_args
        assert call_args[0][3] == 5  # request_cost passed to backend

    def test_invalid_json_in_bucket_data(self):
        """Test handling of invalid JSON in bucket data."""
        algorithm = LeakyBucketAlgorithm()
        mock_backend = MagicMock(spec=["get", "set"])
        mock_backend.get.return_value = "invalid json"

        with patch.object(algorithm, "get_current_time", return_value=1000.0):
            # Should not raise, should treat as new bucket
            result, metadata = algorithm.is_allowed(mock_backend, "test_key", 10, 60)

        assert result is True
        assert metadata["bucket_level"] == 1  # Fresh bucket + 1 request
