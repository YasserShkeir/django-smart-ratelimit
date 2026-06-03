"""Django admin for managing dynamic rate-limit rules and monitoring counters."""

from typing import Any

from django.contrib import admin

from .models import RateLimitCounter, RateLimitRule


@admin.register(RateLimitRule)
class RateLimitRuleAdmin(admin.ModelAdmin):
    """Create and edit dynamic rate-limit rules at runtime.

    Changes take effect immediately (the rule cache is invalidated on save) when
    ``RATELIMIT_USE_DYNAMIC_RULES`` is enabled and ``RateLimitMiddleware`` is in
    ``MIDDLEWARE``.
    """

    list_display = [
        "name",
        "path_pattern",
        "method",
        "rate",
        "key",
        "algorithm",
        "is_active",
        "priority",
    ]
    list_filter = ["is_active", "algorithm", "key"]
    search_fields = ["name", "path_pattern", "description"]
    list_editable = ["is_active", "priority"]
    ordering = ["-priority", "name"]
    actions = ["enable_rules", "disable_rules"]

    fieldsets = [
        (
            "Basic Info",
            {"fields": ["name", "description", "is_active", "priority"]},
        ),
        (
            "Target",
            {
                "fields": ["path_pattern", "method"],
                "description": (
                    "path_pattern is a regular expression matched against the "
                    "request path (e.g. '^/api/'); method is 'ALL' or a "
                    "comma-separated list like 'GET,POST'."
                ),
            },
        ),
        (
            "Rate Limit",
            {
                "fields": ["rate", "key", "algorithm", "block"],
                "description": (
                    "rate is a string like '100/m' or '10/30s'. key is a key "
                    "function: 'ip', 'user', or 'header:X-API-Key'."
                ),
            },
        ),
    ]

    @admin.action(description="Enable selected rules")
    def enable_rules(self, request: Any, queryset: Any) -> None:
        """Bulk-activate rules (saved individually so the cache invalidates)."""
        updated = 0
        for rule in queryset:
            if not rule.is_active:
                rule.is_active = True
                rule.save()
                updated += 1
        self.message_user(request, f"Enabled {updated} rule(s).")

    @admin.action(description="Disable selected rules")
    def disable_rules(self, request: Any, queryset: Any) -> None:
        """Bulk-deactivate rules."""
        updated = 0
        for rule in queryset:
            if rule.is_active:
                rule.is_active = False
                rule.save()
                updated += 1
        self.message_user(request, f"Disabled {updated} rule(s).")


@admin.register(RateLimitCounter)
class RateLimitCounterAdmin(admin.ModelAdmin):
    """Read-only view of live fixed-window counters for monitoring."""

    list_display = ["key", "count", "window_start", "window_end"]
    list_filter = ["window_start"]
    search_fields = ["key"]
    readonly_fields = ["key", "count", "window_start", "window_end"]

    def has_add_permission(self, request: Any) -> bool:
        """Counters are created by the limiter, never by hand."""
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        """Counters are read-only."""
        return False
