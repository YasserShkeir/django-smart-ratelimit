import argparse

import requests


def check(resp, expected_code, msg=""):
    if resp.status_code == expected_code:
        print(f"  [PASS] {msg}")
        return True
    print(f"  [FAIL] {msg} Expected {expected_code}, got {resp.status_code}")
    print(f"         {resp.text[:100]}")
    return False


def verify_batch(base_url):
    print("\n--- Verifying @ratelimit_batch ---")
    url = f"{base_url}/algo/batch/"

    # Hit 5 times
    for i in range(5):
        resp = requests.get(url)
        if not check(resp, 200, f"Request {i+1}"):
            return False

    # 6th time -> Block
    resp = requests.get(url)
    if not check(resp, 429, "Request 6 (Should Block)"):
        return False
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://localhost:8002")
    args = parser.parse_args()

    if verify_batch(args.target):
        print("\n[SUCCESS] Batch Verification Passed")
        exit(0)
    else:
        print("\n[FAILURE] Batch Verification Failed")
        exit(1)
