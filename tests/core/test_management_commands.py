"""Expanded tests for management commands."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings


class RateLimitHealthCommandTests(TestCase):
    """Tests for ratelimit_health command behavior."""

    @override_settings(INSTALLED_APPS=["django_smart_ratelimit"])
    def test_health_command_runs(self):
        """Test that the health command runs and produces output."""
        out = StringIO()
        call_command("ratelimit_health", stdout=out)
        # Expect some output
        self.assertTrue(out.getvalue())
