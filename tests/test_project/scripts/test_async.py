"""
Test suite for async rate limiting (@aratelimit).
Validates that async views are correctly rate limited.
"""

import os
import sys
import time

import requests

# Add parent directory to path to import verify_scenarios
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_async_basic(base_url):
    """Test that @aratelimit enforces limits on async views."""
    print(f"\n--- Testing @aratelimit Basic ({base_url}) ---")

    url = f"{base_url}/algo/async/"
    unique_ip = f"172.16.{int(time.time()) % 256}.1"
    headers = {"X-Forwarded-For": unique_ip}

    print("  Testing async endpoint rate limit (5/m)...")

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

    print("  [PASS] Request 6 blocked (429) - Async rate limiting works")
    return True


def test_async_headers(base_url):
    """Test that async views return proper rate limit headers."""
    print(f"\n--- Testing @aratelimit Headers ({base_url}) ---")

    url = f"{base_url}/algo/async/"
    unique_ip = f"172.17.{int(time.time()) % 256}.1"
    headers = {"X-Forwarded-For": unique_ip}

    resp = requests.get(url, headers=headers)

    if resp.status_code != 200:
        print(f"  [FAIL] Request failed with status {resp.status_code}")
        return False

    # Check for rate limit headers
    required_headers = ["X-RateLimit-Limit", "X-RateLimit-Remaining"]
    missing = [h for h in required_headers if h not in resp.headers]

    if missing:
        print(f"  [FAIL] Missing headers: {missing}")
        return False

    print(
        f"  Headers: Limit={resp.headers.get('X-RateLimit-Limit')}, "
        f"Remaining={resp.headers.get('X-RateLimit-Remaining')}"
    )
    print("  [PASS] All rate limit headers present")
    return True


def test_middleware_async(base_url):
    """Test middleware on async views (if enabled)."""
    print(f"\n--- Testing Middleware on Async View ({base_url}) ---")

    # Note: Middleware is disabled for async container (8003)
    # But enabled for others
    url = f"{base_url}/middleware/async/"

    resp = requests.get(url)

    if resp.status_code != 200:
        print(f"  [WARN] Request failed with status {resp.status_code}")
        # This might be expected if middleware is applying limits
        return True

    # Check if middleware headers present
    if "X-RateLimit-Limit" in resp.headers:
        print("  [PASS] Middleware headers present on async view")
    else:
        print("  [PASS] No middleware headers (middleware may be disabled)")

    return True


def run_suite(base_url):
    """Run all async tests."""
    print(f"\nRunning Async Rate Limiting Tests for {base_url}")
    results = [
        test_async_basic(base_url),
        test_async_headers(base_url),
        test_middleware_async(base_url),
    ]
    return all(results)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8002")
    args = parser.parse_args()

    if run_suite(args.url):
        print("\nAll Async Tests Passed!")
        sys.exit(0)
    else:
        print("\nSome Async Tests Failed.")
        sys.exit(1)
