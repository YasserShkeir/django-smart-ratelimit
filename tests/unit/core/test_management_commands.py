"""Expanded tests for management commands."""

import json
from io import StringIO
from unittest import mock

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

    def test_health_reports_unhealthy_when_store_unreachable_with_fail_open(self):
        """Unreachable store must report unhealthy even when fail_open is True.

        get_count() honors fail_open and masks store errors by returning a
        default value, so the health check must rely on health_check() which
        probes connectivity directly and does not fail open.
        """

        class _FailOpenBackend:
            """Backend that fails open.

            get_count masks errors while health_check reports the real
            connectivity failure.
            """

            fail_open = True

            def get_count(self, key, period=60):
                # Simulates a fail-open default: the underlying store raised,
                # but the error was masked and a default value is returned.
                return 0

            def health_check(self):
                return {"status": "unhealthy", "error": "store unreachable"}

        backend = _FailOpenBackend()

        with mock.patch(
            "django_smart_ratelimit.management.commands."
            "ratelimit_health.get_backend",
            return_value=backend,
        ):
            out = StringIO()
            call_command("ratelimit_health", "--json", stdout=out)

        result = json.loads(out.getvalue())
        self.assertFalse(result["healthy"])
        self.assertEqual(result["error"], "store unreachable")
