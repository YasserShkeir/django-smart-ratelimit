from unittest.mock import MagicMock, patch

from django.test import TestCase

from django_smart_ratelimit.backends.base import BaseBackend
from django_smart_ratelimit.plugins import discover_plugins, get_all_backends


class MockPlugin(BaseBackend):
    pass


class PluginSystemTest(TestCase):
    def test_discover_plugins(self):
        """Test that we can discover plugins via entry points."""

        # Create a mock entry point
        mock_ep = MagicMock()
        mock_ep.name = "mock_plugin"
        mock_ep.load.return_value = MockPlugin

        # Mock importlib.metadata.entry_points
        with patch("importlib.metadata.entry_points") as mock_entry_points:
            # Setup return value to look like Python 3.10+ select() result
            # or dict for 3.9 depending on what logic we hit.
            # But wait, our code handles both.

            # Let's mock the object returned by entry_points()
            mock_eps_result = MagicMock()

            # Configure select() behavior (Py3.10+)
            mock_eps_result.select.return_value = [mock_ep]

            # Configure legacy behavior (Py3.9) if needed (get/getitem)
            # If select is not present, we use .get().
            # Our mock has .select, so the code should take the first branch.

            mock_entry_points.return_value = mock_eps_result

            plugins = discover_plugins()

            self.assertIn("mock_plugin", plugins)
            self.assertEqual(plugins["mock_plugin"], MockPlugin)

    def test_get_all_backends(self):
        """Test getting all backends includes built-ins and plugins."""
        with patch("django_smart_ratelimit.plugins.discover_plugins") as mock_discover:
            mock_discover.return_value = {"mock_plugin": MockPlugin}

            backends = get_all_backends()

            # Check built-ins
            self.assertIn("memory", backends)
            self.assertIn("redis", backends)

            # Check plugin
            self.assertIn("mock_plugin", backends)
            self.assertEqual(backends["mock_plugin"], MockPlugin)
