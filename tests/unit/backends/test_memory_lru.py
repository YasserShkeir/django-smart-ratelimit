from django_smart_ratelimit.backends.memory import MemoryBackend


class TestMemoryLRU:
    def test_lru_eviction(self):
        # Initialize backend with small limit
        backend = MemoryBackend(max_keys=5, cleanup_interval=60)

        # Add 5 items (fill capacity)
        for i in range(5):
            backend.incr(f"key_{i}", period=60)

        # Verify all are present
        for i in range(5):
            assert backend.get_count(f"key_{i}", period=60) == 1

        # Add 6th item - should evict key_0 (oldest)
        backend.incr("key_5", period=60)

        # key_0 should be gone (count 0), key_5 present
        assert backend.get_count("key_0", period=60) == 0
        assert backend.get_count("key_5", period=60) == 1

        # Verify size
        if hasattr(backend, "_data"):
            assert len(backend._data) <= 5

    def test_lru_access_update(self):
        """Verify that accessing a key updates its position in LRU."""
        backend = MemoryBackend(max_keys=3)

        backend.incr("k1", 60)
        backend.incr("k2", 60)
        backend.incr("k3", 60)

        # Access k1 again, moving it to MRU
        backend.incr("k1", 60)

        # Add k4 - should evict k2 (LRU), not k1
        backend.incr("k4", 60)

        assert backend.get_count("k2", 60) == 0  # Evicted
        assert backend.get_count("k1", 60) == 2  # Kept
        assert backend.get_count("k4", 60) == 1  # Added
