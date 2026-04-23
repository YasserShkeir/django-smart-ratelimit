"""
Policy module for django-smart-ratelimit.

This module provides utilities for CIDR-based allow/deny lists to manage
rate limiting policies based on IP addresses and network ranges.

Key classes:
    - IPList: In-memory CIDR-based IP list
    - FileBackedIPList: IP list backed by a file with auto-refresh
    - URLBackedIPList: IP list backed by a URL fetch with auto-refresh

Key functions:
    - parse_ip_list: Convert various input formats to IPList instances
    - extract_client_ip: Extract client IP from request
    - check_lists: Check if IP is in allow/deny lists
"""

from .lists import (
    FileBackedIPList,
    IPList,
    URLBackedIPList,
    check_lists,
    extract_client_ip,
    parse_ip_list,
)

__all__ = [
    "IPList",
    "FileBackedIPList",
    "URLBackedIPList",
    "parse_ip_list",
    "extract_client_ip",
    "check_lists",
]
