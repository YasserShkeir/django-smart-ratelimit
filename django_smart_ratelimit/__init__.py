"""Django Smart Rate Limiting Library.

A flexible and efficient rate limiting library for Django applications
with support for multiple backends, algorithms (including token bucket),
and comprehensive rate limiting strategies.
"""

__version__ = "0.7.5"
__author__ = "Yasser Shkeir"

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

# Core functionality
from .decorator import rate_limit

# Common key functions
from .key_functions import (
    api_key_aware_key,
    composite_key,
    device_fingerprint_key,
    geographic_key,
    tenant_aware_key,
    time_aware_key,
    user_or_ip_key,
    user_role_key,
)
from .middleware import RateLimitMiddleware

# Utilities
from .utils import (
    add_rate_limit_headers,
    add_token_bucket_headers,
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
    load_function_from_string,
    parse_rate,
    should_skip_path,
    validate_rate_config,
)

__all__ = [
    "rate_limit",
    "RateLimitMiddleware",
    "TokenBucketAlgorithm",
    "RateLimitAlgorithm",
    "get_backend",
    "BaseBackend",
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
