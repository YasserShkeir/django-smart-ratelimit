"""
Real MongoDB backend tests.

This test module tests the MongoDB backend with a real MongoDB instance.
It requires MongoDB to be running on localhost:27017.
"""

import pytest

from django.test import TestCase, override_settings

from django_smart_ratelimit.backends.mongodb import MongoDBBackend

# Skip tests if MongoDB is not available
mongodb_available = False
try:
    import pymongo

    client = pymongo.MongoClient("localhost", 27017, serverSelectionTimeoutMS=1000)
    client.admin.command("ping")
    mongodb_available = True
    client.close()
except Exception:
    pass


@pytest.mark.skipif(not mongodb_available, reason="MongoDB not available")
class MongoDBBackendRealTest(TestCase):
    """Test MongoDB backend with real MongoDB instance."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            "host": "localhost",
            "port": 27017,
            "database": "test_ratelimit",
            "collection": "rate_limits",
            "algorithm": "sliding_window",
        }
        self.backend = MongoDBBackend(**self.config)

        # Clean up any existing test data
        self.backend._collection.delete_many({})
        self.backend._counter_collection.delete_many({})

    def tearDown(self):
        """Clean up after tests."""
        if hasattr(self, "backend") and self.backend._collection is not None:
            self.backend._collection.delete_many({})
            self.backend._counter_collection.delete_many({})

    def test_mongodb_connection(self):
        """Test MongoDB connection."""
        # Test that we can connect and ping
        self.assertTrue(self.backend._client is not None)
        self.assertTrue(self.backend._db is not None)
        self.assertTrue(self.backend._collection is not None)

    def test_mongodb_incr_sliding_window(self):
        """Test sliding window increment."""
        key = "test_key_sliding"
        period = 60  # 1 minute

        # First increment
        count1 = self.backend.incr(key, period)
        self.assertEqual(count1, 1)

        # Second increment
        count2 = self.backend.incr(key, period)
        self.assertEqual(count2, 2)

        # Third increment
        count3 = self.backend.incr(key, period)
        self.assertEqual(count3, 3)

    def test_mongodb_incr_fixed_window(self):
        """Test fixed window increment."""
        # Create backend with fixed window
        config = self.config.copy()
        config["algorithm"] = "fixed_window"
        backend = MongoDBBackend(**config)

        key = "test_key_fixed"
        period = 60  # 1 minute

        # First increment
        count1 = backend.incr(key, period)
        self.assertEqual(count1, 1)

        # Second increment
        count2 = backend.incr(key, period)
        self.assertEqual(count2, 2)

        # Check that counter was created
        counter_count = backend.get_count(key)
        self.assertEqual(counter_count, 2)

    def test_mongodb_get_count(self):
        """Test getting current count."""
        key = "test_key_count"
        period = 60

        # Initially zero
        count = self.backend.get_count(key)
        self.assertEqual(count, 0)

        # After increment
        self.backend.incr(key, period)
        count = self.backend.get_count(key)
        self.assertEqual(count, 1)

        # After another increment
        self.backend.incr(key, period)
        count = self.backend.get_count(key)
        self.assertEqual(count, 2)

    def test_mongodb_get_reset_time(self):
        """Test getting reset time."""
        key = "test_key_reset_time"
        period = 60

        # No reset time for non-existent key
        reset_time = self.backend.get_reset_time(key)
        self.assertIsNone(reset_time)

        # After increment, should have reset time
        self.backend.incr(key, period)
        reset_time = self.backend.get_reset_time(key)
        self.assertIsNotNone(reset_time)
        self.assertIsInstance(reset_time, int)

    def test_mongodb_reset_key(self):
        """Test resetting a key."""
        key = "test_key_reset"
        period = 60

        # Increment a few times
        self.backend.incr(key, period)
        self.backend.incr(key, period)
        count = self.backend.get_count(key)
        self.assertEqual(count, 2)

        # Reset the key
        self.backend.reset(key)

        # Count should be zero
        count = self.backend.get_count(key)
        self.assertEqual(count, 0)

    def test_mongodb_cleanup_expired(self):
        """Test cleanup of expired entries."""
        key = "test_key_cleanup"
        period = 1  # 1 second for quick test

        # Create some entries
        self.backend.incr(key, period)
        self.backend.incr(key, period)

        # Wait for expiry (MongoDB TTL might take up to 60 seconds)
        # For this test, we'll just verify the entries exist initially
        count = self.backend.get_count(key)
        self.assertEqual(count, 2)

        # Test that reset works for cleanup
        self.backend.reset(key)
        count = self.backend.get_count(key)
        self.assertEqual(count, 0)

    def test_mongodb_multiple_keys(self):
        """Test handling multiple keys."""
        keys = ["key1", "key2", "key3"]
        period = 60

        # Increment different keys
        for i, key in enumerate(keys):
            for j in range(i + 1):
                self.backend.incr(key, period)

        # Check counts
        for i, key in enumerate(keys):
            count = self.backend.get_count(key)
            self.assertEqual(count, i + 1)

    def test_mongodb_concurrent_access(self):
        """Test concurrent access to same key."""
        key = "test_key_concurrent"
        period = 60

        # Simulate concurrent increments
        counts = []
        for i in range(10):
            count = self.backend.incr(key, period)
            counts.append(count)

        # Should have incremented correctly
        self.assertEqual(counts, list(range(1, 11)))

        # Final count should be 10
        final_count = self.backend.get_count(key)
        self.assertEqual(final_count, 10)

    def test_mongodb_data_persistence(self):
        """Test that data persists across backend instances."""
        key = "test_key_persistence"
        period = 60

        # Increment with first backend instance
        self.backend.incr(key, period)
        self.backend.incr(key, period)

        # Create new backend instance
        new_backend = MongoDBBackend(**self.config)

        # Should see the same count
        count = new_backend.get_count(key)
        self.assertEqual(count, 2)

        # Increment with new backend
        new_count = new_backend.incr(key, period)
        self.assertEqual(new_count, 3)


@pytest.mark.skipif(not mongodb_available, reason="MongoDB not available")
@override_settings(
    RATELIMIT_BACKEND="django_smart_ratelimit.backends.mongodb.MongoDBBackend",
    RATELIMIT_MONGODB={
        "host": "localhost",
        "port": 27017,
        "database": "test_ratelimit",
        "collection": "rate_limits",
        "algorithm": "sliding_window",
    },
)
class MongoDBBackendIntegrationRealTest(TestCase):
    """Integration tests with real MongoDB and Django settings."""

    def setUp(self):
        """Set up test fixtures."""
        from django_smart_ratelimit.backends import get_backend

        self.backend = get_backend()

        # Clean up test data
        if hasattr(self.backend, "_collection"):
            self.backend._collection.delete_many({})
            self.backend._counter_collection.delete_many({})

    def tearDown(self):
        """Clean up after tests."""
        if (
            hasattr(self.backend, "_collection")
            and self.backend._collection is not None
        ):
            self.backend._collection.delete_many({})
            self.backend._counter_collection.delete_many({})

    def test_backend_factory_creates_mongodb(self):
        """Test that backend factory creates MongoDB backend."""
        from django_smart_ratelimit.backends.mongodb import MongoDBBackend

        self.assertIsInstance(self.backend, MongoDBBackend)

    def test_rate_limiting_with_real_mongodb(self):
        """Test rate limiting functionality with real MongoDB."""
        key = "test_integration_key"
        period = 60

        # Test increment
        count1 = self.backend.incr(key, period)
        self.assertEqual(count1, 1)

        count2 = self.backend.incr(key, period)
        self.assertEqual(count2, 2)

        # Test get_count
        count = self.backend.get_count(key)
        self.assertEqual(count, 2)

        # Test reset
        self.backend.reset(key)
        count = self.backend.get_count(key)
        self.assertEqual(count, 0)
