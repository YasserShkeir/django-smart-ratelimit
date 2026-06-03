"""Django app configuration for Django Smart Ratelimit."""

from typing import Any

from django.apps import AppConfig


class DjangoSmartRatelimitConfig(AppConfig):
    """Configuration for Django Smart Ratelimit app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_smart_ratelimit"
    verbose_name = "Django Smart Ratelimit"

    def ready(self) -> None:
        """Initialize the app when Django starts."""
        from django.core.signals import setting_changed

        from django_smart_ratelimit.config import reset_settings

        def reload_settings(sender: Any, setting: str, **kwargs: Any) -> None:
            if setting.startswith("RATELIMIT_"):
                # print(f"Resetting settings due to change in {setting}")
                reset_settings()

        setting_changed.connect(reload_settings)

        # Wire dynamic-rule cache invalidation (Phase 2). Guarded so the app can
        # still load if models aren't ready in some startup paths.
        try:
            from django_smart_ratelimit.rules import connect_signals

            connect_signals()
        except Exception:  # pragma: no cover - defensive app startup
            pass
