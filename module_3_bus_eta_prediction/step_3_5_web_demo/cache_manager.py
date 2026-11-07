"""
Module 3 - Step 3.5: In-Memory TTL Cache Manager.
Provides thread-safe caching with time-to-live (TTL) expiration to prevent overwhelming
upstream BusMap Gateway during concurrent passenger polling.
"""

import threading
import time
from typing import Any, Dict, Optional, Tuple


class InMemoryTtlCache:
    """
    Thread-safe, lightweight in-memory TTL cache.
    Stores key-value pairs with individual epoch expiration timestamps.
    """

    def __init__(self, default_ttl_seconds: float = 15.0) -> None:
        self.default_ttl = default_ttl_seconds
        self._lock = threading.Lock()
        # Key -> (value, expire_epoch)
        self._store: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Retrieves a cached value if it exists and has not expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            val, expire_at = entry
            if time.time() > expire_at:
                del self._store[key]
                return None
            return val

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """Stores a value with a specified or default TTL in seconds."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expire_at = time.time() + max(0.1, ttl)
        with self._lock:
            self._store[key] = (value, expire_at)

    def count(self) -> int:
        """Returns the count of active (non-expired) items in cache."""
        now = time.time()
        with self._lock:
            return sum(1 for _, expire_at in self._store.values() if expire_at > now)

    def clear(self) -> None:
        """Clears all stored entries."""
        with self._lock:
            self._store.clear()

    def cleanup(self) -> int:
        """Prunes expired items and returns number of evicted entries."""
        now = time.time()
        evicted = 0
        with self._lock:
            keys_to_del = [k for k, (_, expire_at) in self._store.items() if expire_at <= now]
            for k in keys_to_del:
                del self._store[k]
                evicted += 1
        return evicted


# Global singleton instance for the web service
route_eta_cache = InMemoryTtlCache(default_ttl_seconds=15.0)
