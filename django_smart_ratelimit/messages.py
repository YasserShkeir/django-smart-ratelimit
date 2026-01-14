"""
Standardized messages for Django Smart Ratelimit.

This module contains constant strings for error messages and log messages
to ensure consistency across the library.
"""

# Error messages (User facing)
ERROR_RATE_LIMIT_EXCEEDED = "Rate limit exceeded. Please try again later."
ERROR_BACKEND_UNAVAILABLE = "Rate limiting service temporarily unavailable."
ERROR_CONFIGURATION_INVALID = "Invalid rate limit configuration: {details}"
ERROR_KEY_GENERATION_FAILED = "Failed to generate rate limit key: {details}"

# Log messages (Internal)
LOG_BACKEND_ERROR = "Backend {backend} error for key {key}: {error}"
LOG_CIRCUIT_OPEN = "Circuit breaker open for backend {backend}"
LOG_FAILOVER = "Failing over from {primary} to {secondary}"
LOG_BACKEND_INIT_FAILED = "Failed to initialize backend {backend}: {error}"
LOG_BACKEND_OPERATION_FAILED = "Backend {backend} operation {operation} failed: {error}"
