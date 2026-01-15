import argparse

import requests


def get_base_url():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://localhost:8000")
    parser.add_argument(
        "--async-only", action="store_true", help="Only run async tests"
    )
    args, _ = parser.parse_known_args()
    return args


ARGS = get_base_url()
BASE_URL = ARGS.target


def run_test(name, endpoint, limit, headers=None, reset_sleep=None, expect_block=True):
    print(f"Testing {name} ({endpoint})...")
    url = f"{BASE_URL}{endpoint}"

    # 1. Baseline: Hit up to limit
    for i in range(int(limit)):
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"  [FAIL] Request {i+1}/{limit} failed with {resp.status_code}")
            return False

    # 2. Verify Limit: Hit one more time
    resp = requests.get(url, headers=headers)

    if expect_block:
        if resp.status_code == 429:
            print("  [PASS] Rate limit enforced (429 Too Many Requests)")
            return True
        else:
            print(f"  [FAIL] Expected 429, got {resp.status_code}")
            return False
    else:
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("limited") is True:
                    print("  [PASS] Not blocked but marked as limited")
                    return True
            except:
                pass
            print("  [PASS] Exempt/Fail-Open (200 OK)")
            return True
        else:
            print(f"  [FAIL] Expected 200, got {resp.status_code}")
            return False


if __name__ == "__main__":
    print(f"Starting Verification Suite against {BASE_URL}...")

    if ARGS.async_only:
        run_test("Async Sliding Window", "/algo/async/", 5)
    else:
        # 3.2.1 Algorithms
        run_test("Fixed Window", "/algo/fixed/", 5)
        run_test("Sliding Window", "/algo/sliding/", 5)
        run_test("Token Bucket", "/algo/token/", 5)

        # 3.2.2 Keys
        run_test("IP Key A", "/key/ip/", 5, headers={"X-Forwarded-For": "10.0.0.1"})
        run_test("IP Key B", "/key/ip/", 5, headers={"X-Forwarded-For": "10.0.0.2"})

        # 3.2.3 Options
        run_test("Block False", "/opt/block_false/", 5, expect_block=False)

    print("Verification execution complete.")
