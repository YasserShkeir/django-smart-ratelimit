"""Django Smart Rate Limiting Library.

A flexible and efficient rate limiting library for Django applications
with support for multiple backends, algorithms (including token bucket),
and comprehensive rate limiting strategies.
"""

__version__ = "1.0.0"
__author__ = "Yasser Shkeir"

# Optional backend imports (may not be available)
from typing import TYPE_CHECKING, Optional

# Algorithms
from .algorithms import TokenBucketAlgorithm
from .algorithms.base import RateLimitAlgorithm

# Authentication utilities
from .auth_utils import (
    extract_user_identifier,
    get_client_info,
    get_user_info,
    get_user_role,
    has_permission,
    is_authenticated_user,
    is_internal_request,
    is_staff_user,
    is_superuser,
    should_bypass_rate_limit,
)

# Backends
from .backends import get_backend
from .backends.base import BaseBackend
from .backends.factory import BackendFactory
from .backends.memory import MemoryBackend
from .backends.multi import BackendHealthChecker, MultiBackend

# Circuit Breaker
from .circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerState,
    circuit_breaker,
    circuit_breaker_registry,
)

# Configuration
from .configuration import RateLimitConfigManager

# Core functionality
from .decorator import rate_limit

# Exceptions
from .exceptions import (
    BackendConnectionError,
    BackendError,
    BackendTimeoutError,
    CircuitBreakerError,
    CircuitBreakerOpen,
    ConfigurationError,
    KeyGenerationError,
    RateLimitExceeded,
    RateLimitException,
)

# Common key functions
from .key_functions import api_key_aware_key, composite_key, geographic_key
from .key_functions import get_device_fingerprint_key as device_fingerprint_key
from .key_functions import get_tenant_key as tenant_aware_key
from .key_functions import time_aware_key, user_or_ip_key, user_role_key
from .middleware import RateLimitMiddleware

# Performance utilities
from .performance import RateLimitCache

# Utilities
from .utils import (
    add_rate_limit_headers,
    add_token_bucket_headers,
    debug_ratelimit_status,
    format_debug_info,
    format_rate_headers,
    generate_key,
    get_api_key_key,
    get_client_identifier,
    get_device_fingerprint_key,
    get_ip_key,
    get_jwt_key,
    get_rate_for_path,
    get_tenant_key,
    get_user_key,
    is_exempt_request,
    is_ratelimited,
    load_function_from_string,
    parse_rate,
    should_skip_path,
    validate_rate_config,
)

if TYPE_CHECKING:
    from .backends.mongodb import MongoDBBackend as MongoDBBackendType
    from .backends.redis_backend import RedisBackend as RedisBackendType
else:
    RedisBackendType = None
    MongoDBBackendType = None

RedisBackend: Optional[type] = None
MongoDBBackend: Optional[type] = None

try:
    from .backends.redis_backend import RedisBackend
except ImportError:
    pass

try:
    from .backends.mongodb import MongoDBBackend
except ImportError:
    pass

# and django_smart_ratelimit.models respectively

# Models (conditional import to avoid Django app loading issues)
# These will be set by _import_django_components() when needed

# Logging format constants
RATELIMIT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Log level constants
LOG_LEVEL_DEBUG = "DEBUG"
LOG_LEVEL_INFO = "INFO"
LOG_LEVEL_WARNING = "WARNING"
LOG_LEVEL_ERROR = "ERROR"


__all__ = [
    # Core functionality
    "rate_limit",
    "RateLimitMiddleware",
    # Logging
    "RATELIMIT_LOG_FORMAT",
    "LOG_LEVEL_DEBUG",
    "LOG_LEVEL_INFO",
    "LOG_LEVEL_WARNING",
    "LOG_LEVEL_ERROR",
    # Exceptions
    "RateLimitException",
    "RateLimitExceeded",
    "BackendError",
    "BackendConnectionError",
    "BackendTimeoutError",
    "ConfigurationError",
    "CircuitBreakerError",
    "CircuitBreakerOpen",
    "KeyGenerationError",
    # Algorithms
    "TokenBucketAlgorithm",
    "RateLimitAlgorithm",
    # Backends
    "get_backend",
    "BaseBackend",
    "BackendFactory",
    "BackendHealthChecker",
    "MemoryBackend",
    "MultiBackend",
    "RedisBackend",
    "MongoDBBackend",
    # Circuit Breaker
    "CircuitBreakerConfig",
    "CircuitBreakerError",
    "CircuitBreakerState",
    "circuit_breaker",
    "circuit_breaker_registry",
    # Configuration
    "RateLimitConfigManager",
    # Performance
    "RateLimitCache",
    # Utility functions
    "get_ip_key",
    "get_user_key",
    "parse_rate",
    "validate_rate_config",
    "generate_key",
    "get_client_identifier",
    "format_rate_headers",
    "is_exempt_request",
    "add_rate_limit_headers",
    "add_token_bucket_headers",
    "debug_ratelimit_status",
    "format_debug_info",
    "get_jwt_key",
    "get_api_key_key",
    "get_tenant_key",
    "get_device_fingerprint_key",
    "load_function_from_string",
    "should_skip_path",
    "get_rate_for_path",
    # Common key functions
    "api_key_aware_key",
    "composite_key",
    "device_fingerprint_key",
    "geographic_key",
    "tenant_aware_key",
    "time_aware_key",
    "user_or_ip_key",
    "user_role_key",
    # Authentication utilities
    "extract_user_identifier",
    "get_client_info",
    "get_user_info",
    "get_user_role",
    "has_permission",
    "is_authenticated_user",
    "is_internal_request",
    "is_staff_user",
    "is_superuser",
    "should_bypass_rate_limit",
]
