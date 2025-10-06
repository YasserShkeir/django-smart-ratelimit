"""Simplified extended tests for TokenBucketAlgorithm."""

import threading

from django.test import TestCase

from django_smart_ratelimit import MemoryBackend, TokenBucketAlgorithm


class TokenBucketAlgorithmSimpleExtendedTests(TestCase):
    """Simplified extended tests for TokenBucketAlgorithm implementation."""

    def setUp(self):
        """Set up test fixtures."""
        self.backend = MemoryBackend()
        self.algorithm = TokenBucketAlgorithm()

    def test_algorithm_with_custom_config(self):
        """Test algorithm with custom configuration."""
        config = {
            "bucket_size": 20,
            "refill_rate": 2.0,
            "initial_tokens": 10,
            "tokens_per_request": 2,
            "allow_partial": True,
        }
        algorithm = TokenBucketAlgorithm(config)

        # Test that algorithm is initialized with config
        self.assertEqual(algorithm.bucket_size, 20)
        self.assertEqual(algorithm.refill_rate, 2.0)
        self.assertEqual(algorithm.initial_tokens, 10)
        self.assertEqual(algorithm.tokens_per_request, 2)
        self.assertEqual(algorithm.allow_partial, True)

    def test_algorithm_with_zero_bucket_size(self):
        """Test algorithm with zero bucket size."""
        config = {"bucket_size": 0}
        algorithm = TokenBucketAlgorithm(config)

        self.assertEqual(algorithm.bucket_size, 0)

    def test_algorithm_with_custom_initial_tokens(self):
        """Test algorithm with custom initial tokens."""
        config = {"initial_tokens": 5}
        algorithm = TokenBucketAlgorithm(config)

        self.assertEqual(algorithm.initial_tokens, 5)

    def test_algorithm_with_fractional_refill_rate(self):
        """Test algorithm with fractional refill rate."""
        config = {"refill_rate": 0.5}
        algorithm = TokenBucketAlgorithm(config)

        self.assertEqual(algorithm.refill_rate, 0.5)

    def test_algorithm_with_multiple_tokens_per_request(self):
        """Test algorithm with multiple tokens per request."""
        config = {"tokens_per_request": 5}
        algorithm = TokenBucketAlgorithm(config)

        self.assertEqual(algorithm.tokens_per_request, 5)

    def test_algorithm_with_zero_tokens_requested(self):
        """Test algorithm with zero tokens requested."""
        # This should always be allowed
        is_allowed, metadata = self.algorithm.is_allowed(
            self.backend, "test_key", 10, 60, tokens_requested=0
        )
        self.assertTrue(is_allowed)
        self.assertEqual(metadata.get("tokens_consumed"), 0)
        self.assertIn("tokens_remaining", metadata)
        self.assertEqual(metadata.get("tokens_requested"), 0)
        self.assertIn("warning", metadata)

    def test_algorithm_with_negative_tokens_requested(self):
        """Test algorithm with negative tokens requested."""
        # This should always be allowed
        is_allowed, metadata = self.algorithm.is_allowed(
            self.backend, "test_key", 10, 60, tokens_requested=-1
        )
        self.assertTrue(is_allowed)
        self.assertEqual(metadata.get("tokens_consumed"), 0)
        self.assertIn("tokens_remaining", metadata)
        self.assertEqual(metadata.get("tokens_requested"), -1)
        self.assertIn("warning", metadata)

    def test_algorithm_concurrent_requests_simulation(self):
        """Test algorithm concurrent requests simulation."""
        # Create multiple threads that make requests
        results = []
        threads = []

        def make_request():
            try:
                is_allowed, metadata = self.algorithm.is_allowed(
                    self.backend, "test_key", 10, 60
                )
                results.append((is_allowed, metadata))
            except Exception as e:
                results.append((False, {"error": str(e)}))

        # Create and start threads
        for i in range(5):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Check that we got some results
        self.assertGreater(len(results), 0)
        self.assertEqual(len(results), 5)
        # New: all requests should be allowed and at least one consumed a token
        self.assertTrue(all(is_allowed for is_allowed, _ in results))
        self.assertTrue(
            any(meta.get("tokens_remaining", 0) < 10 for _, meta in results)
        )

    def test_is_allowed_with_zero_bucket_size(self):
        """is_allowed should reject when bucket_size is 0 with error metadata."""
        algorithm = TokenBucketAlgorithm({"bucket_size": 0})
        allowed, meta = algorithm.is_allowed(self.backend, "zero_key", 10, 60)
        self.assertFalse(allowed)
        self.assertEqual(meta.get("tokens_remaining"), 0)
        self.assertEqual(meta.get("bucket_size"), 0)
        self.assertIn("error", meta)
        self.assertEqual(meta.get("tokens_requested"), algorithm.tokens_per_request)

    def test_multiple_tokens_per_request_consumption_and_rejection(self):
        """First 7-token request allowed, second immediately after should be rejected."""
        algorithm = TokenBucketAlgorithm({"tokens_per_request": 7})
        # Bucket defaults to limit=10; initial tokens = 10
        allowed1, meta1 = algorithm.is_allowed(self.backend, "multi_req", 10, 60)
        self.assertTrue(allowed1)
        self.assertIn("tokens_remaining", meta1)
        # Allow small floating point tolerance around 3.0
        self.assertLessEqual(abs(meta1["tokens_remaining"] - 3.0), 1e-3)
        self.assertEqual(meta1.get("tokens_requested"), 7)

        # Immediate second call should be rejected (insufficient tokens)
        allowed2, meta2 = algorithm.is_allowed(self.backend, "multi_req", 10, 60)
        self.assertFalse(allowed2)
        self.assertIn("tokens_remaining", meta2)
        # Allow tiny tolerance due to time passage between calls
        self.assertLessEqual(
            abs(meta2["tokens_remaining"] - meta1["tokens_remaining"]), 1e-3
        )
        self.assertEqual(meta2.get("tokens_requested"), 7)

    def test_get_info_with_zero_bucket_size_falls_back_to_limit(self):
        """get_info uses limit when config bucket_size=0 (falsy)."""
        algorithm = TokenBucketAlgorithm({"bucket_size": 0})
        info = algorithm.get_info(self.backend, "info_zero", 10, 60)
        # Because get_info uses `self.bucket_size or limit`, 0 falls back to limit
        self.assertEqual(info.get("bucket_size"), 10)
        self.assertIn("tokens_remaining", info)
        self.assertLessEqual(info["tokens_remaining"], 10)

    def test_algorithm_initialization_defaults(self):
        """Test algorithm initialization with defaults."""
        algorithm = TokenBucketAlgorithm()

        # Check that defaults are set
        self.assertIsNone(algorithm.bucket_size)
        self.assertIsNone(algorithm.refill_rate)
        self.assertIsNone(algorithm.initial_tokens)
        self.assertEqual(algorithm.tokens_per_request, 1)
        self.assertFalse(algorithm.allow_partial)

    def test_get_info_and_reset_flow(self):
        """Ensure get_info exposes expected fields and reset is callable."""
        # Before any consumption
        info = self.algorithm.get_info(self.backend, "info_key", 10, 60)
        self.assertIn("tokens_remaining", info)
        self.assertIn("bucket_size", info)
        self.assertIn("refill_rate", info)
        self.assertLessEqual(info["tokens_remaining"], info["bucket_size"])

        # Consume once
        allowed, meta = self.algorithm.is_allowed(self.backend, "info_key", 10, 60)
        self.assertTrue(allowed)
        self.assertIn("tokens_remaining", meta)

        # Reset should not raise and ideally returns bool
        result = self.algorithm.reset(self.backend, "info_key")
        self.assertIsInstance(result, bool)

    def test_redis_backend_parity_if_available(self):
        """Test Redis backend with same extended API where available."""
        try:
            from django_smart_ratelimit import RedisBackend

            redis_backend = RedisBackend()

            # Skip if Redis not available
            try:
                redis_backend.set("test_connection", "value", 60)
            except:
                self.skipTest("Redis backend not available")

            # Test get_info parity
            info = self.algorithm.get_info(redis_backend, "redis_info_test", 10, 60)
            expected_fields = {"tokens_remaining", "bucket_size", "refill_rate"}
            self.assertTrue(
                expected_fields.issubset(info.keys()),
                f"get_info missing fields: {expected_fields - info.keys()}",
            )

            # Test reset parity
            result = self.algorithm.reset(redis_backend, "redis_reset_test")
            self.assertIsInstance(result, bool)

        except ImportError:
            self.skipTest("Redis backend not available")

    def test_get_info_field_stability_snapshot(self):
        """Snapshot test to ensure get_info field schema stays stable across versions."""
        # Fresh bucket
        info = self.algorithm.get_info(self.backend, "snapshot_test", 10, 60)

        # Essential fields that should always be present
        required_fields = {"tokens_remaining", "bucket_size", "refill_rate"}

        # Check required fields exist
        missing_fields = required_fields - info.keys()
        self.assertEqual(
            len(missing_fields),
            0,
            f"get_info missing required fields: {missing_fields}",
        )

        # Check field types are sensible
        self.assertIsInstance(info["tokens_remaining"], (int, float))
        self.assertIsInstance(info["bucket_size"], (int, float))
        self.assertIsInstance(info["refill_rate"], (int, float))

        # Optional fields that may be present
        optional_fields = {
            "time_to_refill",
            "last_refill",
            "tokens_requested",
            "tokens_consumed",
        }

        # Ensure no unexpected fields (helps catch schema changes)
        all_expected = required_fields | optional_fields
        unexpected = set(info.keys()) - all_expected
        self.assertEqual(
            len(unexpected), 0, f"get_info has unexpected new fields: {unexpected}"
        )

    def test_parametrized_memory_redis_backends(self):
        """Test same behavior across Memory and Redis backends where available."""
        backends = [("Memory", self.backend)]

        try:
            from django_smart_ratelimit import RedisBackend

            redis_backend = RedisBackend()
            try:
                redis_backend.set("param_test", "value", 60)
                backends.append(("Redis", redis_backend))
            except:
                pass  # Redis not available, skip
        except ImportError:
            pass  # Redis not installed

        for backend_name, backend in backends:
            with self.subTest(backend=backend_name):
                test_key = f"param_test_{backend_name.lower()}"

                # Test zero token request behavior
                is_allowed, metadata = self.algorithm.is_allowed(
                    backend, test_key, 10, 60, tokens_requested=0
                )
                self.assertTrue(is_allowed)
                self.assertEqual(metadata["tokens_consumed"], 0)

                # Test error metadata on rejection
                config = {"bucket_size": 0}
                algorithm = TokenBucketAlgorithm(config)
                is_allowed, metadata = algorithm.is_allowed(
                    backend, f"{test_key}_error", 10, 60
                )
                self.assertFalse(is_allowed)
                self.assertIn("error", metadata)
