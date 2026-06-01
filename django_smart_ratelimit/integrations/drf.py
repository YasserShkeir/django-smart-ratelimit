"""
Django REST Framework throttle adapter for django-smart-ratelimit.

This module provides BaseThrottle subclasses that integrate django-smart-ratelimit
with DRF's throttling system, allowing you to use smart rate limiting algorithms
and backends within standard DRF throttle_classes configuration.

Example:
    In your DRF view:

        from rest_framework.views import APIView
        from django_smart_ratelimit.integrations.drf import UserRateLimitThrottle

        class MyAPIView(APIView):
            throttle_classes = [UserRateLimitThrottle]

            def get(self, request):
                return Response({"message": "ok"})

    In settings.py:

        REST_FRAMEWORK = {
            "DEFAULT_THROTTLE_CLASSES": [
                "django_smart_ratelimit.integrations.drf.UserRateLimitThrottle",
                "django_smart_ratelimit.integrations.drf.AnonRateLimitThrottle",
            ],
            "DEFAULT_THROTTLE_RATES": {
                "user": "1000/hour",
                "anon": "100/hour",
            },
        }
"""

import inspect
import logging
import time
from typing import Any, Dict, Optional, Tuple

from django.http import HttpRequest

from django_smart_ratelimit.backends import get_backend

logger = logging.getLogger(__name__)

# Cache of whether a given backend type's ``incr`` accepts a cost/amount
# argument. Keyed by backend class so the (cheap but non-trivial) signature
# inspection runs once per backend type rather than on every request.
_INCR_COST_SUPPORT_CACHE: Dict[type, bool] = {}


def _backend_incr_supports_cost(backend: Any) -> bool:
    """
    Determine whether ``backend.incr`` accepts a positional cost argument.

    The decision is based on inspecting the method signature (cached per
    backend type) rather than catching ``TypeError`` from the call itself.
    Relying on ``TypeError`` is fragile: a ``TypeError`` raised from *inside*
    the backend would be misclassified as "no cost support".

    A backend is considered to support cost if its ``incr`` accepts more than
    the two required parameters (``key``, ``period``) -- e.g. a third
    positional parameter or ``*args`` -- so additional tokens can be consumed
    in a single call.

    Args:
        backend: The backend instance whose ``incr`` is being inspected.

    Returns:
        True if a cost argument can be passed to ``backend.incr``.
    """
    backend_type = type(backend)
    cached = _INCR_COST_SUPPORT_CACHE.get(backend_type)
    if cached is not None:
        return cached

    supports_cost = False
    try:
        signature = inspect.signature(backend.incr)
        params = list(signature.parameters.values())
        # ``backend.incr`` is bound, so ``self`` is already excluded. The base
        # contract is incr(key, period); anything that can bind a third
        # positional argument supports cost.
        positional = [
            p
            for p in params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        has_var_positional = any(
            p.kind == inspect.Parameter.VAR_POSITIONAL for p in params
        )
        supports_cost = len(positional) > 2 or has_var_positional
    except (TypeError, ValueError):
        # Builtins / C-implemented callables may not expose a signature.
        # Be conservative and fall back to single-token increments.
        supports_cost = False

    _INCR_COST_SUPPORT_CACHE[backend_type] = supports_cost
    return supports_cost


# Graceful DRF import with helpful error
try:
    from rest_framework.throttling import BaseThrottle
except ImportError:
    BaseThrottle = None

# Base class used for the throttle hierarchy. When DRF is installed this is the
# real ``BaseThrottle``; otherwise it falls back to ``object`` so the module can
# still be imported. Attempting to *instantiate* a throttle without DRF raises a
# helpful ImportError from ``__init__`` (subclassing ``None`` directly would
# crash at import time before that helpful error could ever be shown).
_ThrottleBase: Any = BaseThrottle if BaseThrottle is not None else object


class SmartRateLimitThrottle(_ThrottleBase):
    """
    BaseThrottle adapter for django-smart-ratelimit.

    This class bridges DRF's throttling interface with django-smart-ratelimit's
    flexible rate limiting backends and algorithms.

    Attributes:
        scope: DRF-style throttle scope (e.g., 'user', 'anon'). Used to look up
               rate from DRF's THROTTLE_RATES setting.
        rate: Optional rate override (format: "10/m", "100/hour"). If not set,
              uses THROTTLE_RATES[scope]. Supports callable for dynamic rates.
        algorithm: Rate limiting algorithm: 'sliding_window' (default), 'fixed_window',
                  or 'token_bucket'.
        cost: Weight of each request (default: 1). Can be overridden by
              get_cost(request, view) method.
        key_func: Optional callable that returns a cache key from (request, view).
                 If not set, defaults to get_cache_key().

    Example:
        class MyThrottle(SmartRateLimitThrottle):
            scope = "my_scope"
            rate = "50/hour"
            algorithm = "sliding_window"

            def get_cache_key(self, request, view):
                if request.user.is_authenticated:
                    return f"user:{request.user.id}"
                return self.get_ident(request)
    """

    def __init__(self) -> None:
        """Initialize throttle, raising helpful error if DRF not installed."""
        if BaseThrottle is None:
            raise ImportError(
                "django-rest-framework is required for SmartRateLimitThrottle. "
                "Install it with: pip install djangorestframework"
            )
        super().__init__()

        # Check attributes exist
        if not hasattr(self, "scope"):
            self.scope: Optional[str] = None

        self.algorithm = getattr(self, "algorithm", "sliding_window")
        self.cost = getattr(self, "cost", 1)
        self.key_func = getattr(self, "key_func", None)

        # Optional parity with the @rate_limit decorator (v4): CIDR allow/deny
        # policy lists and shadow mode. Set these as class attributes on a
        # throttle subclass to enable them. Parse ONCE here (not per request) so
        # a URL/file-backed feed is not re-fetched on every request and a
        # malformed inline CIDR raises at construction rather than silently
        # failing open on each request.
        from ..policy import parse_ip_list

        self.allow_list = parse_ip_list(getattr(self, "allow_list", None))
        self.deny_list = parse_ip_list(getattr(self, "deny_list", None))
        self.shadow = bool(getattr(self, "shadow", False))

        # Rate will be resolved in allow_request from either:
        # 1. self.rate attribute
        # 2. DRF settings THROTTLE_RATES[scope]
        self.rate = getattr(self, "rate", None)

        # Cache for reset time
        self._last_reset_time: Optional[int] = None

    def get_cache_key(self, request: HttpRequest, view: Any) -> Optional[str]:
        """
        Generate the cache key for rate limiting.

        Default implementation: user ID if authenticated, else IP address.
        Override to customize key generation.

        Args:
            request: DRF request object
            view: The view being throttled

        Returns:
            Cache key string, or None to skip throttling
        """
        from django_smart_ratelimit.key_functions import get_ip_key

        if hasattr(request, "user") and request.user.is_authenticated:
            user_id = getattr(request.user, "id", None)
            if user_id:
                return f"user:{user_id}"

        return get_ip_key(request)

    def _parse_rate(self, rate: Optional[str]) -> Tuple[int, int]:
        """
        Parse rate string into (limit, period_seconds).

        Args:
            rate: Rate string (e.g., "10/m", "100/hour")

        Returns:
            Tuple of (limit, period_in_seconds)

        Raises:
            ValueError: If rate format is invalid
        """
        from django_smart_ratelimit.backends.utils import parse_rate

        if not rate:
            raise ValueError("Rate must be specified")
        return parse_rate(rate)

    def _get_rate(self, request: HttpRequest, view: Any) -> str:
        """
        Resolve the rate limit string for this request.

        Priority:
        1. self.rate attribute (if not None)
        2. DRF's REST_FRAMEWORK['THROTTLE_RATES'][scope]

        Args:
            request: DRF request
            view: The view being throttled

        Returns:
            Rate string (e.g., "100/hour")

        Raises:
            ValueError: If no rate can be resolved
        """
        # Support callable rate. Use type(self) to bypass method binding so
        # a plain function attribute receives (throttle, request) rather than
        # an extra bound self argument.
        rate = getattr(type(self), "rate", self.rate)
        if callable(rate):
            rate = rate(self, request)

        if rate:
            return rate

        # Fall back to DRF settings
        if self.scope:
            from django.conf import settings

            throttle_rates = getattr(settings, "REST_FRAMEWORK", {}).get(
                "DEFAULT_THROTTLE_RATES", {}
            )

            if self.scope in throttle_rates:
                return throttle_rates[self.scope]

        raise ValueError(
            f"No rate configured for scope '{self.scope}'. "
            "Set 'rate' attribute or add to REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']."
        )

    def get_cost(self, request: HttpRequest, view: Any) -> int:
        """
        Get the cost (weight) of this request.

        Override to implement weighted rate limiting (e.g., expensive operations
        cost more tokens).

        Args:
            request: DRF request
            view: The view being throttled

        Returns:
            Cost in tokens (default: 1)
        """
        # Support callable cost attribute. Access via the class to avoid
        # method binding when users assign a plain function.
        cost = getattr(type(self), "cost", self.cost)
        if callable(cost):
            return cost(request, view)
        return cost

    def allow_request(self, request: HttpRequest, view: Any) -> bool:
        """
        Check if request should be allowed (implements DRF throttle interface).

        Args:
            request: DRF request object
            view: The view being throttled

        Returns:
            True if request is allowed, False to trigger throttle response
        """
        # Get cache key. Access key_func via class to avoid method binding
        # when the user assigns a plain function as a class attribute.
        key_func = getattr(type(self), "key_func", None) or self.key_func
        if key_func and callable(key_func):
            key = key_func(request, view)
        else:
            key = self.get_cache_key(request, view)

        if not key:
            return True  # No key = skip throttling

        # CIDR allow/deny policy lists + shadow mode (parity with @rate_limit).
        from django_smart_ratelimit.pipeline import (
            POLICY_ALLOW,
            POLICY_DENY,
            apply_policy_lists,
            handle_shadow_decision,
        )

        if self.allow_list is not None or self.deny_list is not None:
            policy = apply_policy_lists(
                request, allow_list=self.allow_list, deny_list=self.deny_list
            )
            if policy == POLICY_ALLOW:
                return True
            if policy == POLICY_DENY:
                if self.shadow:
                    handle_shadow_decision(
                        allowed=False,
                        shadow=True,
                        request=request,
                        key="deny_list",
                        limit=0,
                        remaining=0,
                        algorithm=self.algorithm,
                        backend="policy",
                        cost=0,
                    )
                    return True
                return False

        # Get rate
        try:
            rate_str = self._get_rate(request, view)
            limit, period = self._parse_rate(rate_str)
        except Exception as e:
            logger.warning(f"Failed to parse rate: {e}. Allowing request.")
            return True

        # Get backend and check rate limit
        backend = get_backend()

        try:
            cost = self.get_cost(request, view)

            # Honor the throttle's declared ``algorithm``. The bucket algorithms
            # have distinct (burst) semantics, so they must dispatch to the same
            # TokenBucket/LeakyBucket logic the @rate_limit decorator uses rather
            # than to the backend's plain window counter. Window algorithms keep
            # the counter path (the backend's configured window type).
            if self.algorithm == "token_bucket":
                from ..algorithms import TokenBucketAlgorithm

                tb = TokenBucketAlgorithm(getattr(self, "algorithm_config", None))
                try:
                    allowed, metadata = tb.is_allowed(
                        backend, key, limit, period, tokens_requested=cost
                    )
                except TypeError:
                    allowed, metadata = tb.is_allowed(backend, key, limit, period)
                remaining = int(metadata.get("tokens_remaining", 0)) if metadata else 0
            elif self.algorithm == "leaky_bucket":
                from ..algorithms import LeakyBucketAlgorithm

                lb = LeakyBucketAlgorithm(getattr(self, "algorithm_config", None))
                try:
                    allowed, metadata = lb.is_allowed(
                        backend, key, limit, period, request_cost=cost
                    )
                except TypeError:
                    allowed, metadata = lb.is_allowed(backend, key, limit, period)
                remaining = int(metadata.get("space_remaining", 0)) if metadata else 0
            else:
                # sliding_window / fixed_window: counter via the backend.
                # Prefer backends that accept a cost argument (v3 contract).
                # Whether cost is supported is decided by inspecting the backend's
                # ``incr`` signature (cached per backend type) -- NOT by catching
                # TypeError from the call, which would misclassify a TypeError
                # raised from inside the backend as "no cost support". Older
                # backends fall back to a loop of single-token increments so
                # weighted throttling still works end-to-end.
                if _backend_incr_supports_cost(backend):
                    count = backend.incr(key, period, cost)  # type: ignore[call-arg]
                else:
                    count = backend.incr(key, period)
                    for _ in range(max(0, cost - 1)):
                        count = backend.incr(key, period)

                # ``count`` is the post-incr value; the request is allowed iff the
                # count BEFORE this request (count - cost) was below the limit.
                # Using ``< limit`` (not ``<= limit``) because a count equal to
                # limit means this request pushed us to the boundary — it should
                # be the last allowed one.
                allowed = (count - cost) < limit
                remaining = max(0, limit - count)

            # Shadow mode: a would-be block is downgraded to an allow + log line
            # so a new throttle can be validated in production before enforcing.
            if self.shadow:
                decision = handle_shadow_decision(
                    allowed=allowed,
                    shadow=True,
                    request=request,
                    key=key,
                    limit=limit,
                    remaining=remaining,
                    algorithm=self.algorithm,
                    backend=type(backend).__name__,
                    cost=cost,
                )
                allowed = decision.allow

            # Always store reset time for wait() method — both success & denial
            # paths may need Retry-After information.
            reset_time = None
            try:
                reset_time = backend.get_reset_time(key)
            except Exception:
                reset_time = None
            if reset_time:
                self._last_reset_time = reset_time
            else:
                self._last_reset_time = int(time.time() + period)

            return allowed

        except Exception as e:
            # If backend fails and fail_open is True, allow request.
            # Catch broadly because third-party backends raise varied types.
            fail_open = getattr(backend, "fail_open", True)
            if fail_open:
                logger.warning(f"Backend error, allowing request: {e}")
                return True
            logger.error(f"Backend error: {e}")
            return False

    def throttle_success(self) -> bool:
        """
        Called when request is allowed. Required by BaseThrottle interface.

        Returns:
            Always True
        """
        return True

    def throttle_failure(self) -> bool:
        """
        Called when request is throttled. Required by BaseThrottle interface.

        Returns:
            Always False
        """
        return False

    def wait(self) -> Optional[float]:
        """
        Return seconds until the throttle is reset (for Retry-After header).

        Required by BaseThrottle interface.

        Returns:
            Seconds to wait, or None
        """
        if self._last_reset_time is None:
            return None

        now = int(time.time())
        seconds_to_wait = max(0, self._last_reset_time - now)

        return float(seconds_to_wait) if seconds_to_wait > 0 else None


class UserRateLimitThrottle(SmartRateLimitThrottle):
    """
    Rate limit by authenticated user.

    Scope: 'user'
    Key: user.id if authenticated, else IP

    Usage in settings.py:
        REST_FRAMEWORK = {
            'DEFAULT_THROTTLE_CLASSES': [
                'django_smart_ratelimit.integrations.drf.UserRateLimitThrottle',
            ],
            'DEFAULT_THROTTLE_RATES': {
                'user': '1000/hour',
            },
        }
    """

    scope = "user"

    def get_cache_key(self, request: HttpRequest, view: Any) -> Optional[str]:
        """Return user ID if authenticated, else IP address."""
        from django_smart_ratelimit.key_functions import get_ip_key

        if hasattr(request, "user") and request.user.is_authenticated:
            user_id = getattr(request.user, "id", None)
            if user_id:
                return f"user:{user_id}"

        return get_ip_key(request)


class AnonRateLimitThrottle(SmartRateLimitThrottle):
    """
    Rate limit anonymous users by IP address.

    Scope: 'anon'
    Key: IP address

    Usage in settings.py:
        REST_FRAMEWORK = {
            'DEFAULT_THROTTLE_CLASSES': [
                'django_smart_ratelimit.integrations.drf.AnonRateLimitThrottle',
            ],
            'DEFAULT_THROTTLE_RATES': {
                'anon': '100/hour',
            },
        }
    """

    scope = "anon"

    def get_cache_key(self, request: HttpRequest, view: Any) -> Optional[str]:
        """Return IP address."""
        from django_smart_ratelimit.key_functions import get_ip_key

        return get_ip_key(request)


class ScopedRateLimitThrottle(SmartRateLimitThrottle):
    """
    Rate limit based on view's throttle_scope attribute.

    This class allows per-view rate limit configuration without subclassing.
    Each view can set its own throttle_scope, and the rate is looked up from
    REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'].

    Usage:
        class MyView(APIView):
            throttle_classes = [ScopedRateLimitThrottle]
            throttle_scope = 'my_api'

            def get(self, request):
                return Response({"message": "ok"})

        In settings.py:
            REST_FRAMEWORK = {
                'DEFAULT_THROTTLE_RATES': {
                    'my_api': '500/hour',
                },
            }
    """

    def __init__(self) -> None:
        """Initialize without a fixed scope."""
        super().__init__()
        self.scope = None  # Will be set from view's throttle_scope

    def allow_request(self, request: HttpRequest, view: Any) -> bool:
        """
        Override to set scope from view's throttle_scope attribute.

        Args:
            request: DRF request
            view: The view being throttled

        Returns:
            True if allowed, False to throttle
        """
        # Resolve scope from view's throttle_scope attribute
        if hasattr(view, "throttle_scope"):
            self.scope = view.throttle_scope
        else:
            logger.warning(
                f"View {view.__class__.__name__} has no 'throttle_scope' attribute. "
                "Set 'throttle_scope' on the view."
            )
            return True

        # Call parent implementation
        return super().allow_request(request, view)
