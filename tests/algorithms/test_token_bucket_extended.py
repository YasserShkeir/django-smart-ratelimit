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
        # tokens_consumed might not be in metadata for zero tokens
        self.assertIn("tokens_remaining", metadata)

    def test_algorithm_with_negative_tokens_requested(self):
        """Test algorithm with negative tokens requested."""
        # This should always be allowed
        is_allowed, metadata = self.algorithm.is_allowed(
            self.backend, "test_key", 10, 60, tokens_requested=-1
        )
        self.assertTrue(is_allowed)
        # tokens_consumed might not be in metadata for negative tokens
        self.assertIn("tokens_remaining", metadata)

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

    def test_algorithm_initialization_defaults(self):
        """Test algorithm initialization with defaults."""
        algorithm = TokenBucketAlgorithm()

        # Check that defaults are set
        self.assertIsNone(algorithm.bucket_size)
        self.assertIsNone(algorithm.refill_rate)
        self.assertIsNone(algorithm.initial_tokens)
        self.assertEqual(algorithm.tokens_per_request, 1)
        self.assertFalse(algorithm.allow_partial)
