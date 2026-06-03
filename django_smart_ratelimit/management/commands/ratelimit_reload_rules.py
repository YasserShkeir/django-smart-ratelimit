"""Management command: reload the dynamic rate-limit rule cache.

Invalidating the cache forces the next request to reload rules from the database.
The cache is normally invalidated automatically on rule save/delete and expires
after ``RATELIMIT_RULE_CACHE_TIMEOUT`` seconds; this command is for forcing a
reload manually (e.g. after a bulk DB import that bypassed model signals).
"""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Invalidate the dynamic rate-limit rule cache."""

    help = "Reload (invalidate the cache of) dynamic rate-limit rules."

    def handle(self, *args: Any, **options: Any) -> None:
        """Invalidate the rule cache and report the active rule count."""
        from django_smart_ratelimit.models import RateLimitRule
        from django_smart_ratelimit.rules import rule_engine

        rule_engine.invalidate_cache()
        active = RateLimitRule.objects.filter(is_active=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Rate-limit rule cache reloaded ({active} active rule(s))."
            )
        )
