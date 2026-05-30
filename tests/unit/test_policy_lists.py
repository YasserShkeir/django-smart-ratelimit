"""
Unit tests for django_smart_ratelimit.policy.lists module.

Tests cover IPList, FileBackedIPList, URLBackedIPList, and helper functions.
"""

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from django_smart_ratelimit.policy.lists import (
    _MAX_URL_RESPONSE_BYTES,
    FileBackedIPList,
    IPList,
    URLBackedIPList,
    check_lists,
    extract_client_ip,
    parse_ip_list,
)


class IPListTests(SimpleTestCase):
    """Test cases for IPList class."""

    def test_iplist_ipv4_single_ip(self):
        """Test IPList with single IPv4 address."""
        ip_list = IPList(["192.168.1.100"])
        self.assertTrue(ip_list.contains("192.168.1.100"))
        self.assertFalse(ip_list.contains("192.168.1.101"))
        self.assertFalse(ip_list.contains("10.0.0.1"))

    def test_iplist_ipv4_cidr(self):
        """Test IPList with IPv4 CIDR ranges."""
        ip_list = IPList(["10.0.0.0/8", "192.168.0.0/16"])
        # Test first range
        self.assertTrue(ip_list.contains("10.0.0.1"))
        self.assertTrue(ip_list.contains("10.255.255.255"))
        # Test second range
        self.assertTrue(ip_list.contains("192.168.0.0"))
        self.assertTrue(ip_list.contains("192.168.255.255"))
        # Test out of range
        self.assertFalse(ip_list.contains("11.0.0.0"))
        self.assertFalse(ip_list.contains("193.0.0.0"))

    def test_iplist_ipv4_subnet_mask(self):
        """Test IPList with various IPv4 subnet masks."""
        ip_list = IPList(["192.168.1.0/24"])
        self.assertTrue(ip_list.contains("192.168.1.0"))
        self.assertTrue(ip_list.contains("192.168.1.1"))
        self.assertTrue(ip_list.contains("192.168.1.254"))
        self.assertTrue(ip_list.contains("192.168.1.255"))
        self.assertFalse(ip_list.contains("192.168.0.255"))
        self.assertFalse(ip_list.contains("192.168.2.0"))

    def test_iplist_ipv6_single_ip(self):
        """Test IPList with single IPv6 address."""
        ip_list = IPList(["2001:db8::1"])
        self.assertTrue(ip_list.contains("2001:db8::1"))
        self.assertFalse(ip_list.contains("2001:db8::2"))

    def test_iplist_ipv6_cidr(self):
        """Test IPList with IPv6 CIDR ranges."""
        ip_list = IPList(["2001:db8::/32", "fc00::/7"])
        # Test first range
        self.assertTrue(ip_list.contains("2001:db8::1"))
        self.assertTrue(ip_list.contains("2001:db8:ffff:ffff:ffff:ffff:ffff:ffff"))
        # Test second range (ULA)
        self.assertTrue(ip_list.contains("fc00::1"))
        self.assertTrue(ip_list.contains("fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"))
        # Out of range
        self.assertFalse(ip_list.contains("2001:db9::1"))

    def test_iplist_mixed_ipv4_ipv6(self):
        """Test IPList with mixed IPv4 and IPv6 ranges."""
        ip_list = IPList(["10.0.0.0/8", "192.168.0.0/16", "2001:db8::/32", "fc00::/7"])
        # IPv4 checks
        self.assertTrue(ip_list.contains("10.0.0.1"))
        self.assertTrue(ip_list.contains("192.168.1.1"))
        # IPv6 checks
        self.assertTrue(ip_list.contains("2001:db8::1"))
        self.assertTrue(ip_list.contains("fc00::1"))
        # Out of range
        self.assertFalse(ip_list.contains("8.8.8.8"))
        self.assertFalse(ip_list.contains("2001:4860:4860::8888"))

    def test_iplist_single_ip_promotion_ipv4(self):
        """Test that single IPv4 addresses are promoted to /32."""
        ip_list = IPList(["203.0.113.42"])
        self.assertTrue(ip_list.contains("203.0.113.42"))
        self.assertFalse(ip_list.contains("203.0.113.41"))
        self.assertFalse(ip_list.contains("203.0.113.43"))

    def test_iplist_single_ip_promotion_ipv6(self):
        """Test that single IPv6 addresses are promoted to /128."""
        ip_list = IPList(["2001:db8::42"])
        self.assertTrue(ip_list.contains("2001:db8::42"))
        self.assertFalse(ip_list.contains("2001:db8::41"))
        self.assertFalse(ip_list.contains("2001:db8::43"))

    def test_iplist_invalid_cidr_raises_valueerror(self):
        """Test that invalid CIDR notation raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            IPList(["invalid-cidr"])
        self.assertIn("Invalid", str(cm.exception))

    def test_iplist_invalid_ip_address_raises_valueerror(self):
        """Test that invalid IP address raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            IPList(["999.999.999.999"])
        self.assertIn("Invalid", str(cm.exception))

    def test_iplist_invalid_cidr_format_raises_valueerror(self):
        """Test that invalid CIDR format raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            IPList(["10.0.0.0/33"])  # Max is /32 for IPv4
        self.assertIn("Invalid", str(cm.exception))

    def test_iplist_contains_invalid_ip(self):
        """Test contains() with invalid IP returns False."""
        ip_list = IPList(["10.0.0.0/8"])
        self.assertFalse(ip_list.contains("invalid"))
        self.assertFalse(ip_list.contains("999.999.999.999"))
        self.assertFalse(ip_list.contains(""))

    def test_iplist_empty_list(self):
        """Test IPList with empty CIDR list."""
        ip_list = IPList([])
        self.assertFalse(ip_list.contains("10.0.0.1"))
        self.assertFalse(ip_list.contains("192.168.1.1"))


class FileBackedIPListTests(SimpleTestCase):
    """Test cases for FileBackedIPList class."""

    def test_file_backed_iplist_reads_file(self):
        """Test that FileBackedIPList reads from file correctly."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("10.0.0.0/8\n")
            f.write("192.168.0.0/16\n")
            f.write("203.0.113.42\n")
            f.flush()
            path = f.name

        try:
            ip_list = FileBackedIPList(path)
            self.assertTrue(ip_list.contains("10.0.0.1"))
            self.assertTrue(ip_list.contains("192.168.1.1"))
            self.assertTrue(ip_list.contains("203.0.113.42"))
            self.assertFalse(ip_list.contains("8.8.8.8"))
        finally:
            Path(path).unlink()

    def test_file_backed_iplist_ignores_comments(self):
        """Test that FileBackedIPList ignores comments and blank lines."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("# This is a comment\n")
            f.write("\n")
            f.write("10.0.0.0/8\n")
            f.write("# Another comment\n")
            f.write("192.168.0.0/16\n")
            f.write("\n")
            f.flush()
            path = f.name

        try:
            ip_list = FileBackedIPList(path)
            self.assertTrue(ip_list.contains("10.0.0.1"))
            self.assertTrue(ip_list.contains("192.168.1.1"))
        finally:
            Path(path).unlink()

    def test_file_backed_iplist_strips_whitespace(self):
        """Test that FileBackedIPList strips whitespace from lines."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("  10.0.0.0/8  \n")
            f.write("   192.168.0.0/16   \n")
            f.flush()
            path = f.name

        try:
            ip_list = FileBackedIPList(path)
            self.assertTrue(ip_list.contains("10.0.0.1"))
            self.assertTrue(ip_list.contains("192.168.1.1"))
        finally:
            Path(path).unlink()

    def test_file_backed_iplist_nonexistent_file_at_init_logs_warning(self):
        """Test that FileBackedIPList handles missing file gracefully with logging."""
        # FileBackedIPList is resilient - it logs warning but initializes with empty list
        # _read_file() raises FileNotFoundError which is caught by force_refresh()
        path = "/tmp/nonexistent_" + str(time.time()) + ".txt"
        ip_list = FileBackedIPList(path)
        # Should have empty network list since file didn't exist
        self.assertEqual(len(ip_list.networks), 0)
        self.assertFalse(ip_list.contains("10.0.0.1"))

    def test_file_backed_iplist_invalid_cidr_logs_error(self):
        """Test that FileBackedIPList logs error on invalid CIDR during force_refresh."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("10.0.0.0/8\n")
            f.flush()
            path = f.name

        try:
            ip_list = FileBackedIPList(path)
            # Now update file with invalid CIDR
            with open(path, "w") as f:
                f.write("invalid-cidr\n")

            # force_refresh should log error but keep old list
            ip_list.force_refresh()
            # Old list should still be available
            self.assertTrue(ip_list.contains("10.0.0.1"))
        finally:
            Path(path).unlink()

    def test_file_backed_iplist_force_refresh(self):
        """Test force_refresh() reloads from file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("10.0.0.0/8\n")
            f.flush()
            path = f.name

        try:
            ip_list = FileBackedIPList(path)
            self.assertTrue(ip_list.contains("10.0.0.1"))

            # Update file
            with open(path, "w") as f:
                f.write("192.168.0.0/16\n")

            # Before refresh, old list still in memory
            self.assertTrue(ip_list.contains("10.0.0.1"))

            # Force refresh
            ip_list.force_refresh()

            # Now new list is loaded
            self.assertFalse(ip_list.contains("10.0.0.1"))
            self.assertTrue(ip_list.contains("192.168.1.1"))
        finally:
            Path(path).unlink()

    def test_file_backed_iplist_refresh_interval(self):
        """Test that refresh happens after interval expires."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("10.0.0.0/8\n")
            f.flush()
            path = f.name

        try:
            # Use very short refresh interval
            ip_list = FileBackedIPList(path, refresh_interval=1)
            self.assertTrue(ip_list.contains("10.0.0.1"))

            # Update file
            with open(path, "w") as f:
                f.write("192.168.0.0/16\n")

            # Wait for refresh interval
            time.sleep(1.1)

            # Next contains() call should trigger refresh
            self.assertFalse(ip_list.contains("10.0.0.1"))
            self.assertTrue(ip_list.contains("192.168.1.1"))
        finally:
            Path(path).unlink()

    def test_file_backed_iplist_missing_file_keeps_last_list(self):
        """Test that missing file after init keeps last loaded list."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("10.0.0.0/8\n")
            f.flush()
            path = f.name

        try:
            ip_list = FileBackedIPList(path, refresh_interval=1)
            self.assertTrue(ip_list.contains("10.0.0.1"))

            # Delete file
            Path(path).unlink()

            # Wait for refresh interval
            time.sleep(1.1)

            # Next contains() call should attempt refresh but keep old list
            self.assertTrue(ip_list.contains("10.0.0.1"))
        except FileNotFoundError:
            # This is expected in the constructor
            pass

    def test_file_backed_iplist_thread_safe(self):
        """Test that FileBackedIPList is thread-safe."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("10.0.0.0/8\n")
            f.flush()
            path = f.name

        try:
            ip_list = FileBackedIPList(path, refresh_interval=1)
            results = []

            def check_ip():
                for _ in range(100):
                    results.append(ip_list.contains("10.0.0.1"))

            threads = [threading.Thread(target=check_ip) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All checks should have succeeded
            self.assertEqual(len(results), 500)
            self.assertTrue(all(results))
        finally:
            Path(path).unlink()


class URLBackedIPListTests(SimpleTestCase):
    """Test cases for URLBackedIPList class."""

    def test_url_backed_iplist_invalid_url_raises_error(self):
        """Test that URLBackedIPList raises error for invalid URL."""
        with self.assertRaises(ValueError) as cm:
            URLBackedIPList("ftp://example.com/ips.txt")
        self.assertIn("http", str(cm.exception).lower())

    @patch("urllib.request.urlopen")
    def test_url_backed_iplist_fetches_from_url(self, mock_urlopen):
        """Test that URLBackedIPList fetches and parses from URL."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"10.0.0.0/8\n192.168.0.0/16\n203.0.113.42\n"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        ip_list = URLBackedIPList("https://example.com/ips.txt")
        self.assertTrue(ip_list.contains("10.0.0.1"))
        self.assertTrue(ip_list.contains("192.168.1.1"))
        self.assertTrue(ip_list.contains("203.0.113.42"))
        self.assertFalse(ip_list.contains("8.8.8.8"))

    @patch("urllib.request.urlopen")
    def test_url_backed_iplist_ignores_comments(self, mock_urlopen):
        """Test that URLBackedIPList ignores comments and blank lines."""
        mock_response = MagicMock()
        mock_response.read.return_value = (
            b"# Comment\n\n10.0.0.0/8\n# Another\n192.168.0.0/16\n\n"
        )
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        ip_list = URLBackedIPList("https://example.com/ips.txt")
        self.assertTrue(ip_list.contains("10.0.0.1"))
        self.assertTrue(ip_list.contains("192.168.1.1"))

    @patch("urllib.request.urlopen")
    def test_url_backed_iplist_http_error_keeps_old_list(self, mock_urlopen):
        """Test that HTTP error keeps old list."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"10.0.0.0/8\n"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        ip_list = URLBackedIPList("https://example.com/ips.txt")
        self.assertTrue(ip_list.contains("10.0.0.1"))

        # Now simulate HTTP error
        mock_urlopen.side_effect = Exception("Connection failed")

        # Force refresh should fail but keep old list
        ip_list.force_refresh()
        self.assertTrue(ip_list.contains("10.0.0.1"))

    @patch("urllib.request.urlopen")
    def test_url_backed_iplist_refresh_interval(self, mock_urlopen):
        """Test that refresh happens after interval expires."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"10.0.0.0/8\n"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        ip_list = URLBackedIPList("https://example.com/ips.txt", refresh_interval=1)
        self.assertTrue(ip_list.contains("10.0.0.1"))
        call_count_1 = mock_urlopen.call_count

        # Update mock response
        mock_response.read.return_value = b"192.168.0.0/16\n"

        # Check within interval - should not call fetch again
        self.assertTrue(ip_list.contains("10.0.0.1"))
        self.assertEqual(mock_urlopen.call_count, call_count_1)

        # Wait for interval
        time.sleep(1.1)

        # Next check should trigger fetch
        self.assertTrue(ip_list.contains("192.168.1.1"))
        self.assertGreater(mock_urlopen.call_count, call_count_1)

    @patch("urllib.request.urlopen")
    def test_url_backed_iplist_thread_safe(self, mock_urlopen):
        """Test that URLBackedIPList is thread-safe."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"10.0.0.0/8\n"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        ip_list = URLBackedIPList("https://example.com/ips.txt")
        results = []

        def check_ip():
            for _ in range(100):
                results.append(ip_list.contains("10.0.0.1"))

        threads = [threading.Thread(target=check_ip) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All checks should have succeeded
        self.assertEqual(len(results), 500)
        self.assertTrue(all(results))


class ParseIPListTests(SimpleTestCase):
    """Test cases for parse_ip_list helper function."""

    def test_parse_iplist_none_returns_none(self):
        """Test parse_ip_list(None) returns None."""
        result = parse_ip_list(None)
        self.assertIsNone(result)

    def test_parse_iplist_iplist_instance_returns_as_is(self):
        """Test parse_ip_list with IPList returns same instance."""
        ip_list = IPList(["10.0.0.0/8"])
        result = parse_ip_list(ip_list)
        self.assertIs(result, ip_list)

    def test_parse_iplist_list_returns_iplist(self):
        """Test parse_ip_list with list returns IPList."""
        cidrs = ["10.0.0.0/8", "192.168.0.0/16"]
        result = parse_ip_list(cidrs)
        self.assertIsInstance(result, IPList)
        self.assertTrue(result.contains("10.0.0.1"))

    def test_parse_iplist_file_url_returns_filebacked(self):
        """Test parse_ip_list with file:// URL returns FileBackedIPList."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("10.0.0.0/8\n")
            f.flush()
            path = f.name

        try:
            result = parse_ip_list(f"file://{path}")
            self.assertIsInstance(result, FileBackedIPList)
            self.assertTrue(result.contains("10.0.0.1"))
        finally:
            Path(path).unlink()

    def test_parse_iplist_file_path_returns_filebacked(self):
        """Test parse_ip_list with file path returns FileBackedIPList."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("10.0.0.0/8\n")
            f.flush()
            path = f.name

        try:
            result = parse_ip_list(path)
            self.assertIsInstance(result, FileBackedIPList)
            self.assertTrue(result.contains("10.0.0.1"))
        finally:
            Path(path).unlink()

    @patch("urllib.request.urlopen")
    def test_parse_iplist_http_url_returns_urlbacked(self, mock_urlopen):
        """Test parse_ip_list with http URL returns URLBackedIPList."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"10.0.0.0/8\n"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        result = parse_ip_list("https://example.com/ips.txt")
        self.assertIsInstance(result, URLBackedIPList)

    @patch("urllib.request.urlopen")
    def test_parse_iplist_http_url_returns_urlbacked_http(self, mock_urlopen):
        """Test parse_ip_list with http URL returns URLBackedIPList."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"10.0.0.0/8\n"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        result = parse_ip_list("http://example.com/ips.txt")
        self.assertIsInstance(result, URLBackedIPList)

    def test_parse_iplist_single_cidr_returns_iplist(self):
        """Test parse_ip_list with single CIDR returns IPList."""
        result = parse_ip_list("10.0.0.0/8")
        self.assertIsInstance(result, IPList)
        self.assertTrue(result.contains("10.0.0.1"))

    def test_parse_iplist_single_ip_returns_iplist(self):
        """Test parse_ip_list with single IP returns IPList."""
        result = parse_ip_list("203.0.113.42")
        self.assertIsInstance(result, IPList)
        self.assertTrue(result.contains("203.0.113.42"))


class ExtractClientIPTests(SimpleTestCase):
    """Test cases for extract_client_ip function."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()

    def test_extract_client_ip_remote_addr(self):
        """Test extract_client_ip with REMOTE_ADDR."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.100"
        ip = extract_client_ip(request)
        self.assertEqual(ip, "192.168.1.100")

    def test_extract_client_ip_x_forwarded_for(self):
        """Test extract_client_ip respects X-Forwarded-For."""
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.42"
        ip = extract_client_ip(request)
        self.assertEqual(ip, "203.0.113.42")

    def test_extract_client_ip_x_forwarded_for_comma_separated(self):
        """Test extract_client_ip handles comma-separated X-Forwarded-For."""
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.42, 10.0.0.1, 192.168.1.1"
        ip = extract_client_ip(request)
        # Should use first IP
        self.assertEqual(ip, "203.0.113.42")

    def test_extract_client_ip_x_real_ip(self):
        """Test extract_client_ip respects X-Real-IP."""
        request = self.factory.get("/")
        request.META["HTTP_X_REAL_IP"] = "203.0.113.42"
        ip = extract_client_ip(request)
        self.assertEqual(ip, "203.0.113.42")

    def test_extract_client_ip_cloudflare(self):
        """Test extract_client_ip respects Cloudflare IP header."""
        request = self.factory.get("/")
        request.META["HTTP_CF_CONNECTING_IP"] = "203.0.113.42"
        ip = extract_client_ip(request)
        self.assertEqual(ip, "203.0.113.42")

    def test_extract_client_ip_cloudflare_takes_precedence(self):
        """Test extract_client_ip prefers Cloudflare over other headers."""
        request = self.factory.get("/")
        request.META["HTTP_CF_CONNECTING_IP"] = "203.0.113.42"
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.43"
        request.META["HTTP_X_REAL_IP"] = "203.0.113.44"
        ip = extract_client_ip(request)
        self.assertEqual(ip, "203.0.113.42")

    def test_extract_client_ip_whitespace_stripped(self):
        """Test extract_client_ip strips whitespace."""
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "  203.0.113.42  "
        ip = extract_client_ip(request)
        self.assertEqual(ip, "203.0.113.42")

    def test_extract_client_ip_unknown_default(self):
        """Test extract_client_ip returns unknown when no IP found."""
        request = self.factory.get("/")
        request.META = {}
        ip = extract_client_ip(request)
        self.assertEqual(ip, "unknown")


class CheckListsTests(SimpleTestCase):
    """Test cases for check_lists function."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()

    def test_check_lists_no_lists_returns_false_empty_reason(self):
        """Test check_lists with no lists returns (False, '')."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.100"
        should_skip, reason = check_lists(request)
        self.assertFalse(should_skip)
        self.assertEqual(reason, "")

    def test_check_lists_allow_list_skip(self):
        """Test check_lists skips rate limiting for IPs in allow list."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        allow_list = IPList(["10.0.0.0/8"])
        should_skip, reason = check_lists(request, allow_list=allow_list)
        self.assertTrue(should_skip)
        self.assertEqual(reason, "allow_list")

    def test_check_lists_deny_list_block(self):
        """Test check_lists blocks for IPs in deny list."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "203.0.113.42"
        deny_list = IPList(["203.0.113.0/24"])
        should_skip, reason = check_lists(request, deny_list=deny_list)
        self.assertFalse(should_skip)
        self.assertEqual(reason, "deny_list")

    def test_check_lists_deny_precedence_over_allow(self):
        """Test check_lists deny list takes precedence over allow list."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        allow_list = IPList(["10.0.0.0/8"])
        deny_list = IPList(["10.0.0.0/16"])
        should_skip, reason = check_lists(
            request, allow_list=allow_list, deny_list=deny_list
        )
        self.assertFalse(should_skip)
        self.assertEqual(reason, "deny_list")

    def test_check_lists_neither_list_normal_limiting(self):
        """Test check_lists returns (False, '') when IP not in either list."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "8.8.8.8"
        allow_list = IPList(["10.0.0.0/8"])
        deny_list = IPList(["203.0.113.0/24"])
        should_skip, reason = check_lists(
            request, allow_list=allow_list, deny_list=deny_list
        )
        self.assertFalse(should_skip)
        self.assertEqual(reason, "")

    def test_check_lists_only_allow_list(self):
        """Test check_lists with only allow list."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        allow_list = IPList(["10.0.0.0/8"])
        should_skip, reason = check_lists(request, allow_list=allow_list)
        self.assertTrue(should_skip)
        self.assertEqual(reason, "allow_list")

    def test_check_lists_only_deny_list(self):
        """Test check_lists with only deny list."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "203.0.113.42"
        deny_list = IPList(["203.0.113.0/24"])
        should_skip, reason = check_lists(request, deny_list=deny_list)
        self.assertFalse(should_skip)
        self.assertEqual(reason, "deny_list")

    def test_check_lists_respects_x_forwarded_for(self):
        """Test check_lists uses extract_client_ip for proxy support."""
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.42"
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        deny_list = IPList(["203.0.113.0/24"])
        should_skip, reason = check_lists(request, deny_list=deny_list)
        self.assertFalse(should_skip)
        self.assertEqual(reason, "deny_list")


class FailClosedDenyListTests(SimpleTestCase):
    """Test cases for the fail-closed deny-list behavior in check_lists."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()

    def _request(self, ip="8.8.8.8"):
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = ip
        return request

    def test_filebacked_missing_file_sets_load_failed(self):
        """A deny-list file that never loads marks the list load_failed."""
        path = "/tmp/nonexistent_deny_" + str(time.time()) + ".txt"
        deny_list = FileBackedIPList(path)
        self.assertTrue(deny_list.load_failed)
        self.assertEqual(len(deny_list.networks), 0)

    @override_settings(RATELIMIT_POLICY_FAIL_CLOSED=True)
    def test_fail_closed_denies_when_initial_load_failed(self):
        """When fail-closed is on and the deny source never loaded, deny."""
        path = "/tmp/nonexistent_deny_" + str(time.time()) + ".txt"
        deny_list = FileBackedIPList(path)
        should_skip, reason = check_lists(self._request(), deny_list=deny_list)
        self.assertFalse(should_skip)
        self.assertEqual(reason, "deny_list")

    @override_settings(RATELIMIT_POLICY_FAIL_CLOSED=False)
    def test_fail_open_allows_when_initial_load_failed(self):
        """Default (fail-open): an unloaded deny source allows everyone."""
        path = "/tmp/nonexistent_deny_" + str(time.time()) + ".txt"
        deny_list = FileBackedIPList(path)
        should_skip, reason = check_lists(self._request(), deny_list=deny_list)
        self.assertFalse(should_skip)
        self.assertEqual(reason, "")

    def test_fail_closed_default_is_fail_open(self):
        """With no setting configured, behavior is fail-open (backward compat)."""
        path = "/tmp/nonexistent_deny_" + str(time.time()) + ".txt"
        deny_list = FileBackedIPList(path)
        should_skip, reason = check_lists(self._request(), deny_list=deny_list)
        self.assertFalse(should_skip)
        self.assertEqual(reason, "")

    @override_settings(RATELIMIT_POLICY_FAIL_CLOSED=True)
    def test_fail_closed_not_triggered_for_loaded_deny_list(self):
        """A successfully-loaded deny list is unaffected by fail-closed."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("203.0.113.0/24\n")
            f.flush()
            path = f.name

        try:
            deny_list = FileBackedIPList(path)
            self.assertFalse(deny_list.load_failed)
            # An IP not in the deny list continues to normal limiting.
            should_skip, reason = check_lists(
                self._request("8.8.8.8"), deny_list=deny_list
            )
            self.assertFalse(should_skip)
            self.assertEqual(reason, "")
            # An IP in the deny list is blocked as usual.
            should_skip, reason = check_lists(
                self._request("203.0.113.42"), deny_list=deny_list
            )
            self.assertFalse(should_skip)
            self.assertEqual(reason, "deny_list")
        finally:
            Path(path).unlink()

    @override_settings(RATELIMIT_POLICY_FAIL_CLOSED=True)
    def test_fail_closed_does_not_affect_allow_list(self):
        """An allow list that failed to load does not fail closed (deny)."""
        path = "/tmp/nonexistent_allow_" + str(time.time()) + ".txt"
        allow_list = FileBackedIPList(path)
        self.assertTrue(allow_list.load_failed)
        # No deny list -> allow-list load failure must not deny the request.
        should_skip, reason = check_lists(self._request(), allow_list=allow_list)
        self.assertFalse(should_skip)
        self.assertEqual(reason, "")

    @override_settings(RATELIMIT_POLICY_FAIL_CLOSED=True)
    def test_successful_refresh_clears_load_failed(self):
        """A deny list that recovers via refresh stops failing closed."""
        path = "/tmp/recovering_deny_" + str(time.time()) + ".txt"
        deny_list = FileBackedIPList(path, refresh_interval=0)
        self.assertTrue(deny_list.load_failed)

        # Create the file now and force a refresh.
        try:
            with open(path, "w") as f:
                f.write("203.0.113.0/24\n")
            deny_list.force_refresh()
            self.assertFalse(deny_list.load_failed)

            should_skip, reason = check_lists(self._request(), deny_list=deny_list)
            self.assertFalse(should_skip)
            self.assertEqual(reason, "")
        finally:
            Path(path).unlink()

    @override_settings(RATELIMIT_POLICY_FAIL_CLOSED=True)
    def test_transient_refresh_failure_keeps_last_good_and_does_not_fail_closed(self):
        """A transient refresh failure keeps last-good and does not fail closed."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("203.0.113.0/24\n")
            f.flush()
            path = f.name

        try:
            deny_list = FileBackedIPList(path, refresh_interval=0)
            self.assertFalse(deny_list.load_failed)

            # Delete the file to simulate a transient source failure, then
            # refresh: last-good is kept and load_failed stays False.
            Path(path).unlink()
            deny_list.force_refresh()
            self.assertFalse(deny_list.load_failed)

            # Fail-closed must NOT trigger because we still serve last-good.
            should_skip, reason = check_lists(
                self._request("203.0.113.42"), deny_list=deny_list
            )
            self.assertFalse(should_skip)
            self.assertEqual(reason, "deny_list")
        finally:
            if Path(path).exists():
                Path(path).unlink()


class URLBackedIPListHardeningTests(SimpleTestCase):
    """Test cases for URLBackedIPList defense-in-depth hardening."""

    def _mock_response(self, body: bytes):
        mock_response = MagicMock()
        mock_response.read.return_value = body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        return mock_response

    @patch("urllib.request.urlopen")
    def test_http_feed_logs_warning(self, mock_urlopen):
        """A plain http:// feed URL logs a non-TLS warning."""
        mock_urlopen.return_value = self._mock_response(b"10.0.0.0/8\n")
        with self.assertLogs(
            "django_smart_ratelimit.policy.lists", level="WARNING"
        ) as cm:
            URLBackedIPList("http://example.com/ips.txt")
        self.assertTrue(any("http://" in msg for msg in cm.output))
        self.assertTrue(any("TLS" in msg for msg in cm.output))

    @patch("urllib.request.urlopen")
    def test_https_feed_does_not_warn(self, mock_urlopen):
        """An https:// feed URL does not log the non-TLS warning."""
        mock_urlopen.return_value = self._mock_response(b"10.0.0.0/8\n")
        # assertNoLogs is 3.10+, so inspect records via assertLogs on a no-op.
        import logging as _logging

        logger = _logging.getLogger("django_smart_ratelimit.policy.lists")
        records = []
        handler = _logging.Handler()
        handler.emit = records.append  # type: ignore[assignment]
        logger.addHandler(handler)
        try:
            URLBackedIPList("https://example.com/ips.txt")
        finally:
            logger.removeHandler(handler)
        self.assertFalse(
            any(r.levelno >= _logging.WARNING for r in records),
            "https feed should not emit a non-TLS warning",
        )

    @patch("urllib.request.urlopen")
    def test_read_size_cap_rejects_oversized_response(self, mock_urlopen):
        """A response over the size cap is rejected (initial load fails)."""
        oversized = b"10.0.0.0/8\n" * ((_MAX_URL_RESPONSE_BYTES // 11) + 100)
        # The code reads MAX+1 bytes; simulate read(n) honoring its argument.
        mock_response = MagicMock()
        mock_response.read.side_effect = lambda n=None: (
            oversized[:n] if n is not None else oversized
        )
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        with self.assertLogs("django_smart_ratelimit.policy.lists", level="ERROR"):
            ip_list = URLBackedIPList("https://example.com/ips.txt")
        # Oversized initial load leaves the list empty and flagged as failed.
        self.assertEqual(len(ip_list.networks), 0)
        self.assertTrue(ip_list.load_failed)

    @patch("urllib.request.urlopen")
    def test_read_called_with_size_limit(self, mock_urlopen):
        """The response is read with the byte cap (read(MAX+1))."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"10.0.0.0/8\n"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        URLBackedIPList("https://example.com/ips.txt")
        mock_response.read.assert_called_once_with(_MAX_URL_RESPONSE_BYTES + 1)

    @patch("urllib.request.urlopen")
    def test_response_at_cap_is_accepted(self, mock_urlopen):
        """A response exactly at the cap is accepted, not rejected."""
        body = b"10.0.0.0/8\n"
        padding = b"# " + b"x" * (_MAX_URL_RESPONSE_BYTES - len(body) - 3) + b"\n"
        at_cap = body + padding
        self.assertEqual(len(at_cap), _MAX_URL_RESPONSE_BYTES)

        mock_response = MagicMock()
        mock_response.read.side_effect = lambda n=None: (
            at_cap[:n] if n is not None else at_cap
        )
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        ip_list = URLBackedIPList("https://example.com/ips.txt")
        self.assertFalse(ip_list.load_failed)
        self.assertTrue(ip_list.contains("10.0.0.1"))
