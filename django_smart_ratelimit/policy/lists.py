"""
CIDR-based allow/deny list implementations for django-smart-ratelimit.

This module provides classes for managing IP allowlists and denylists using CIDR notation.
It supports IPv4 and IPv6 addresses, file-based configuration, and URL-based feeds.

IMPORTANT SECURITY NOTE ON X-Forwarded-For:
The `extract_client_ip` function respects X-Forwarded-For headers to support proxies and CDNs.
However, this header can be spoofed if not properly validated. Only trust X-Forwarded-For
if your application is behind a trusted proxy and you've configured Django's TRUSTED_PROXIES
setting appropriately. Otherwise, clients can spoof their IP address and bypass IP-based
rate limiting controls.

Examples:
    Basic IP list for allow/deny:

        from django_smart_ratelimit.policy import IPList

        internal_ips = IPList(['10.0.0.0/8', '192.168.1.0/24'])
        if internal_ips.contains('10.0.0.5'):
            # Skip rate limiting
            pass

    File-backed IP list with auto-refresh:

        from django_smart_ratelimit.policy import FileBackedIPList

        blocklist = FileBackedIPList('/etc/ratelimit/blocklist.txt', refresh_interval=300)
        if blocklist.contains(client_ip):
            # Force block this IP
            return HttpResponse(status=429)

    URL-based threat intelligence feed:

        from django_smart_ratelimit.policy import URLBackedIPList

        threat_feed = URLBackedIPList(
            'https://example.com/threats/blocklist.txt',
            refresh_interval=3600,
            http_timeout=10
        )
        if threat_feed.contains(client_ip):
            # Block based on threat intel
            return HttpResponse(status=429)

    Using parse_ip_list for flexible input:

        from django_smart_ratelimit.policy import parse_ip_list, check_lists

        allow_list = parse_ip_list('file:///etc/ratelimit/allowlist.txt')
        deny_list = parse_ip_list(['10.0.0.0/8', '203.0.113.0/24'])

        should_skip, reason = check_lists(request, allow_list, deny_list)
        if should_skip:
            # Skip rate limiting
            pass
        elif reason == 'deny_list':
            # Force block
            return HttpResponse(status=429)
"""

import ipaddress
import logging
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional, Tuple, Union

from django.http import HttpRequest

logger = logging.getLogger(__name__)


class IPList:
    """
    In-memory CIDR-based IP list for checking if an IP is in a set of networks.

    This class efficiently stores and checks IP addresses and CIDR ranges using
    Python's ipaddress module. Single IP addresses are automatically promoted
    to /32 (IPv4) or /128 (IPv6) CIDR notation.

    Args:
        cidrs: List of CIDR strings (e.g., ['10.0.0.0/8', '192.168.0.0/16', '203.0.113.42'])

    Raises:
        ValueError: If any CIDR string is invalid

    Examples:
        >>> allowed = IPList(['10.0.0.0/8', '192.168.1.0/24', '203.0.113.42'])
        >>> allowed.contains('10.0.0.5')
        True
        >>> allowed.contains('192.168.1.100')
        True
        >>> allowed.contains('203.0.113.42')
        True
        >>> allowed.contains('8.8.8.8')
        False
    """

    def __init__(self, cidrs: List[str]) -> None:
        """Initialize IPList with CIDR ranges."""
        self.networks: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = []

        for cidr in cidrs:
            try:
                # Handle single IPs by converting to /32 or /128
                if "/" not in cidr:
                    try:
                        ip = ipaddress.ip_address(cidr)
                        if isinstance(ip, ipaddress.IPv4Address):
                            cidr = f"{cidr}/32"
                        else:
                            cidr = f"{cidr}/128"
                    except ValueError as e:
                        raise ValueError(f"Invalid IP address: {cidr}") from e

                network = ipaddress.ip_network(cidr, strict=False)
                self.networks.append(network)
            except ValueError as e:
                raise ValueError(
                    f"Invalid CIDR notation: {cidr}. "
                    f"Expected format like '10.0.0.0/8' or '192.168.1.1'. "
                    f"Error: {e}"
                ) from e

    def contains(self, ip: str) -> bool:
        """
        Check if an IP address is in any of the networks.

        Args:
            ip: IP address string (e.g., '192.168.1.100')

        Returns:
            True if IP is in any network, False otherwise
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            for network in self.networks:
                if ip_obj in network:
                    return True
            return False
        except ValueError:
            # Invalid IP format
            logger.debug(f"Invalid IP address format: {ip}")
            return False


class FileBackedIPList(IPList):
    """
    File-backed CIDR-based IP list with automatic refresh capability.

    This class reads IP ranges from a file and periodically refreshes the list
    from disk. The refresh is lazy (only checked on lookup after the interval
    has passed) and thread-safe.

    File format:
        - One CIDR range or IP per line
        - Comments starting with '#' are ignored
        - Blank lines are ignored
        - Examples: 10.0.0.0/8, 192.168.1.0/24, 203.0.113.42

    Args:
        path: File path to read CIDRs from
        refresh_interval: Seconds between file refreshes (default: 300)

    Raises:
        ValueError: If file cannot be read or contains invalid CIDRs
        FileNotFoundError: If file does not exist initially

    Examples:
        >>> blocklist = FileBackedIPList('/etc/ratelimit/blocklist.txt', refresh_interval=300)
        >>> if blocklist.contains('10.0.0.5'):
        ...     # Handle blocked IP
        ...     pass

        >>> blocklist.force_refresh()  # Explicitly reload from disk
    """

    def __init__(self, path: str, refresh_interval: int = 300) -> None:
        """Initialize FileBackedIPList."""
        self.path = path
        self.refresh_interval = refresh_interval
        self.last_refresh = 0.0
        self._lock = threading.RLock()
        self.networks: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = []

        # Load initial list
        self.force_refresh()

    def _read_file(self) -> List[str]:
        """
        Read and parse CIDR list from file.

        Returns:
            List of valid CIDR strings

        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If file cannot be read
        """
        try:
            path_obj = Path(self.path)
            if not path_obj.exists():
                raise FileNotFoundError(f"IP list file not found: {self.path}")

            cidrs = []
            with open(path_obj, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    # Strip whitespace and skip empty lines/comments
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    cidrs.append(line)

            return cidrs
        except FileNotFoundError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to read IP list file {self.path}: {e}") from e

    def force_refresh(self) -> None:
        """Force an immediate refresh of the IP list from disk."""
        with self._lock:
            try:
                cidrs = self._read_file()
                # Validate all CIDRs before committing
                networks = []
                for cidr in cidrs:
                    if "/" not in cidr:
                        try:
                            ip = ipaddress.ip_address(cidr)
                            if isinstance(ip, ipaddress.IPv4Address):
                                cidr = f"{cidr}/32"
                            else:
                                cidr = f"{cidr}/128"
                        except ValueError as e:
                            raise ValueError(f"Invalid IP address: {cidr}") from e

                    network = ipaddress.ip_network(cidr, strict=False)
                    networks.append(network)

                self.networks = networks
                self.last_refresh = time.time()
                logger.debug(
                    f"Refreshed IP list from {self.path}: {len(networks)} networks"
                )
            except FileNotFoundError:
                logger.warning(
                    f"IP list file {self.path} not found, keeping last loaded list"
                )
            except ValueError as e:
                logger.error(f"Invalid CIDR in {self.path}: {e}, keeping last loaded list")

    def _check_refresh(self) -> None:
        """Check if refresh is needed and perform it if necessary."""
        current_time = time.time()
        if current_time - self.last_refresh > self.refresh_interval:
            self.force_refresh()

    def contains(self, ip: str) -> bool:
        """
        Check if an IP address is in any of the networks.

        Performs a lazy refresh check before lookup.

        Args:
            ip: IP address string

        Returns:
            True if IP is in any network, False otherwise
        """
        with self._lock:
            self._check_refresh()
            return super().contains(ip)


class URLBackedIPList(IPList):
    """
    URL-backed CIDR-based IP list with automatic refresh capability.

    This class fetches IP ranges from a URL (e.g., a threat intelligence feed)
    and periodically refreshes the list. The refresh is lazy (only checked on
    lookup after the interval has passed) and thread-safe.

    Expected response format:
        - Newline-separated CIDR ranges or IP addresses
        - Comments starting with '#' are ignored
        - Blank lines are ignored

    Args:
        url: URL to fetch IP list from (must start with http:// or https://)
        refresh_interval: Seconds between URL fetches (default: 3600)
        http_timeout: Seconds to wait for HTTP response (default: 10)

    Raises:
        ValueError: If URL is invalid or contains invalid CIDRs

    Examples:
        >>> threat_feed = URLBackedIPList(
        ...     'https://example.com/threats/blocklist.txt',
        ...     refresh_interval=3600,
        ...     http_timeout=10
        ... )
        >>> if threat_feed.contains('203.0.113.5'):
        ...     # Handle threat IP
        ...     pass
    """

    def __init__(
        self,
        url: str,
        refresh_interval: int = 3600,
        http_timeout: int = 10,
    ) -> None:
        """Initialize URLBackedIPList."""
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"URL must start with http:// or https://: {url}")

        self.url = url
        self.refresh_interval = refresh_interval
        self.http_timeout = http_timeout
        self.last_refresh = 0.0
        self._lock = threading.RLock()
        self.networks: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = []

        # Load initial list
        self.force_refresh()

    def _fetch_url(self) -> List[str]:
        """
        Fetch and parse CIDR list from URL.

        Returns:
            List of valid CIDR strings

        Raises:
            ValueError: If URL fetch fails or response is invalid
        """
        try:
            request = urllib.request.Request(self.url)
            request.add_header("User-Agent", "django-smart-ratelimit/3.0.0")

            with urllib.request.urlopen(  # nosec B310 - URL is opt-in by caller via source=
                request, timeout=self.http_timeout
            ) as response:
                content = response.read().decode("utf-8")

            cidrs = []
            for line in content.splitlines():
                # Strip whitespace and skip empty lines/comments
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                cidrs.append(line)

            return cidrs
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            raise ValueError(f"Failed to fetch IP list from {self.url}: {e}") from e
        except Exception as e:
            raise ValueError(f"Error fetching IP list from {self.url}: {e}") from e

    def force_refresh(self) -> None:
        """Force an immediate refresh of the IP list from the URL."""
        with self._lock:
            try:
                cidrs = self._fetch_url()
                # Validate all CIDRs before committing
                networks = []
                for cidr in cidrs:
                    if "/" not in cidr:
                        try:
                            ip = ipaddress.ip_address(cidr)
                            if isinstance(ip, ipaddress.IPv4Address):
                                cidr = f"{cidr}/32"
                            else:
                                cidr = f"{cidr}/128"
                        except ValueError as e:
                            raise ValueError(f"Invalid IP address: {cidr}") from e

                    network = ipaddress.ip_network(cidr, strict=False)
                    networks.append(network)

                self.networks = networks
                self.last_refresh = time.time()
                logger.debug(
                    f"Refreshed IP list from {self.url}: {len(networks)} networks"
                )
            except ValueError as e:
                logger.error(
                    f"Failed to refresh IP list from {self.url}: {e}, "
                    f"keeping last loaded list"
                )

    def _check_refresh(self) -> None:
        """Check if refresh is needed and perform it if necessary."""
        current_time = time.time()
        if current_time - self.last_refresh > self.refresh_interval:
            self.force_refresh()

    def contains(self, ip: str) -> bool:
        """
        Check if an IP address is in any of the networks.

        Performs a lazy refresh check before lookup.

        Args:
            ip: IP address string

        Returns:
            True if IP is in any network, False otherwise
        """
        with self._lock:
            self._check_refresh()
            return super().contains(ip)


def parse_ip_list(
    source: Union[str, List[str], IPList, None]
) -> Optional[IPList]:
    """
    Parse various input formats into an IPList instance.

    Supports:
        - None -> returns None
        - IPList instance -> returns as-is
        - List[str] -> wraps in IPList
        - str starting with 'file://' -> wraps in FileBackedIPList
        - str that is an existing file path -> wraps in FileBackedIPList
        - str starting with 'http://' or 'https://' -> wraps in URLBackedIPList
        - str single CIDR/IP -> wraps in IPList

    Args:
        source: Input source (various formats)

    Returns:
        IPList instance or None

    Examples:
        >>> allow = parse_ip_list(['10.0.0.0/8', '192.168.0.0/16'])
        >>> allow = parse_ip_list('file:///etc/ratelimit/allowlist.txt')
        >>> allow = parse_ip_list('https://example.com/ips.txt')
        >>> allow = parse_ip_list('203.0.113.42')
        >>> allow = parse_ip_list(None)  # Returns None
    """
    if source is None:
        return None

    if isinstance(source, IPList):
        return source

    if isinstance(source, list):
        return IPList(source)

    if isinstance(source, str):
        # File-backed list
        if source.startswith("file://"):
            path = source[7:]  # Remove 'file://' prefix
            return FileBackedIPList(path)

        # Check if it's an existing file path
        if Path(source).exists():
            return FileBackedIPList(source)

        # URL-backed list
        if source.startswith(("http://", "https://")):
            return URLBackedIPList(source)

        # Single CIDR/IP
        return IPList([source])

    # Unsupported type, return None
    logger.warning(f"Unsupported IP list source type: {type(source)}")
    return None


def extract_client_ip(request: HttpRequest) -> str:
    """
    Extract client IP address from a Django request.

    Respects proxy headers (X-Forwarded-For, X-Real-IP, CF-Connecting-IP) to
    support requests through load balancers and CDNs.

    SECURITY WARNING:
    This function trusts X-Forwarded-For and other proxy headers. These headers
    can be spoofed if the request doesn't come from a trusted proxy. Only rely
    on this function if your application is deployed behind a trusted reverse
    proxy and you've configured Django's TRUSTED_PROXIES appropriately.

    Args:
        request: Django HTTP request object

    Returns:
        Client IP address string or "unknown" if unable to extract

    Examples:
        >>> ip = extract_client_ip(request)
        >>> if blocklist.contains(ip):
        ...     # Handle blocked IP
        ...     pass
    """
    # Order of preference for IP headers
    ip_headers = [
        "HTTP_CF_CONNECTING_IP",  # Cloudflare
        "HTTP_X_FORWARDED_FOR",  # Standard proxy header
        "HTTP_X_REAL_IP",  # Nginx
        "REMOTE_ADDR",  # Direct connection (always available)
    ]

    for header in ip_headers:
        ip = request.META.get(header, "").strip()
        if ip and ip != "unknown":
            # Handle comma-separated IPs (X-Forwarded-For)
            if "," in ip:
                ip = ip.split(",")[0].strip()
            if ip:
                return ip

    return "unknown"


def check_lists(
    request: HttpRequest,
    allow_list: Optional[IPList] = None,
    deny_list: Optional[IPList] = None,
) -> Tuple[bool, str]:
    """
    Check if request IP is in allow/deny lists.

    Checks precedence:
        1. If IP is in deny_list -> returns (False, "deny_list") [force block]
        2. If IP is in allow_list -> returns (True, "allow_list") [skip rate limiting]
        3. Otherwise -> returns (False, "") [continue normal rate limiting]

    Args:
        request: Django HTTP request object
        allow_list: IPList of IPs to allow (bypass rate limiting)
        deny_list: IPList of IPs to deny (force block)

    Returns:
        Tuple of (should_skip_rate_limit, reason):
            - (True, "allow_list") if IP should skip rate limiting
            - (False, "deny_list") if IP should be force-blocked
            - (False, "") if neither list matches (normal rate limiting applies)

    Examples:
        >>> allow = IPList(['10.0.0.0/8'])
        >>> deny = IPList(['10.0.0.5'])
        >>> should_skip, reason = check_lists(request, allow, deny)
        >>> if reason == 'deny_list':
        ...     return HttpResponse('Blocked', status=429)
        >>> elif should_skip:
        ...     # Skip rate limiting
        ...     pass
        >>> else:
        ...     # Apply normal rate limiting
        ...     pass
    """
    client_ip = extract_client_ip(request)

    # Deny takes precedence
    if deny_list and deny_list.contains(client_ip):
        return (False, "deny_list")

    # Then check allow list
    if allow_list and allow_list.contains(client_ip):
        return (True, "allow_list")

    # Neither list matched
    return (False, "")
