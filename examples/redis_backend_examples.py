#!/usr/bin/env python3
"""
Redis Backend Examples

This demonstrates specific Redis backend configurations and usage patterns
for high-performance rate limiting in production environments.
"""

# Example 1: Basic Redis Configuration
BASIC_REDIS_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "password": None,
        "key_prefix": "ratelimit:",
        "algorithm": "sliding_window",  # or 'fixed_window'
    },
}

# Example 2: Production Redis with SSL
PRODUCTION_REDIS_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "redis.production.example.com",
        "port": 6380,  # Custom port
        "db": 0,
        "password": "your-secure-redis-password",
        "ssl": True,
        "ssl_cert_reqs": "required",
        "ssl_ca_certs": "/path/to/ca-certificates.crt",
        "ssl_certfile": "/path/to/client.crt",
        "ssl_keyfile": "/path/to/client.key",
        "connection_pool_kwargs": {
            "max_connections": 100,
            "retry_on_timeout": True,
            "socket_keepalive": True,
            "socket_keepalive_options": {
                "TCP_KEEPIDLE": 1,
                "TCP_KEEPINTVL": 3,
                "TCP_KEEPCNT": 5,
            },
        },
        "key_prefix": "prod_ratelimit:",
        "algorithm": "sliding_window",
    },
}

# Example 3: Redis Cluster Configuration
REDIS_CLUSTER_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "cluster": True,
        "hosts": [
            {"host": "redis-cluster-1.example.com", "port": 6379},
            {"host": "redis-cluster-2.example.com", "port": 6379},
            {"host": "redis-cluster-3.example.com", "port": 6379},
            {"host": "redis-cluster-4.example.com", "port": 6379},
            {"host": "redis-cluster-5.example.com", "port": 6379},
            {"host": "redis-cluster-6.example.com", "port": 6379},
        ],
        "password": "cluster-password",
        "ssl": True,
        "skip_full_coverage_check": True,
        "connection_pool_kwargs": {
            "max_connections_per_node": 50,
            "retry_on_timeout": True,
        },
        "key_prefix": "cluster_ratelimit:",
        "algorithm": "sliding_window",
    },
}

# Example 4: Redis Sentinel Configuration (High Availability)
REDIS_SENTINEL_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "sentinel": True,
        "sentinels": [
            ("sentinel-1.example.com", 26379),
            ("sentinel-2.example.com", 26379),
            ("sentinel-3.example.com", 26379),
        ],
        "service_name": "mymaster",
        "password": "redis-password",
        "sentinel_password": "sentinel-password",
        "db": 0,
        "socket_timeout": 0.5,
        "socket_connect_timeout": 0.5,
        "connection_pool_kwargs": {
            "max_connections": 50,
        },
        "key_prefix": "sentinel_ratelimit:",
        "algorithm": "sliding_window",
    },
}

# Example 5: Redis with Connection Pooling Optimization
OPTIMIZED_REDIS_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "redis.example.com",
        "port": 6379,
        "db": 1,  # Separate DB for rate limiting
        "password": "redis-password",
        "connection_pool_kwargs": {
            "max_connections": 200,  # High connection limit for busy servers
            "retry_on_timeout": True,
            "health_check_interval": 30,  # Health check every 30 seconds
            "socket_keepalive": True,
            "socket_keepalive_options": {
                "TCP_KEEPIDLE": 1,
                "TCP_KEEPINTVL": 3,
                "TCP_KEEPCNT": 5,
            },
            "socket_timeout": 5.0,
            "socket_connect_timeout": 5.0,
        },
        "key_prefix": "opt_ratelimit:",
        "key_expiry": 3600,  # TTL for keys in seconds
        "algorithm": "sliding_window",
    },
}

# Example 6: Redis with Custom Key Patterns
CUSTOM_KEY_REDIS_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "key_prefix": "rl:",  # Short prefix to save memory
        "key_patterns": {
            "ip": "ip:{ip}",
            "user": "u:{user_id}",
            "api_key": "ak:{api_key_hash}",
            "tenant": "t:{tenant_id}",
            "geographic": "geo:{country}:{ip}",
        },
        "algorithm": "sliding_window",
    },
}

# Example 7: Environment-Specific Redis Configurations

# Development
DEVELOPMENT_REDIS = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "localhost",
        "port": 6379,
        "db": 15,  # High DB number for dev
        "password": None,
        "key_prefix": "dev_rl:",
        "connection_pool_kwargs": {
            "max_connections": 10,  # Low limit for dev
        },
    },
}

# Testing
TESTING_REDIS = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "localhost",
        "port": 6379,
        "db": 14,  # Separate DB for tests
        "password": None,
        "key_prefix": "test_rl:",
        "connection_pool_kwargs": {
            "max_connections": 5,
        },
        "flush_on_startup": True,  # Clear all keys when starting tests
    },
}

# Staging
STAGING_REDIS = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "redis-staging.example.com",
        "port": 6379,
        "db": 0,
        "password": "staging-password",
        "ssl": True,
        "key_prefix": "staging_rl:",
        "connection_pool_kwargs": {
            "max_connections": 50,
            "retry_on_timeout": True,
        },
    },
}

# Production with Multiple Redis Instances
PRODUCTION_MULTI_REDIS = {
    "RATELIMIT_BACKEND": "multi",
    "RATELIMIT_BACKENDS": {
        "redis_primary": {
            "backend": "django_smart_ratelimit.backends.redis_backend.RedisBackend",
            "config": {
                "host": "redis-primary.prod.example.com",
                "port": 6379,
                "db": 0,
                "password": "primary-redis-password",
                "ssl": True,
                "connection_pool_kwargs": {
                    "max_connections": 100,
                    "retry_on_timeout": True,
                },
                "key_prefix": "prod_primary:",
            },
        },
        "redis_secondary": {
            "backend": "django_smart_ratelimit.backends.redis_backend.RedisBackend",
            "config": {
                "host": "redis-secondary.prod.example.com",
                "port": 6379,
                "db": 0,
                "password": "secondary-redis-password",
                "ssl": True,
                "connection_pool_kwargs": {
                    "max_connections": 100,
                    "retry_on_timeout": True,
                },
                "key_prefix": "prod_secondary:",
            },
        },
    },
    "RATELIMIT_MULTI_BACKEND": {
        "backends": ["redis_primary", "redis_secondary"],
        "strategy": "first_healthy",
        "health_check_interval": 30,
        "fallback_backend": "redis_secondary",
    },
}


# Example 8: Redis with Performance Monitoring
MONITORED_REDIS_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "redis.example.com",
        "port": 6379,
        "db": 0,
        "password": "redis-password",
        "connection_pool_kwargs": {
            "max_connections": 100,
            "retry_on_timeout": True,
        },
        "key_prefix": "monitored_rl:",
        # Performance monitoring settings
        "enable_metrics": True,
        "metrics_prefix": "ratelimit_metrics:",
        "track_operations": True,
        "track_timings": True,
        "slow_operation_threshold": 0.1,  # Log operations slower than 100ms
        # Memory optimization
        "compress_values": True,
        "value_compression_threshold": 1024,  # Compress values larger than 1KB
        "use_lua_scripts": True,  # Use Lua scripts for atomic operations
        "algorithm": "sliding_window",
    },
}

# Example 9: Redis with Geographic Distribution
GEOGRAPHIC_REDIS_CONFIG = {
    "RATELIMIT_BACKEND": "multi",
    "RATELIMIT_BACKENDS": {
        "redis_us_east": {
            "backend": "django_smart_ratelimit.backends.redis_backend.RedisBackend",
            "config": {
                "host": "redis-us-east.example.com",
                "port": 6379,
                "db": 0,
                "password": "us-east-password",
                "ssl": True,
                "key_prefix": "us_east:",
                "region": "us-east-1",
            },
        },
        "redis_eu_west": {
            "backend": "django_smart_ratelimit.backends.redis_backend.RedisBackend",
            "config": {
                "host": "redis-eu-west.example.com",
                "port": 6379,
                "db": 0,
                "password": "eu-west-password",
                "ssl": True,
                "key_prefix": "eu_west:",
                "region": "eu-west-1",
            },
        },
    },
    "RATELIMIT_MULTI_BACKEND": {
        "backends": ["redis_us_east", "redis_eu_west"],
        "strategy": "geographic_routing",  # Custom strategy
        "region_selection": lambda request: "us-east-1"
        if "US" in request.META.get("HTTP_CF_IPCOUNTRY", "")
        else "eu-west-1",
    },
}

# Example 10: Cloud Provider Specific Configurations

# AWS ElastiCache
AWS_ELASTICACHE_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "your-cluster.cache.amazonaws.com",
        "port": 6379,
        "db": 0,
        "ssl": True,
        "ssl_cert_reqs": None,  # AWS ElastiCache doesn't require client certs
        "connection_pool_kwargs": {
            "max_connections": 50,
            "retry_on_timeout": True,
        },
        "key_prefix": "aws_rl:",
        "algorithm": "sliding_window",
    },
}

# Google Cloud Memorystore
GCP_MEMORYSTORE_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "10.0.0.3",  # Private IP
        "port": 6379,
        "db": 0,
        "password": None,  # Memorystore can be configured without auth
        "connection_pool_kwargs": {
            "max_connections": 50,
            "socket_timeout": 5.0,
        },
        "key_prefix": "gcp_rl:",
        "algorithm": "sliding_window",
    },
}

# Azure Cache for Redis
AZURE_REDIS_CONFIG = {
    "RATELIMIT_BACKEND": "redis",
    "RATELIMIT_REDIS": {
        "host": "your-cache.redis.cache.windows.net",
        "port": 6380,  # Azure uses 6380 for SSL
        "db": 0,
        "password": "your-azure-redis-key",
        "ssl": True,
        "ssl_cert_reqs": "required",
        "connection_pool_kwargs": {
            "max_connections": 50,
            "retry_on_timeout": True,
        },
        "key_prefix": "azure_rl:",
        "algorithm": "sliding_window",
    },
}


if __name__ == "__main__":
    print("Redis Backend Examples")
    print("======================")
    print("")
    print("This file contains examples of Redis backend configurations:")
    print("1. Basic Redis setup")
    print("2. Production Redis with SSL")
    print("3. Redis Cluster configuration")
    print("4. Redis Sentinel (high availability)")
    print("5. Optimized connection pooling")
    print("6. Custom key patterns")
    print("7. Environment-specific configs")
    print("8. Performance monitoring")
    print("9. Geographic distribution")
    print("10. Cloud provider specific configs")
    print("")
    print("Redis is the recommended backend for high-performance")
    print("rate limiting in production environments.")
