"""Django app configuration for Django Smart Ratelimit."""

from django.apps import AppConfig


class DjangoSmartRatelimitConfig(AppConfig):
    """Configuration for Django Smart Ratelimit app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_smart_ratelimit"
    verbose_name = "Django Smart Ratelimit"

    def ready(self) -> None:
        """Initialize the app when Django starts."""
        # Import signal handlers if needed
        pass
