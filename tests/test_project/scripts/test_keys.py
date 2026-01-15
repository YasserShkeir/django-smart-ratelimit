import os
import sys

# Add parent directory to path to import verify_scenarios
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from verify_scenarios import Tester


def test_ip_key(base_url):
    tester = Tester(base_url)
    print(f"\n--- Testing IP Key ({base_url}) ---")
    return tester.check_rate_limit("/key/ip/", 5, "minute")


def test_header_key(base_url):
    tester = Tester(base_url)
    print(f"\n--- Testing Header Key ({base_url}) ---")

    # User A (Key: Alpha)
    print("  User A (Alpha)...")
    if not tester.check_rate_limit(
        "/key/header/", 5, "minute", headers={"X-API-KEY": "Alpha"}
    ):
        return False

    # User B (Key: Beta) - Should be fresh
    print("  User B (Beta) - Should be unaffected...")
    resp = tester.session.get(f"{base_url}/key/header/", headers={"X-API-KEY": "Beta"})
    if resp.status_code != 200:
        print(f"  [FAIL] Isolation failed. User B blocked: {resp.status_code}")
        return False
    print("  [PASS] User B allowed (Isolation verify)")
    return True


def test_param_key(base_url):
    tester = Tester(base_url)
    print(f"\n--- Testing Param Key ({base_url}) ---")

    # Tenant 1
    print("  Tenant 1...")
    if not tester.check_rate_limit(
        "/key/param/", 5, "minute", params={"tenant_id": "1"}
    ):
        return False

    # Tenant 2 - Should be fresh
    print("  Tenant 2 - Should be unaffected...")
    resp = tester.session.get(f"{base_url}/key/param/", params={"tenant_id": "2"})
    if resp.status_code != 200:
        print(f"  [FAIL] Isolation failed. Tenant 2 blocked: {resp.status_code}")
        return False
    print("  [PASS] Tenant 2 allowed (Isolation verify)")
    return True


def run_suite(base_url):
    results = [
        test_ip_key(base_url),
        test_header_key(base_url),
        test_param_key(base_url),
    ]
    return all(results)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8002")
    args = parser.parse_args()

    if run_suite(args.url):
        print("\nAll Key Tests Passed!")
        sys.exit(0)
    else:
        print("\nSome Key Tests Failed.")
        sys.exit(1)
