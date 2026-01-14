"""Rate Limit Context module."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from django.http import HttpRequest


@dataclass
class RateLimitContext:
    """Context for a rate limit check."""

    # Request info
    request: HttpRequest

    # Rate limit parameters
    key: str = ""
    limit: int = 100
    period: int = 60
    algorithm: str = "sliding_window"

    # Result (filled after check)
    allowed: bool = True
    current_count: int = 0
    remaining: int = 0
    reset_time: float = 0.0

    # Metadata
    backend_name: str = ""
    check_duration: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def client_ip(self) -> str:
        """Get client IP from request."""
        return self.request.META.get("REMOTE_ADDR", "")

    @property
    def user_id(self) -> Optional[str]:
        """Get user ID if authenticated."""
        if hasattr(self.request, "user") and self.request.user.is_authenticated:
            return str(self.request.user.pk)
        return None

    def to_headers(self) -> Dict[str, str]:
        """Convert to rate limit response headers."""
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(int(self.reset_time)),
        }
