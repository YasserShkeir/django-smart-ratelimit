import os
import sys
import time

# Add parent directory to path to import verify_scenarios
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from verify_scenarios import Tester


def test_fixed_window(base_url):
    tester = Tester(base_url)
    print(f"\n--- Testing Fixed Window ({base_url}) ---")
    # Limit: 5/m
    return tester.check_rate_limit("/algo/fixed/", 5, "minute")


def test_sliding_window(base_url):
    tester = Tester(base_url)
    print(f"\n--- Testing Sliding Window ({base_url}) ---")
    # Limit: 5/m
    return tester.check_rate_limit("/algo/sliding/", 5, "minute")


def test_token_bucket(base_url):
    tester = Tester(base_url)
    print(f"\n--- Testing Token Bucket ({base_url}) ---")
    # Limit: 5/m
    return tester.check_rate_limit("/algo/token/", 5, "minute")


def test_seconds(base_url):
    tester = Tester(base_url)
    print(f"\n--- Testing Seconds Precision ({base_url}) ---")
    # Limit: 1/s
    # We hit once (pass), then immediately again (block), then wait 1.1s, then hit (pass)

    url = f"{base_url}/algo/seconds/"

    # 1. Pass
    resp = tester.session.get(url)
    if resp.status_code != 200:
        print(f"  [FAIL] Initial request failed: {resp.status_code}")
        return False
    print("  [PASS] Request 1 allowed")

    # 2. Block (immediate)
    resp = tester.session.get(url)
    if resp.status_code != 429:
        print(f"  [FAIL] Immediate second request passed: {resp.status_code}")
        return False
    print("  [PASS] Request 2 blocked")

    # 3. Wait and Pass
    time.sleep(1.1)
    resp = tester.session.get(url)
    if resp.status_code != 200:
        print(f"  [FAIL] Request after wait failed: {resp.status_code}")
        return False
    print("  [PASS] Request 3 allowed after wait")
    return True


def run_suite(base_url):
    results = [
        test_fixed_window(base_url),
        test_sliding_window(base_url),
        test_token_bucket(base_url),
        test_seconds(base_url),
    ]
    return all(results)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8002")
    args = parser.parse_args()

    if run_suite(args.url):
        print("\nAll Algorithm Tests Passed!")
        sys.exit(0)
    else:
        print("\nSome Algorithm Tests Failed.")
        sys.exit(1)
