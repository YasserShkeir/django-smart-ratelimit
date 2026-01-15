import time

from django.test import TestCase

from django_smart_ratelimit.backends.memory import MemoryBackend
from django_smart_ratelimit.backends.utils import get_current_timestamp


class MemoryCleanupTests(TestCase):
    def test_background_cleanup(self):
        """Test that background thread cleans up expired items."""
        # Setup backend with short cleanup interval
        backend = MemoryBackend(
            cleanup_interval=1, enable_background_cleanup=True, max_keys=100
        )

        try:
            # Add an expired entry manually
            key = "expired_key"
            expired_time = get_current_timestamp() - 10
            # Format: {key: (expiry_time, [(timestamp, unique_id), ...])}
            with backend._lock:
                backend._data[key] = (expired_time, [])
                # Also add to partitions if using partitions
                if hasattr(backend, "_update_partition"):
                    backend._update_partition(key, expired_time)

            # Verify it exists
            with backend._lock:
                self.assertIn(key, backend._data)

            # Wait for cleanup (should run ~1 second + processing time)
            time.sleep(2.5)

            # Verify it's gone
            with backend._lock:
                self.assertNotIn(key, backend._data)

        finally:
            backend.shutdown()

    def test_get_stats(self):
        """Test memory stats generation."""
        backend = MemoryBackend()
        try:
            stats = backend.get_stats()
            self.assertIn("estimated_memory_bytes", stats)
            self.assertIsInstance(stats["estimated_memory_bytes"], int)
        finally:
            backend.shutdown()
