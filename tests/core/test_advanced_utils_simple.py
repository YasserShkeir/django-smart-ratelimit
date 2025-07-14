"""Simplified tests for advanced_utils module."""


from django.test import TestCase

from django_smart_ratelimit.backends.advanced_utils import (
    BackendOperationMixin,
    TokenBucketHelper,
)


class BackendOperationMixinSimpleTests(TestCase):
    """Simplified tests for BackendOperationMixin."""

    def setUp(self):
        """Set up test fixtures."""
        self.mixin = BackendOperationMixin()

    def test_initialization(self):
        """Test mixin initialization."""
        self.assertIsInstance(self.mixin, BackendOperationMixin)

    def test_retry_operation_max_retries_exceeded(self):
        """Test retry operation when max retries exceeded."""

        def failing_operation():
            raise Exception("Operation failed")

        with self.assertRaises(Exception):
            self.mixin._execute_with_retry("test_op", failing_operation, max_retries=2)

    def test_normalize_backend_key(self):
        """Test normalize backend key."""
        normalized = self.mixin._normalize_backend_key("test_key", "token_bucket")
        self.assertIn("test_key", normalized)


class TokenBucketHelperSimpleTests(TestCase):
    """Simplified tests for TokenBucketHelper."""

    def setUp(self):
        """Set up test fixtures."""
        self.helper = TokenBucketHelper()

    def test_initialization(self):
        """Test helper initialization."""
        self.assertIsInstance(self.helper, TokenBucketHelper)

    def test_calculate_tokens_and_metadata(self):
        """Test calculate tokens and metadata method."""
        # This method exists according to the error message
        result = self.helper.calculate_tokens_and_metadata(
            bucket_size=10,
            refill_rate=10 / 60,
            initial_tokens=10,
            tokens_requested=1,
            current_tokens=10.0,
            last_refill=0.0,
            current_time=1.0,
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)  # tokens and metadata
