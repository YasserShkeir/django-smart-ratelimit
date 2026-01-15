"""
Test suite for @ratelimit_batch decorator.
Validates that batch rate limiting correctly enforces multiple limits per request.
"""

import os
import sys
import time

import requests

# Add parent directory to path to import verify_scenarios
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_batch_basic(base_url):
    """Test that @ratelimit_batch enforces the first limit to be hit."""
    print(f"\n--- Testing @ratelimit_batch Basic ({base_url}) ---")

    # The batch endpoint has:
    # - IP limit: 5/m
    # - User limit: 10/h
    # Without authentication, the IP limit (5/m) should be hit first.

    url = f"{base_url}/algo/batch/"
    f"batch_test_{int(time.time())}"
    headers = {"X-Forwarded-For": f"192.168.{int(time.time()) % 256}.1"}

    print("  Testing IP limit (5/m) triggers first...")

    for i in range(5):
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"  [FAIL] Request {i+1}/5 failed with status {resp.status_code}")
            return False
        print(f"  [PASS] Request {i+1}/5 allowed")

    # 6th request should be blocked
    resp = requests.get(url, headers=headers)
    if resp.status_code != 429:
        print(f"  [FAIL] Request 6 not blocked! Status: {resp.status_code}")
        return False

    print("  [PASS] Request 6 blocked (429) - Batch limiting works")
    return True


def test_batch_isolation(base_url):
    """Test that different IPs are isolated in batch limiting."""
    print(f"\n--- Testing @ratelimit_batch Isolation ({base_url}) ---")

    url = f"{base_url}/algo/batch/"

    # IP A - Exhaust limit
    headers_a = {"X-Forwarded-For": f"10.0.0.{int(time.time()) % 256}"}
    print("  Exhausting limit for IP A...")

    for i in range(5):
        resp = requests.get(url, headers=headers_a)
        if resp.status_code != 200:
            print(f"  [FAIL] IP A request {i+1} failed")
            return False

    # IP B - Should still be allowed
    headers_b = {"X-Forwarded-For": f"10.0.1.{int(time.time()) % 256}"}
    print("  Testing IP B access...")

    resp = requests.get(url, headers=headers_b)
    if resp.status_code != 200:
        print(f"  [FAIL] IP B blocked! Status: {resp.status_code}")
        return False

    print("  [PASS] IP B allowed - Isolation verified")
    return True


def run_suite(base_url):
    """Run all batch tests."""
    print(f"\nRunning Batch Decorator Tests for {base_url}")
    results = [
        test_batch_basic(base_url),
        test_batch_isolation(base_url),
    ]
    return all(results)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8002")
    args = parser.parse_args()

    if run_suite(args.url):
        print("\nAll Batch Tests Passed!")
        sys.exit(0)
    else:
        print("\nSome Batch Tests Failed.")
        sys.exit(1)
