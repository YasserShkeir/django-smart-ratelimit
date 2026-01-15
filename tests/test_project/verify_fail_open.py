import sys

import requests

BASE_URL = "http://localhost:8003"


def test_fail_open(expect_success: bool):
    url = f"{BASE_URL}/infra/fail-open/"
    print(f"Testing Fail-Open behavior at {url}...")
    print(f"Expect Success (Fail Open): {expect_success}")

    try:
        response = requests.get(url, timeout=5)
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")

        if expect_success:
            if response.status_code == 200:
                print("[PASS] Request allowed (Fail Open).")
                return True
            else:
                print(f"[FAIL] Expected 200, got {response.status_code}")
                return False
        else:
            # Expecting failure (500) because fail_open=False and backend is down
            if response.status_code == 500:
                print("[PASS] Request failed as expected (Fail Closed).")
                return True
            elif response.status_code == 200:
                print("[FAIL] Request allowed but expected failure (Fail Closed).")
                return False
            else:
                print(f"[FAIL] Unexpected status {response.status_code}")
                return False

    except requests.exceptions.RequestException as e:
        if not expect_success:
            print(f"[PASS] Request failed with exception: {e}")
            return True
        print(f"[FAIL] Request exception: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python verify_fail_open.py <true|false>")
        sys.exit(1)

    expect_success = sys.argv[1].lower() == "true"
    if test_fail_open(expect_success):
        sys.exit(0)
    else:
        sys.exit(1)
