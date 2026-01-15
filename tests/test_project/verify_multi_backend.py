import sys

import requests

BASE_URL = "http://localhost:8004"


def test_multi_backend():
    print(f"Testing Multi-Backend Failover at {BASE_URL}...")

    # We expect the primary (Redis) to fail (configured to wrong port)
    # and secondary (Memory) to take over.

    url = f"{BASE_URL}/algo/fixed/"

    # 1. Consume limit (5/m)
    print("Consuming limit...")
    for i in range(5):
        try:
            resp = requests.get(url)
            if resp.status_code != 200:
                print(f"[FAIL] Request {i+1} failed with status {resp.status_code}")
                return False
            print(f"  Request {i+1} allowed.")
        except requests.exceptions.RequestException as e:
            print(f"[FAIL] Request {i+1} exception: {e}")
            return False

    # 2. Verify blocking (6th request)
    print("Verifying blocking...")
    resp = requests.get(url)
    if resp.status_code == 429:
        print("[PASS] Request 6 blocked (Rate Limit enforced by secondary backend).")
        return True
    else:
        print(f"[FAIL] Request 6 NOT blocked. Status: {resp.status_code}")
        return False


if __name__ == "__main__":
    if test_multi_backend():
        sys.exit(0)
    else:
        sys.exit(1)
