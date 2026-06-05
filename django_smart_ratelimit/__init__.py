"""Django Smart Rate Limiting Library.

A flexible and efficient rate limiting library for Django applications
with support for multiple backends, algorithms (including token bucket),
and comprehensive rate limiting strategies.
"""

__version__ = "4.12.1"
__author__ = "Yasser Shkeir"

# Optional backend imports (may not be available)
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Union

# Adaptive Rate Limiting
from .adaptive import (
    AdaptiveRateLimiter,
    ConnectionCountIndicator,
    CPULoadIndicator,
    CustomLoadIndicator,
    LatencyLoadIndicator,
    LoadIndicator,
    LoadMetrics,
    MemoryLoadIndicator,
    TimeOfDayIndicator,
    create_adaptive_limiter,
    get_adaptive_limiter,
    register_adaptive_limiter,
    unregister_adaptive_limiter,
)

# Algorithms
from .algorithms import LeakyBucketAlgorithm, TokenBucketAlgorithm
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

# Core functionality
from .concurrency import concurrency_limit

# Configuration
from .configuration import RateLimitConfigManager
from .decorator import aratelimit, rate_limit

# Enums for type-safe configuration
from .enums import Algorithm, RateLimitKey


def ratelimit(
    key: Union[str, Callable],
    rate: Optional[Union[str, Callable[..., str]]] = None,
    block: bool = True,
    backend: Optional[str] = None,
    skip_if: Optional[Callable] = None,
    algorithm: Optional[str] = None,
    algorithm_config: Optional[Dict[str, Any]] = None,
    settings: Optional[Any] = None,
    adaptive: Optional[Union[str, "AdaptiveRateLimiter"]] = None,
    response_callback: Optional[Callable] = None,
    cost: Union[int, Callable[..., int]] = 1,
    shadow: bool = False,
    allow_list: Any = None,
    deny_list: Any = None,
) -> Callable:
    """Alias for rate_limit decorator.

    This is provided for compatibility with django-ratelimit naming convention.
    See rate_limit for full documentation.
    """
    return rate_limit(
        key=key,
        rate=rate,
        block=block,
        backend=backend,
        skip_if=skip_if,
        algorithm=algorithm,
        algorithm_config=algorithm_config,
        settings=settings,
        adaptive=adaptive,
        response_callback=response_callback,
        cost=cost,
        shadow=shadow,
        allow_list=allow_list,
        deny_list=deny_list,
    )


# Advanced feature modules (roadmap Phase 2-5). These are safe to import at
# package load (they import Django models lazily, inside functions), so they can
# be re-exported here for discoverability/autocomplete. The Django *model*
# classes are NOT re-exported — import those from django_smart_ratelimit.models
# (importing them here would touch the app registry before it is ready).
from .analytics import (
    find_alertable_offenders,
    get_offender_detail,
    get_rule_hit_counts,
    get_top_offenders,
    get_traffic_summary,
    offenders_csv,
    send_offender_alerts,
)
from .api_keys import (
    api_key_key,
    extract_api_key,
    get_api_key_record,
    get_api_key_tier,
)

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
from .geo import (
    GeoLocation,
    GeoProvider,
    MaxMindProvider,
    NullGeoProvider,
    geo_key,
    get_country,
    get_geo_provider,
    get_rate_for_country,
    set_geo_provider,
)
from .graphql import (
    GrapheneRateLimitMiddleware,
    GraphQLRateLimitExceeded,
    estimate_query_complexity,
    make_strawberry_extension,
)
from .groups import get_tier_from_groups, group_key

# Common key functions
from .key_functions import api_key_aware_key, composite_key, geographic_key
from .key_functions import get_device_fingerprint_key as device_fingerprint_key
from .key_functions import get_tenant_key as tenant_aware_key
from .key_functions import time_aware_key, user_or_ip_key, user_role_key
from .middleware import RateLimitMiddleware

# Performance utilities
from .performance import RateLimitCache

# v3 pipeline — shared rate-limit evaluation primitives. Exported so advanced
# users can compose their own middleware/throttle adapters on top of the
# same logic the built-in decorator uses.
from .pipeline import (
    POLICY_ALLOW,
    POLICY_CONTINUE,
    POLICY_DENY,
    ResolvedLimit,
    ShadowDecision,
    apply_policy_lists,
    handle_shadow_decision,
    resolve_effective_rate,
)
from .quota import consume_quota, get_quota_usage, quota, reset_quota
from .rules import RuleEngine, get_rule_engine, rule_engine
from .statsd import StatsDClient, StatsDMetrics, get_statsd_metrics
from .tenants import (
    extract_tenant,
    get_tenant_quota,
    resolve_tenant_rate,
    tenant_key,
)
from .tiers import (
    apply_tier_to_rate,
    create_user_override,
    get_user_override,
    get_user_tier,
    resolve_effective_user_rate,
    tier_key,
    tiered,
)

# Utilities
from .utils import is_ratelimited  # noqa: F401
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
RedisClusterBackend: Optional[type] = None
MongoDBBackend: Optional[type] = None

try:
    from .backends.redis_backend import RedisBackend, RedisClusterBackend
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
    "ratelimit",  # Alias for rate_limit
    "aratelimit",  # Async decorator
    "concurrency_limit",
    "quota",
    "consume_quota",
    "get_quota_usage",
    "reset_quota",
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
    # Adaptive Rate Limiting
    "AdaptiveRateLimiter",
    "LoadIndicator",
    "LoadMetrics",
    "CPULoadIndicator",
    "MemoryLoadIndicator",
    "LatencyLoadIndicator",
    "ConnectionCountIndicator",
    "CustomLoadIndicator",
    "TimeOfDayIndicator",
    "create_adaptive_limiter",
    "get_adaptive_limiter",
    "register_adaptive_limiter",
    "unregister_adaptive_limiter",
    # Algorithms
    "TokenBucketAlgorithm",
    "LeakyBucketAlgorithm",
    "RateLimitAlgorithm",
    # Backends
    "get_backend",
    "BaseBackend",
    "BackendFactory",
    "BackendHealthChecker",
    "MemoryBackend",
    "MultiBackend",
    "RedisBackend",
    "RedisClusterBackend",
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
    # v3 Pipeline (shared evaluation primitives)
    "POLICY_ALLOW",
    "POLICY_CONTINUE",
    "POLICY_DENY",
    "ResolvedLimit",
    "ShadowDecision",
    "apply_policy_lists",
    "handle_shadow_decision",
    "resolve_effective_rate",
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
    # Enums
    "Algorithm",
    "RateLimitKey",
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
    # Dynamic rules (Phase 2)
    "RuleEngine",
    "rule_engine",
    "get_rule_engine",
    # User tiers / groups / overrides / API keys (Phase 3)
    "get_user_tier",
    "apply_tier_to_rate",
    "get_user_override",
    "resolve_effective_user_rate",
    "tier_key",
    "tiered",
    "create_user_override",
    "get_tier_from_groups",
    "group_key",
    "extract_api_key",
    "get_api_key_record",
    "api_key_key",
    "get_api_key_tier",
    # Analytics (Phase 4)
    "get_traffic_summary",
    "get_top_offenders",
    "get_rule_hit_counts",
    "offenders_csv",
    "get_offender_detail",
    "find_alertable_offenders",
    "send_offender_alerts",
    # Geographic (Phase 5.4)
    "geo_key",
    "get_country",
    "get_rate_for_country",
    "GeoProvider",
    "MaxMindProvider",
    "NullGeoProvider",
    "GeoLocation",
    "get_geo_provider",
    "set_geo_provider",
    # Multi-tenant (Phase 5.5)
    "extract_tenant",
    "tenant_key",
    "get_tenant_quota",
    "resolve_tenant_rate",
    # GraphQL (Phase 5.6)
    "GrapheneRateLimitMiddleware",
    "make_strawberry_extension",
    "estimate_query_complexity",
    "GraphQLRateLimitExceeded",
    # StatsD exporter (Phase 5.1)
    "StatsDClient",
    "StatsDMetrics",
    "get_statsd_metrics",
]
