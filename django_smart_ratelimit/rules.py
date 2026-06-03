"""Dynamic rate-limit rule evaluation engine.

Matches an incoming request against the active :class:`RateLimitRule` rows
(cached, with bounded staleness + signal-based invalidation) and returns the
highest-priority match, so rate limits can be created and changed at runtime via
the Django admin or the ORM without a redeploy.
"""

import re
import threading
import time
from typing import Any, List, Optional


class RuleEngine:
    """Evaluates and matches rate limit rules to requests, with caching."""

    def __init__(self, cache_timeout: Optional[int] = None) -> None:
        """Initialize the engine.

        Args:
            cache_timeout: Seconds to cache the active rule set. ``None`` reads
                ``RATELIMIT_RULE_CACHE_TIMEOUT`` (default 60) at call time.
        """
        self._cache_timeout = cache_timeout
        self._rules_cache: Optional[List] = None
        self._cache_expires = 0.0
        self._lock = threading.Lock()

    @property
    def cache_timeout(self) -> int:
        """Effective cache TTL (explicit override or the configured setting)."""
        if self._cache_timeout is not None:
            return self._cache_timeout
        try:
            from .config import get_settings

            return int(getattr(get_settings(), "rule_cache_timeout", 60))
        except Exception:  # pragma: no cover - settings not ready
            return 60

    def invalidate_cache(self) -> None:
        """Drop the cached rule set so the next request reloads it."""
        with self._lock:
            self._rules_cache = None
            self._cache_expires = 0.0

    def _get_cached_rules(self) -> List[Any]:
        now = time.monotonic()
        with self._lock:
            if self._rules_cache is not None and now < self._cache_expires:
                return self._rules_cache
        rules = self._load_rules()
        with self._lock:
            self._rules_cache = rules
            self._cache_expires = time.monotonic() + self.cache_timeout
        return rules

    def _load_rules(self) -> List[Any]:
        from .models import RateLimitRule

        # Ordered by (-priority, name) via the model Meta, so the first match is
        # the highest priority.
        return list(RateLimitRule.objects.filter(is_active=True))

    def get_rules_for_request(self, request: Any) -> List[Any]:
        """All active rules matching the request, highest priority first."""
        return [r for r in self._get_cached_rules() if self._matches(r, request)]

    def get_rule_for_request(self, request: Any) -> Optional[Any]:
        """The single highest-priority rule matching the request, or ``None``."""
        matches = self.get_rules_for_request(request)
        return matches[0] if matches else None

    @staticmethod
    def _matches(rule: Any, request: Any) -> bool:
        """True if ``rule`` applies to ``request`` (path regex + method)."""
        path = getattr(request, "path", "") or ""
        try:
            if not re.search(rule.path_pattern, path):
                return False
        except re.error:  # pragma: no cover - validated at save time
            return False
        methods = rule.methods()
        if "ALL" not in methods:
            if (getattr(request, "method", "") or "").upper() not in methods:
                return False
        return True


# Process-wide singleton used by the middleware integration.
rule_engine = RuleEngine()


def get_rule_engine() -> RuleEngine:
    """Return the process-wide RuleEngine singleton."""
    return rule_engine


def connect_signals() -> None:
    """Invalidate the rule cache whenever a rule is saved or deleted.

    Called from ``AppConfig.ready()`` so live edits (admin/ORM) take effect
    immediately rather than only after the cache TTL expires.
    """
    from django.db.models.signals import post_delete, post_save

    from .models import RateLimitRule

    def _invalidate(sender: object, **kwargs: object) -> None:
        rule_engine.invalidate_cache()

    post_save.connect(
        _invalidate, sender=RateLimitRule, dispatch_uid="dsr_rule_cache_save"
    )
    post_delete.connect(
        _invalidate, sender=RateLimitRule, dispatch_uid="dsr_rule_cache_delete"
    )
