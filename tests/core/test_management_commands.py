"""Simplified tests for management commands."""


from django.test import TestCase

from django_smart_ratelimit.management.commands.cleanup_ratelimit import (
    Command as CleanupCommand,
)
from django_smart_ratelimit.management.commands.ratelimit_health import (
    Command as HealthCommand,
)


class CleanupRateLimitCommandSimpleTests(TestCase):
    """Simplified tests for cleanup_ratelimit command."""

    def test_command_exists(self):
        """Test that the command exists and can be instantiated."""
        command = CleanupCommand()
        self.assertIsInstance(command, CleanupCommand)

    def test_command_help_message(self):
        """Test that the command has a help message."""
        command = CleanupCommand()
        self.assertIn("Clean up", command.help)


class RateLimitHealthCommandSimpleTests(TestCase):
    """Simplified tests for ratelimit_health command."""

    def test_command_exists(self):
        """Test that the command exists and can be instantiated."""
        command = HealthCommand()
        self.assertIsInstance(command, HealthCommand)

    def test_command_help_message(self):
        """Test that the command has a help message."""
        command = HealthCommand()
        self.assertIn("health", command.help)
