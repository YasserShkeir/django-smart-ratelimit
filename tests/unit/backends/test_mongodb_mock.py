"""Tests for MongoDB backend using mocks."""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from django.core.exceptions import ImproperlyConfigured

from django_smart_ratelimit.exceptions import BackendError

try:
    import pymongo

    from django_smart_ratelimit.backends.mongodb import MongoDBBackend

    PYMONGO_AVAILABLE = True
except ImportError:
    PYMONGO_AVAILABLE = False


@pytest.mark.skipif(not PYMONGO_AVAILABLE, reason="pymongo not installed")
class TestMongoDBBackendMock(unittest.TestCase):
    """Tests for MongoDB backend using mocks."""

    def setUp(self):
        self.patcher = patch("django_smart_ratelimit.backends.mongodb.MongoClient")
        self.MockMongoClient = self.patcher.start()

        # Setup default mock behavior
        self.mock_client = MagicMock()
        self.MockMongoClient.return_value = self.mock_client
        self.mock_db = MagicMock()
        self.mock_client.__getitem__.return_value = self.mock_db
        self.mock_collection = MagicMock()
        self.mock_counter_collection = MagicMock()

        # The backend accesses db[collection] and db[counter_collection]
        def get_collection(name):
            if name == "rate_limit_counters":
                return self.mock_counter_collection
            return self.mock_collection

        self.mock_db.__getitem__.side_effect = get_collection

    def tearDown(self):
        self.patcher.stop()

    def test_connection_failure_handling_fail_closed(self):
        """Test behavior when MongoDB connection fails (fail_open=False)."""
        # Simulate connection failure on ping
        self.mock_client.admin.command.side_effect = pymongo.errors.ConnectionFailure(
            "Connection failed"
        )

        # Should raise ImproperlyConfigured during initialization
        with self.assertRaises(ImproperlyConfigured):
            MongoDBBackend(host="localhost", port=27017, fail_open=False)

    def test_ttl_index_creation(self):
        """Verify TTL index is created on collection."""
        # Reset mocks to track calls from init
        self.MockMongoClient.reset_mock()
        self.mock_collection.reset_mock()

        # Re-setup the chain
        self.MockMongoClient.return_value = self.mock_client
        self.mock_client.__getitem__.return_value = self.mock_db

        MongoDBBackend(host="localhost", port=27017)

        # Verify create_index was called with expireAfterSeconds
        self.mock_collection.create_index.assert_any_call(
            [("expires_at", pymongo.ASCENDING)],
            expireAfterSeconds=0,
            name="ttl_index",
            background=True,
        )

    def test_token_bucket_not_implemented(self):
        """Test that token bucket raises NotImplementedError."""
        backend = MongoDBBackend(host="localhost", port=27017)

        with self.assertRaises(NotImplementedError):
            backend.token_bucket_check("key", 10, 1.0, 10, 1)

    def test_fixed_window_retries_on_duplicate_key_error(self):
        """Concurrent first-hit DuplicateKeyError is retried, not propagated."""
        backend = MongoDBBackend(host="localhost", port=27017, algorithm="fixed_window")

        # First call simulates losing the concurrent insert race; the retry
        # then finds the document created by the winner and increments it.
        self.mock_counter_collection.find_one_and_update.side_effect = [
            pymongo.errors.DuplicateKeyError("E11000 duplicate key"),
            {"count": 2},
        ]

        count = backend.incr("user:1", 60)

        self.assertEqual(count, 2)
        self.assertEqual(self.mock_counter_collection.find_one_and_update.call_count, 2)

    def test_fixed_window_reraises_persistent_duplicate_key_error(self):
        """A persistent DuplicateKeyError surfaces via backend error handling."""
        backend = MongoDBBackend(host="localhost", port=27017, algorithm="fixed_window")

        # Every attempt raises: the retry loop exhausts (3 attempts) and
        # re-raises, which incr() funnels into _handle_backend_error.
        self.mock_counter_collection.find_one_and_update.side_effect = (
            pymongo.errors.DuplicateKeyError("E11000 duplicate key")
        )

        # With fail_open=False (default), incr() surfaces the exhausted error
        # as a BackendError rather than masking a persistent failure.
        with self.assertRaises(BackendError):
            backend.incr("user:1", 60)

        self.assertEqual(self.mock_counter_collection.find_one_and_update.call_count, 3)
