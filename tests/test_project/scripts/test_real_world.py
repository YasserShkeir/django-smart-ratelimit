import os
import sys

import requests

# Add parent directory to path to import verify_scenarios
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from verify_scenarios import Tester


def test_login_brute_force(base_url):
    print(f"\n--- Testing Login Brute Force ({base_url}) ---")
    Tester(base_url)

    # Endpoint: /real_world/login/ (5/m)
    url = f"{base_url}/real_world/login/"

    print("  Simulating 5 failed login attempts...")
    for i in range(5):
        resp = requests.post(url)
        if resp.status_code != 401:
            print(f"  [FAIL] Expected 401, got {resp.status_code}")
            return False

    print("  Simulating 6th attempt (Attack)...")
    resp = requests.post(url)

    if resp.status_code == 429:
        print("  [PASS] Brute force attack blocked (429)")
        return True
    else:
        print(f"  [FAIL] Attack NOT blocked! Status: {resp.status_code}")
        return False


def test_api_tiering(base_url):
    print(f"\n--- Testing API Tiering ({base_url}) ---")

    # Endpoint: /real_world/tiering/
    # Basic Tier: 5/m (Default)
    # Premium Tier: 20/m (Header: X-User-Tier: premium)

    url = f"{base_url}/real_world/tiering/"

    # 1. Test Basic Tier
    print("  Testing Basic Tier (5/m)...")
    headers = {"X-User-Tier": "basic"}

    # Consume 5
    for i in range(5):
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"  [FAIL] Basic request {i+1} failed")
            return False

    # 6th should block
    resp = requests.get(url, headers=headers)
    if resp.status_code != 429:
        print(f"  [FAIL] Basic tier not limited correctly (Status: {resp.status_code})")
        return False
    print("  [PASS] Basic tier limited at 5 requests")

    # 2. Test Premium Tier
    print("  Testing Premium Tier (20/m)...")
    headers = {"X-User-Tier": "premium"}

    # Should allow > 5 requests. Let's try 10.
    for i in range(10):
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"  [FAIL] Premium request {i+1} failed (Status: {resp.status_code})")
            return False

    print("  [PASS] Premium tier allowed > 5 requests")
    return True


def test_expensive_search(base_url):
    print(f"\n--- Testing Expensive Search Isolation ({base_url}) ---")
    # Verify that blocking a specific expensive endpoint does NOT block cheap endpoints

    url_search = f"{base_url}/real_world/search/"  # 5/m
    url_dash = f"{base_url}/real_world/dashboard/"  # 100/m

    # 1. Exhaust Search Limit
    print("  Exhausting expensive search limit (5/m)...")
    for i in range(5):
        resp = requests.get(url_search)
        if resp.status_code != 200:
            print(f"  [FAIL] Search request {i+1} failed")
            return False

    # Verify Search is blocked
    resp = requests.get(url_search)
    if resp.status_code != 429:
        print(f"  [FAIL] Search not blocked (Status: {resp.status_code})")
        return False
    print("  [PASS] Search blocked correctly")

    # 2. Check Dashboard (Should still be allowed)
    print("  Checking Dashboard access (Should be allowed)...")
    resp = requests.get(url_dash)
    if resp.status_code == 200:
        print("  [PASS] Dashboard accessible (Resource isolation verified)")
        return True
    else:
        print(f"  [FAIL] Dashboard blocked! Status: {resp.status_code}")
        return False


def run_suite(base_url):
    print("\nRunning Real World Scenarios...")
    results = [
        test_login_brute_force(base_url),
        test_api_tiering(base_url),
        test_expensive_search(base_url),
    ]
    return all(results)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="http://localhost:8001")
    args = parser.parse_args()
    run_suite(args.url)
