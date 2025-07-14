#!/usr/bin/env python3
"""
Backend Configuration Examples

This demonstrates how to configure different backends for rate limiting,
including Redis, MongoDB, Database, and Multi-backend setups.
"""

# Example 1: Redis Backend Configuration
REDIS_BACKEND_CONFIG = {
    # Single Redis instance
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "password": None,
        "ssl": False,
        "ssl_cert_reqs": None,
        "ssl_ca_certs": None,
        "ssl_certfile": None,
        "ssl_keyfile": None,
        "connection_pool_kwargs": {
            "max_connections": 50,
            "retry_on_timeout": True,
        },
        "key_prefix": "ratelimit:",
        "algorithm": "sliding_window",  # or 'fixed_window'
    },
}

# Redis Cluster Configuration
REDIS_CLUSTER_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "hosts": [
            {"host": "redis-node-1.example.com", "port": 6379},
            {"host": "redis-node-2.example.com", "port": 6379},
            {"host": "redis-node-3.example.com", "port": 6379},
        ],
        "cluster": True,
        "password": "your-cluster-password",
        "ssl": True,
        "skip_full_coverage_check": True,
    },
}

# Redis Sentinel Configuration
REDIS_SENTINEL_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "sentinels": [
            ("sentinel-1.example.com", 26379),
            ("sentinel-2.example.com", 26379),
            ("sentinel-3.example.com", 26379),
        ],
        "service_name": "mymaster",
        "password": "redis-password",
        "sentinel_password": "sentinel-password",
        "db": 0,
    },
}


# Example 2: MongoDB Backend Configuration
MONGODB_BACKEND_CONFIG = {
    # Single MongoDB instance
    "RATELIMIT_BACKEND": "mongodb",
    "RATELIMIT_MONGODB": {
        "host": "localhost",
        "port": 27017,
        "database": "ratelimit",
        "collection": "rate_limit_entries",
        "counter_collection": "rate_limit_counters",
        "username": None,
        "password": None,
        "auth_source": "admin",
        "replica_set": None,
        "tls": False,
        "tls_ca_file": None,
        "tls_cert_file": None,
        "server_selection_timeout": 5000,
        "socket_timeout": 5000,
        "connect_timeout": 5000,
        "max_pool_size": 50,
        "min_pool_size": 0,
        "max_idle_time": 30000,
        "algorithm": "sliding_window",
    },
}

# MongoDB Atlas Configuration
MONGODB_ATLAS_CONFIG = {
    "RATELIMIT_BACKEND": "mongodb",
    "RATELIMIT_MONGODB": {
        "uri": "mongodb+srv://username:password@cluster0.mongodb.net/ratelimit?retryWrites=true&w=majority",
        "database": "ratelimit",
        "collection": "rate_limits",
        "counter_collection": "counters",
        "tls": True,
        "server_selection_timeout": 10000,
        "algorithm": "sliding_window",
    },
}

# MongoDB Replica Set Configuration
MONGODB_REPLICA_CONFIG = {
    "RATELIMIT_BACKEND": "mongodb",
    "RATELIMIT_MONGODB": {
        "hosts": [
            "mongo1.example.com:27017",
            "mongo2.example.com:27017",
            "mongo3.example.com:27017",
        ],
        "replica_set": "rs0",
        "database": "ratelimit",
        "username": "ratelimit_user",
        "password": "secure_password",
        "auth_source": "admin",
        "tls": True,
        "tls_ca_file": "/path/to/ca.pem",
        "read_preference": "secondaryPreferred",
    },
}


# Example 3: Database Backend Configuration
DATABASE_BACKEND_CONFIG = {
    "RATELIMIT_BACKEND": "database",
    "RATELIMIT_DATABASE": {
        "table_name": "django_smart_ratelimit_ratelimitentry",
        "cleanup_interval": 3600,  # seconds
        "algorithm": "sliding_window",
    },
}

# Database with custom model configuration
DATABASE_CUSTOM_MODEL_CONFIG = {
    "RATELIMIT_BACKEND": "database",
    "RATELIMIT_DATABASE": {
        "model": "myapp.models.CustomRateLimitEntry",
        "cleanup_interval": 1800,
        "algorithm": "fixed_window",
    },
}


# Example 4: Memory Backend Configuration
MEMORY_BACKEND_CONFIG = {
    "RATELIMIT_BACKEND": "memory",
    "RATELIMIT_MEMORY": {
        "max_entries": 10000,
        "cleanup_interval": 300,  # seconds
        "algorithm": "sliding_window",
    },
}


# Example 5: Multi-Backend Configuration
MULTI_BACKEND_CONFIG = {
    "RATELIMIT_BACKEND": "multi",
    # Define available backends
    "RATELIMIT_BACKENDS": {
        "redis_primary": {
            "backend": "django_smart_ratelimit.backends.redis_backend.RedisBackend",
            "config": {
                "host": "redis-primary.example.com",
                "port": 6379,
                "db": 0,
                "password": "redis-password",
                "connection_pool_kwargs": {
                    "max_connections": 100,
                },
            },
        },
        "redis_secondary": {
            "backend": "django_smart_ratelimit.backends.redis_backend.RedisBackend",
            "config": {
                "host": "redis-secondary.example.com",
                "port": 6379,
                "db": 0,
                "password": "redis-password",
            },
        },
        "mongodb_analytics": {
            "backend": "django_smart_ratelimit.backends.mongodb.MongoDBBackend",
            "config": {
                "uri": "mongodb://mongo.example.com:27017/ratelimit",
                "database": "ratelimit_analytics",
            },
        },
        "database_fallback": {
            "backend": "django_smart_ratelimit.backends.database.DatabaseBackend",
            "config": {},
        },
    },
    # Multi-backend strategy configuration
    "RATELIMIT_MULTI_BACKEND": {
        "backends": ["redis_primary", "database_fallback"],
        "strategy": "first_healthy",  # Options: first_healthy, all, majority
        "health_check_interval": 60,  # seconds
        "fallback_backend": "database_fallback",
        "parallel_execution": True,  # For 'all' strategy
        "timeout": 5.0,  # seconds
    },
}

# Multi-backend with different strategies
MULTI_BACKEND_STRATEGIES = {
    # Strategy 1: First Healthy (Failover)
    "first_healthy_config": {
        "backends": ["redis_primary", "redis_secondary", "database_fallback"],
        "strategy": "first_healthy",
        "health_check_interval": 30,
    },
    # Strategy 2: All Backends (Redundancy)
    "all_backends_config": {
        "backends": ["redis_primary", "mongodb_analytics"],
        "strategy": "all",
        "parallel_execution": True,
        "require_all_success": False,  # Continue if at least one succeeds
    },
    # Strategy 3: Majority Consensus
    "majority_config": {
        "backends": ["redis_primary", "redis_secondary", "database_fallback"],
        "strategy": "majority",
        "consensus_threshold": 2,  # At least 2 out of 3 must agree
    },
}


# Example 6: Environment-specific backend configurations

# Development environment
DEVELOPMENT_BACKEND = {
    "RATELIMIT_BACKEND": "memory",
    "RATELIMIT_MEMORY": {
        "max_entries": 1000,
        "cleanup_interval": 60,
    },
}

# Testing environment
TESTING_BACKEND = {
    "RATELIMIT_BACKEND": "memory",
    "RATELIMIT_MEMORY": {
        "max_entries": 100,
        "cleanup_interval": 10,
    },
}

# Staging environment
STAGING_BACKEND = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "redis-staging.example.com",
        "port": 6379,
        "db": 1,  # Different DB from production
        "password": "staging-password",
    },
}

# Production environment
PRODUCTION_BACKEND = {
    "RATELIMIT_BACKEND": "multi",
    "RATELIMIT_BACKENDS": {
        "redis_cluster": {
            "backend": "django_smart_ratelimit.backends.redis_backend.RedisBackend",
            "config": {
                "hosts": [
                    {"host": "redis-1.prod.example.com", "port": 6379},
                    {"host": "redis-2.prod.example.com", "port": 6379},
                    {"host": "redis-3.prod.example.com", "port": 6379},
                ],
                "cluster": True,
                "password": "production-redis-password",
                "ssl": True,
            },
        },
        "mongodb_backup": {
            "backend": "django_smart_ratelimit.backends.mongodb.MongoDBBackend",
            "config": {
                "uri": "mongodb+srv://prod-user:prod-pass@prod-cluster.mongodb.net/ratelimit",
                "database": "ratelimit_production",
                "tls": True,
            },
        },
    },
    "RATELIMIT_MULTI_BACKEND": {
        "backends": ["redis_cluster", "mongodb_backup"],
        "strategy": "first_healthy",
        "health_check_interval": 30,
    },
}


# Example 7: Custom backend implementation example
"""
# custom_backend.py

from django_smart_ratelimit.backends.base import BaseBackend
from typing import Any, Dict, Optional
import time

class CustomBackend(BaseBackend):
    '''Custom backend implementation example.'''

    def __init__(self, **config: Any) -> None:
        super().__init__()
        self.config = {
            'custom_setting': 'default_value',
            **config
        }
        self.storage = {}  # Simple in-memory storage for demo

    def is_rate_limited(self, key: str, limit: int, period: int) -> bool:
        '''Check if the key is rate limited.'''
        now = time.time()
        window_start = now - period

        # Clean old entries
        if key in self.storage:
            self.storage[key] = [
                timestamp for timestamp in self.storage[key]
                if timestamp > window_start
            ]
        else:
            self.storage[key] = []

        # Check if limit exceeded
        if len(self.storage[key]) >= limit:
            return True

        # Add current _request
        self.storage[key].append(now)
        return False

    def get_usage_count(self, key: str, period: int) -> int:
        '''Get current usage count for the key.'''
        if key not in self.storage:
            return 0

        now = time.time()
        window_start = now - period

        return len([
            timestamp for timestamp in self.storage[key]
            if timestamp > window_start
        ])

    def clear_key(self, key: str) -> None:
        '''Clear rate limit data for the key.'''
        if key in self.storage:
            del self.storage[key]

    def get_statistics(self) -> Dict[str, Any]:
        '''Get backend statistics.'''
        return {
            'backend_type': 'custom',
            'total_keys': len(self.storage),
            'total_requests': sum(len(requests) for requests in self.storage.values()),
            'custom_setting': self.config['custom_setting']
        }

    def health_check(self) -> Dict[str, Any]:
        '''Check backend health.'''
        return {
            'healthy': True,
            'backend': 'custom',
            'storage_keys': len(self.storage)
        }
"""

# Custom backend configuration
CUSTOM_BACKEND_CONFIG = {
    "RATELIMIT_BACKEND": "myapp.backends.CustomBackend",
    "RATELIMIT_CUSTOM": {
        "custom_setting": "production_value",
        "other_setting": 42,
    },
}


# Example: Backend configurations with algorithm parameter
REDIS_WITH_ALGORITHM_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "key_prefix": "ratelimit:",
        "algorithm": "sliding_window",  # Default algorithm for this backend
    },
}

MONGODB_WITH_ALGORITHM_CONFIG = {
    "RATELIMIT_BACKEND": "mongodb",
    "RATELIMIT_MONGODB": {
        "host": "localhost",
        "port": 27017,
        "database": "ratelimit",
        "collection": "rate_limit_entries",
        "counter_collection": "rate_limit_counters",
        "algorithm": "fixed_window",  # Default algorithm for MongoDB backend
    },
}

# Example: Using different algorithms per endpoint
from django_smart_ratelimit import rate_limit


# API endpoints with different algorithms
@rate_limit(key="ip", rate="100/h", algorithm="sliding_window")
def smooth_api(_request):
    """API using sliding window for smooth rate limiting."""
    return {"message": "Smooth rate limiting", "algorithm": "sliding_window"}


@rate_limit(key="ip", rate="100/h", algorithm="fixed_window")
def burst_api(_request):
    """API using fixed window for burst-tolerant rate limiting."""
    return {"message": "Burst-tolerant rate limiting", "algorithm": "fixed_window"}


# Using skip_if with backend configuration
@rate_limit(
    key="ip",
    rate="50/h",
    backend="redis",
    algorithm="sliding_window",
    skip_if=lambda _request: _request.user.is_superuser,
)
def admin_friendly_api(_request):
    """API that bypasses rate limiting for superusers."""
    return {
        "message": "Admin-friendly API",
        "bypassed": _request.user.is_superuser,
        "algorithm": "sliding_window",
    }


if __name__ == "__main__":
    print("Backend Configuration Examples")
    print("==============================")
    print("")
    print("This file contains examples of backend configurations:")
    print("1. Redis Backend (single, cluster, sentinel)")
    print("2. MongoDB Backend (single, Atlas, replica set)")
    print("3. Database Backend")
    print("4. Memory Backend")
    print("5. Multi-Backend configurations")
    print("6. Environment-specific configs")
    print("7. Custom backend implementation")
    print("")
    print("Choose the appropriate backend configuration based on")
    print("your infrastructure and requirements.")
