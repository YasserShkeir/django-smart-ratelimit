"""
MongoDB backend for rate limiting using TTL collections.

This backend uses MongoDB with TTL (Time To Live) indexes to implement
rate limiting with automatic cleanup of expired entries.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseBackend

try:
    import pymongo
    from pymongo import MongoClient
    from pymongo.collection import Collection
    from pymongo.database import Database
    from pymongo.errors import (
        ConnectionFailure,
        DuplicateKeyError,
        OperationFailure,
        ServerSelectionTimeoutError,
    )
except ImportError:
    pymongo = None
    MongoClient = None
    Collection = None
    Database = None
    ConnectionFailure = None
    DuplicateKeyError = None
    OperationFailure = None
    ServerSelectionTimeoutError = None

logger = logging.getLogger(__name__)


class MongoDBBackend(BaseBackend):
    """
    MongoDB backend implementation using TTL collections.

    This backend uses MongoDB collections with TTL indexes to automatically
    clean up expired rate limit entries. It supports both sliding window
    and fixed window algorithms.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the MongoDB backend with connection and configuration."""
        if pymongo is None:
            raise ImproperlyConfigured(
                "MongoDB backend requires the pymongo package. "
                "Install it with: pip install pymongo"
            )

        # Get MongoDB configuration from settings
        mongo_config = getattr(settings, "RATELIMIT_MONGODB", {})

        # Default configuration
        self.config = {
            "host": "localhost",
            "port": 27017,
            "database": "ratelimit",
            "collection": "rate_limit_entries",
            "counter_collection": "rate_limit_counters",
            "username": None,
            "password": None,
            "auth_source": None,
            "replica_set": None,
            "tls": False,
            "tls_ca_file": None,
            "tls_cert_file": None,
            "tls_key_file": None,
            "server_selection_timeout": 5000,  # milliseconds
            "socket_timeout": 5000,  # milliseconds
            "connect_timeout": 5000,  # milliseconds
            "max_pool_size": 50,
            "min_pool_size": 0,
            "max_idle_time": 30000,  # 30 seconds
            "algorithm": "sliding_window",  # or "fixed_window"
            **mongo_config,
            **kwargs,
        }

        # Initialize connection
        self._client = None
        self._db = None
        self._collection = None
        self._counter_collection = None

        # Initialize connection and collections
        self._connect()
        self._setup_collections()

    def _connect(self) -> None:
        """Establish MongoDB connection."""
        try:
            # Build connection URI
            uri_parts = []

            # Authentication
            if self.config["username"] and self.config["password"]:
                auth_part = f"{self.config['username']}:{self.config['password']}"
                if self.config["auth_source"]:
                    auth_part += f"@{self.config['auth_source']}"
                uri_parts.append(f"mongodb://{auth_part}@")
            else:
                uri_parts.append("mongodb://")

            # Host and port
            uri_parts.append(f"{self.config['host']}:{self.config['port']}")

            # Database
            uri_parts.append(f"/{self.config['database']}")

            # Options
            options = []
            if self.config["replica_set"]:
                options.append(f"replicaSet={self.config['replica_set']}")
            if self.config["tls"]:
                options.append("tls=true")
                if self.config["tls_ca_file"]:
                    options.append(f"tlsCAFile={self.config['tls_ca_file']}")
                if self.config["tls_cert_file"]:
                    options.append(
                        f"tlsCertificateKeyFile={self.config['tls_cert_file']}"
                    )
            if self.config["auth_source"]:
                options.append(f"authSource={self.config['auth_source']}")

            if options:
                uri_parts.append(f"?{'&'.join(options)}")

            uri = "".join(uri_parts)

            # Create client with connection options
            self._client = MongoClient(
                uri,
                serverSelectionTimeoutMS=self.config["server_selection_timeout"],
                socketTimeoutMS=self.config["socket_timeout"],
                connectTimeoutMS=self.config["connect_timeout"],
                maxPoolSize=self.config["max_pool_size"],
                minPoolSize=self.config["min_pool_size"],
                maxIdleTimeMS=self.config["max_idle_time"],
            )

            # Test connection
            if self._client is None:
                raise ImproperlyConfigured("MongoDB client not initialized")
            self._client.admin.command("ping")

            # Get database and collections
            self._db = self._client[self.config["database"]]
            self._collection = self._db[self.config["collection"]]
            self._counter_collection = self._db[self.config["counter_collection"]]

            logger.info(
                f"Connected to MongoDB at {self.config['host']}:{self.config['port']}"
            )

        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise ImproperlyConfigured(f"Cannot connect to MongoDB: {e}")

    def _setup_collections(self) -> None:
        """Set up MongoDB collections with appropriate indexes."""
        if self._collection is None or self._counter_collection is None:
            raise ImproperlyConfigured("MongoDB collections not initialized")

        try:
            # Create TTL index for automatic cleanup of expired entries
            self._collection.create_index(
                [("expires_at", pymongo.ASCENDING)],
                expireAfterSeconds=0,  # TTL based on the expires_at field value
                name="ttl_index",
                background=True,
            )

            # Create compound index for efficient querying
            self._collection.create_index(
                [("key", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)],
                name="key_timestamp_index",
                background=True,
            )

            # Create index for counter collection
            self._counter_collection.create_index(
                [("key", pymongo.ASCENDING), ("window_start", pymongo.ASCENDING)],
                name="counter_key_window_index",
                unique=True,
                background=True,
            )

            # Create TTL index for counter collection
            self._counter_collection.create_index(
                [("expires_at", pymongo.ASCENDING)],
                expireAfterSeconds=0,
                name="counter_ttl_index",
                background=True,
            )

            logger.info("MongoDB collections and indexes created successfully")

        except OperationFailure as e:
            logger.error(f"Failed to create MongoDB indexes: {e}")
            raise ImproperlyConfigured(f"Cannot create MongoDB indexes: {e}")

    def _get_window_times(self, window_seconds: int) -> tuple[datetime, datetime]:
        """Get the start and end times for a fixed window."""
        now = datetime.now(timezone.utc)

        # Calculate the start of the current window
        seconds_since_epoch = int(now.timestamp())
        window_start_seconds = (seconds_since_epoch // window_seconds) * window_seconds
        window_start = datetime.fromtimestamp(window_start_seconds, timezone.utc)
        window_end = window_start + timedelta(seconds=window_seconds)

        return window_start, window_end

    def _incr_sliding_window(self, key: str, period: int) -> int:
        """Increment counter for sliding window algorithm."""
        if self._collection is None:
            raise ImproperlyConfigured("MongoDB collection not initialized")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=period)
        window_start = now - timedelta(seconds=period)

        # Insert new entry
        entry = {
            "key": key,
            "timestamp": now,
            "expires_at": expires_at,
            "algorithm": "sliding_window",
        }

        try:
            self._collection.insert_one(entry)
        except OperationFailure as e:
            logger.error(f"Failed to insert rate limit entry: {e}")
            raise

        # Count entries in the current window
        count = self._collection.count_documents(
            {"key": key, "timestamp": {"$gte": window_start}}
        )

        return count

    def _incr_fixed_window(self, key: str, period: int) -> int:
        """Increment counter for fixed window algorithm."""
        if self._counter_collection is None:
            raise ImproperlyConfigured("MongoDB counter collection not initialized")

        window_start, window_end = self._get_window_times(period)
        expires_at = window_end + timedelta(seconds=60)  # Keep for a bit longer

        # Use upsert to atomically increment or create counter
        result = self._counter_collection.find_one_and_update(
            {
                "key": key,
                "window_start": window_start,
                "window_end": window_end,
            },
            {
                "$inc": {"count": 1},
                "$set": {"expires_at": expires_at},
                "$setOnInsert": {
                    "key": key,
                    "window_start": window_start,
                    "window_end": window_end,
                    "algorithm": "fixed_window",
                },
            },
            upsert=True,
            return_document=pymongo.ReturnDocument.AFTER,
        )

        return result["count"] if result else 1

    def incr(self, key: str, period: int) -> int:
        """
        Increment the counter for the given key within the time period.

        Args:
            key: The rate limit key
            period: Time period in seconds

        Returns:
            Current count after increment
        """
        if self._collection is None:
            raise ImproperlyConfigured("MongoDB backend not properly initialized")

        try:
            if self.config["algorithm"] == "fixed_window":
                return self._incr_fixed_window(key, period)
            else:
                return self._incr_sliding_window(key, period)
        except Exception as e:
            logger.error(f"Error incrementing counter for key {key}: {e}")
            # Return a high count to fail-safe by denying the request
            return 9999

    def get_count(self, key: str) -> int:
        """
        Get the current count for the given key.

        Args:
            key: The rate limit key

        Returns:
            Current count (0 if key doesn't exist)
        """
        if self._collection is None:
            return 0

        try:
            if self.config["algorithm"] == "fixed_window":
                # For fixed window, get the current window counter
                now = datetime.now(timezone.utc)
                # Find the most recent counter for this key
                counter = self._counter_collection.find_one(
                    {"key": key}, sort=[("window_start", pymongo.DESCENDING)]
                )

                if counter and self._ensure_utc_aware(counter["window_end"]) > now:
                    return counter["count"]
                return 0
            else:
                # For sliding window, count recent entries
                # We don't know the exact period, so we use a reasonable default
                window_start = datetime.now(timezone.utc) - timedelta(
                    seconds=3600
                )  # 1 hour default
                return self._collection.count_documents(
                    {"key": key, "timestamp": {"$gte": window_start}}
                )
        except Exception as e:
            logger.error(f"Error getting count for key {key}: {e}")
            return 0

    def get_reset_time(self, key: str) -> Optional[int]:
        """
        Get the timestamp when the key will reset.

        Args:
            key: The rate limit key

        Returns:
            Unix timestamp when key expires, or None if key doesn't exist
        """
        if self._collection is None:
            return None

        try:
            if self.config["algorithm"] == "fixed_window":
                # For fixed window, get the window end time
                counter = self._counter_collection.find_one(
                    {"key": key}, sort=[("window_start", pymongo.DESCENDING)]
                )

                if counter and self._ensure_utc_aware(
                    counter["window_end"]
                ) > datetime.now(timezone.utc):
                    return int(counter["window_end"].timestamp())
                return None
            else:
                # For sliding window, find the earliest expiry time
                entry = self._collection.find_one(
                    {"key": key}, sort=[("expires_at", pymongo.ASCENDING)]
                )

                if entry and self._ensure_utc_aware(entry["expires_at"]) > datetime.now(
                    timezone.utc
                ):
                    return int(entry["expires_at"].timestamp())
                return None
        except Exception as e:
            logger.error(f"Error getting reset time for key {key}: {e}")
            return None

    def reset(self, key: str) -> None:
        """
        Reset the counter for the given key.

        Args:
            key: The rate limit key to reset
        """
        if self._collection is None or self._counter_collection is None:
            return

        try:
            # Remove all entries for this key
            self._collection.delete_many({"key": key})

            # Remove counters for this key
            self._counter_collection.delete_many({"key": key})

            logger.debug(f"Reset rate limit for key: {key}")
        except Exception as e:
            logger.error(f"Error resetting key {key}: {e}")

    def health_check(self) -> bool:
        """
        Check if the MongoDB backend is healthy.

        Returns:
            True if healthy, False otherwise
        """
        try:
            if self._client is None:
                return False

            # Test connection with a simple ping
            self._client.admin.command("ping")
            return True
        except Exception as e:
            logger.error(f"MongoDB health check failed: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the MongoDB backend.

        Returns:
            Dictionary containing backend statistics
        """
        stats = {
            "backend_type": "mongodb",
            "algorithm": self.config["algorithm"],
            "connected": self.health_check(),
            "database": self.config["database"],
            "collection": self.config["collection"],
        }

        try:
            if self._db is not None:
                # Get collection stats
                collection_stats = self._db.command(
                    "collStats", self.config["collection"]
                )
                stats.update(
                    {
                        "total_documents": collection_stats.get("count", 0),
                        "total_size": collection_stats.get("size", 0),
                        "average_document_size": collection_stats.get("avgObjSize", 0),
                    }
                )
        except Exception as e:
            logger.error(f"Error getting MongoDB stats: {e}")

        return stats

    def close(self) -> None:
        """Close the MongoDB connection."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None
            self._collection = None
            self._counter_collection = None
            logger.info("MongoDB connection closed")

    def __del__(self) -> None:
        """Ensure connection is closed when backend is destroyed."""
        try:
            self.close()
        except AttributeError:
            # Object may not be fully initialized
            pass

    def _ensure_utc_aware(self, dt: datetime) -> datetime:
        """Ensure datetime is UTC-aware for comparison with stored values."""
        if dt.tzinfo is None:
            # Naive datetime, assume it's UTC
            return dt.replace(tzinfo=timezone.utc)
        return dt
