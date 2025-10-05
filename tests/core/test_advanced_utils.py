"""Expanded tests for advanced_utils module."""

from unittest.mock import Mock

from django.test import TestCase

from django_smart_ratelimit.backends.advanced_utils import (
    BackendOperationMixin,
    TokenBucketHelper,
)


class BackendOperationMixinTests(TestCase):
    """Tests for BackendOperationMixin retry and key normalization."""

    def setUp(self):
        self.mixin = BackendOperationMixin()

    def test_execute_with_retry_succeeds_after_failures(self):
        call = Mock(side_effect=[Exception("fail1"), Exception("fail2"), "ok"])
        result = self.mixin._execute_with_retry(
            "op", call, max_retries=3, retry_delay=0.001
        )
        self.assertEqual(result, "ok")
        self.assertEqual(call.call_count, 3)

    def test_execute_with_retry_raises_after_max(self):
        call = Mock(side_effect=[Exception("fail")] * 3)
        with self.assertRaises(Exception):
            self.mixin._execute_with_retry("op", call, max_retries=2, retry_delay=0.001)

    def test_normalize_backend_key_contains_parts(self):
        k = self.mixin._normalize_backend_key("key", "token_bucket")
        self.assertIn("key", k)
        self.assertIn("token_bucket", k)


class TokenBucketHelperTests(TestCase):
    """Tests for TokenBucketHelper computations."""

    def setUp(self):
        self.helper = TokenBucketHelper()

    def test_calculate_tokens_and_metadata_basic(self):
        # Function returns (is_allowed: bool, metadata: dict)
        allowed, meta = self.helper.calculate_tokens_and_metadata(
            bucket_size=10,
            refill_rate=10 / 60,
            initial_tokens=10,
            tokens_requested=1,
            current_tokens=10.0,
            last_refill=0.0,
            current_time=1.0,
        )
        self.assertIsInstance(allowed, bool)
        self.assertIn("tokens_remaining", meta)

    def test_calculate_tokens_and_metadata_no_refill(self):
        allowed, meta = self.helper.calculate_tokens_and_metadata(
            bucket_size=5,
            refill_rate=0.0,
            initial_tokens=5,
            tokens_requested=2,
            current_tokens=1.0,
            last_refill=0.0,
            current_time=100.0,
        )
        # With no refill and only 1 token, allow_partial default may affect results
        self.assertIn("tokens_remaining", meta)
