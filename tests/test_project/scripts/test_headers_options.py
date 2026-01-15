import os
import sys

import requests

# Add parent directory to path to import verify_scenarios
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from verify_scenarios import Tester


def test_headers_existence(base_url):
    print(f"\n--- Testing Headers Existence ({base_url}) ---")
    url = f"{base_url}/algo/fixed/"

    # Make one request
    resp = requests.get(url)

    headers = resp.headers
    print(f"  Headers received: {list(headers.keys())}")

    required = ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"]
    missing = [h for h in required if h not in headers]

    if missing:
        print(f"  [FAIL] Missing headers: {missing}")
        return False

    print("  [PASS] All rate limit headers present")
    return True


def test_headers_logic(base_url):
    print(f"\n--- Testing Headers Logic ({base_url}) ---")
    # Use a fresh key to ensure counters are clean
    # Since we can't easily change the IP of the container runner,
    # we'll use a specific endpoint that relies on a unique key or just consume the sliding window one

    # We will use the 'seconds' endpoint as it's quick to reset if needed,
    # or actually let's use the 'fixed' window one but we need to wait for reset?
    # Better: Use the /key/custom/ endpoint which isn't used by other tests aggressively?
    # Actually, the 'verify_scenarios' runs sequentially, so we might have consumed some.

    # Let's use /key/header/ with a unique key for this test
    url = f"{base_url}/key/header/"
    unique_header = {"X-API-KEY": "headers-test-key"}

    # 1. First request
    resp = requests.get(url, headers=unique_header)
    limit = int(resp.headers.get("X-RateLimit-Limit", -1))
    remaining = int(resp.headers.get("X-RateLimit-Remaining", -1))

    print(f"  Request 1: Limit={limit}, Remaining={remaining}")

    if limit != 5:
        print(f"  [FAIL] Expected Limit=5, got {limit}")
        return False

    # Remaining should be 4 (5-1)
    if remaining != 4:
        # Note: If counters are shared and another test used this, this might fail.
        # But we used a unique API key, so it should be fresh.
        print(f"  [FAIL] Expected Remaining=4, got {remaining}")
        return False

    # 2. Second request
    resp = requests.get(url, headers=unique_header)
    remaining_2 = int(resp.headers.get("X-RateLimit-Remaining", -1))

    print(f"  Request 2: Remaining={remaining_2}")

    if remaining_2 != 3:
        print(f"  [FAIL] Expected Remaining=3, got {remaining_2}")
        return False

    print("  [PASS] Headers logic (decrementing) verified")
    return True


def test_block_false(base_url):
    print(f"\n--- Testing Block=False ({base_url}) ---")
    tester = Tester(base_url)

    # Endpoint: /opt/block_false/ (5/m)
    # We expect 6 requests to all yield 200 OK
    # But the 6th response JSON should have "limited": true

    url = f"{base_url}/opt/block_false/"

    for i in range(5):
        resp = tester.session.get(url)
        if resp.status_code != 200:
            print(f"  [FAIL] Request {i+1} failed with {resp.status_code}")
            return False
        data = resp.json()
        if data.get("limited") is True:
            print(f"  [FAIL] Request {i+1} marked as limited prematurely")
            return False

    print("  [PASS] First 5 requests allowed and not marked limited")

    # 6th Request
    resp = tester.session.get(url)
    if resp.status_code != 200:
        print(f"  [FAIL] 6th request blocked with {resp.status_code} (Expected 200)")
        return False

    data = resp.json()
    if data.get("limited") is not True:
        print(f"  [FAIL] 6th request NOT marked as limited in body: {data}")
        return False

    print("  [PASS] 6th request allowed (200) but marked as limited")
    return True


def test_skip_if(base_url):
    print(f"\n--- Testing Skip_if ({base_url}) ---")

    # URL: /opt/skip/ (Limit: 5/m)
    # Condition: skip_if=is_admin (checks request.user.is_staff)
    # Since we are anonymous, is_staff=False, so Rate Limit APPLIES.

    # 1. Anonymous - Should be limited
    # We won't consume all 5, just verify the header decreases?
    # Actually, verify that we CAN consume all 5 and get blocked on 6th?
    # No, let's verify scenarios described in plan:
    # "Create condition... Verify rate limit counts do not increase".

    # We need to simulate the implementation where skip_if=True.
    # We don't have login easily here without setting up users.
    # But /opt/methods/ skips if method != POST.
    # WAIT! The view says: skip_if=lambda r: r.method != "POST"
    # So if method is GET, it skips?
    # Let's check logic: method=="GET" != "POST" -> True -> SKIPPED.
    # So GET requests should NOT be limited.

    url = f"{base_url}/opt/methods/"

    # Ensure headers are present or absent?
    # If skipped, does the middleware/decorator check run?
    # Usually: if skipped, no key generated, no counting.
    # So headers might be missing, OR headers say "Limit: X, Remaining: X" (unchanged).
    # Smart Ratelimit usually bypasses logic completely.

    print("  Sending 10 GET requests (Skip condition met)...")
    for i in range(10):
        resp = requests.get(url)
        if resp.status_code == 429:
            print("  [FAIL] Blocked on skipped request!")
            return False
        # Verify headers logic - Remaining should NOT decrease if we were counting correctly
        # But if it skips, maybe headers are not added?
        # Let's see behavior.

    print("  [PASS] 10 skipped requests allowed (did not block)")

    # Now try method that is NOT skipped (POST)
    # skip_if = lambda r: r.method != "POST"
    # If we POST, condition is False -> NOT skipped -> Limited (5/m).

    print("  Sending 6 POST requests (Limit: 5/m)...")
    blocked = False
    for i in range(6):
        resp = requests.post(url)
        if resp.status_code == 429:
            if i == 5:
                # 6th request blocked
                blocked = True
            else:
                print(f"  [FAIL] Prematurely blocked on POST {i+1}")
                return False

    if blocked:
        print("  [PASS] POST requests correctly limited")
        return True
    else:
        print("  [FAIL] Failed to block 6th POST request")
        return False


def test_groups(base_url):
    print(f"\n--- Testing Shared Groups ({base_url}) ---")
    tester = Tester(base_url)

    # A and B share key "shared_group" (5/m)

    # Consume 5 on A
    for i in range(5):
        resp = tester.session.get(f"{base_url}/opt/group/a/")
        if resp.status_code != 200:
            print(f"  [FAIL] Request {i+1} to Group A failed")
            return False

    # Try B -> Should be blocked
    resp = tester.session.get(f"{base_url}/opt/group/b/")
    if resp.status_code != 429:
        print(
            f"  [FAIL] Request to Group B allowed ({resp.status_code}) after exhausting Group A"
        )
        return False

    print("  [PASS] Group limit enforced across different endpoints")
    return True


def run_suite(base_url):
    results = [
        test_headers_existence(base_url),
        test_headers_logic(base_url),
        test_block_false(base_url),
        test_skip_if(base_url),
        test_groups(base_url),
    ]
    return all(results)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8002")
    args = parser.parse_args()

    if run_suite(args.url):
        print("\nAll Headers & Options Tests Passed!")
        sys.exit(0)
    else:
        print("\nSome Tests Failed.")
        sys.exit(1)
