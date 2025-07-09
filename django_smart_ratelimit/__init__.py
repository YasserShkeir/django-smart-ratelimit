"""Django Smart Rate Limiting Library.

A flexible and efficient rate limiting library for Django applications
with support for multiple backends and sliding window algorithms.
"""

__version__ = "0.5.0"
__author__ = "Yasser Shkeir"

from .decorator import rate_limit
from .middleware import RateLimitMiddleware

__all__ = ["rate_limit", "RateLimitMiddleware"]
