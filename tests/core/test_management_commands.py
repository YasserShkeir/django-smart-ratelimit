"""Expanded tests for management commands."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings


class CleanupRateLimitCommandTests(TestCase):
    """Tests for cleanup_ratelimit command behavior."""

    @override_settings(INSTALLED_APPS=["django_smart_ratelimit"])
    def test_command_help_shows(self):
        buf = StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            with self.assertRaises(SystemExit) as cm:
                # argparse prints help then exits with code 0
                call_command("cleanup_ratelimit", "--help")
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("usage", buf.getvalue().lower())

    @override_settings(INSTALLED_APPS=["django_smart_ratelimit"])
    def test_dry_run_executes(self):
        out = StringIO()
        call_command("cleanup_ratelimit", "--dry-run", stdout=out)
        self.assertIn("DRY RUN", out.getvalue())

    @override_settings(INSTALLED_APPS=["django_smart_ratelimit"])
    def test_with_arguments(self):
        out = StringIO()
        call_command(
            "cleanup_ratelimit",
            "--older-than",
            "1",
            "--batch-size",
            "5",
            stdout=out,
        )
        # No exception means basic parsing works
        self.assertTrue(out.getvalue())


class RateLimitHealthCommandTests(TestCase):
    """Tests for ratelimit_health command behavior."""

    @override_settings(INSTALLED_APPS=["django_smart_ratelimit"])
    def test_health_command_runs(self):
        out = StringIO()
        call_command("ratelimit_health", stdout=out)
        # Expect some output
        self.assertTrue(out.getvalue())
