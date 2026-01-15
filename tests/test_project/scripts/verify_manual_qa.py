import argparse
import re

import requests


def run_test(name):
    print(f"Testing {name}...")


def fail(msg):
    print(f"  [FAIL] {msg}")
    return False


def check(resp, expected_code, msg=""):
    if resp.status_code == expected_code:
        return True
    print(f"  [FAIL] {msg} Expected {expected_code}, got {resp.status_code}")
    if resp.status_code != 200:
        print(f"     Response: {resp.text[:200]}...")
    return False


def login(base_url, username, password):
    """
    Log in to Django Admin to get a session cookie.
    Returns a requests.Session object if successful.
    """
    s = requests.Session()
    login_url = f"{base_url}/admin/login/"

    # 1. GET login page to get CSRF cookie
    resp = s.get(login_url)
    if resp.status_code != 200:
        print(f"  [ERROR] Failed to fetch login page: {resp.status_code}")
        return None

    csrftoken = s.cookies.get("csrftoken")
    if not csrftoken:
        # Fallback: try to find it in the hidden input
        match = re.search(r'name="csrfmiddlewaretoken" value="(.+?)"', resp.text)
        if match:
            csrftoken = match.group(1)
        else:
            print("  [ERROR] Could not find CSRF token")
            return None

    # 2. POST credentials
    data = {
        "username": username,
        "password": password,
        "csrfmiddlewaretoken": csrftoken,
        "next": "/admin/",
    }
    headers = {"Referer": login_url}

    resp = s.post(login_url, data=data, headers=headers)

    # Check if login succeeded (admin usually redirects to /admin/ on success)
    if (
        resp.status_code == 302
        or resp.url.endswith("/admin/")
        or "Log out" in resp.text
    ):
        return s

    print(
        f"  [ERROR] Login failed for {username}. code={resp.status_code} url={resp.url}"
    )
    return None


def verify_user_key(base_url):
    print("\n--- Verifying User Key ---")
    url = f"{base_url}/key/user/"

    # Login User A
    print("  Logging in User A (testuser)...")
    session_a = login(base_url, "testuser", "password")
    if not session_a:
        return False

    # Login User B
    print("  Logging in User B (testuser2)...")
    session_b = login(base_url, "testuser2", "password")
    if not session_b:
        return False

    # User A: Consume 5 requests
    for i in range(5):
        resp = session_a.get(url)
        if not check(resp, 200, f"User A Request {i+1}"):
            return False

    # User A: 6th request -> Block
    resp = session_a.get(url)
    if not check(resp, 429, "User A 6th Request"):
        return False
    print("  [PASS] User A blocked after 5 requests")

    # User B: Should be allowed
    resp = session_b.get(url)
    if not check(resp, 200, "User B Request 1"):
        return False
    print("  [PASS] User B allowed (separate bucket)")
    return True


def verify_groups(base_url):
    print("\n--- Verifying Groups (Shared Limit) ---")
    url_a = f"{base_url}/opt/group/a/"
    url_b = f"{base_url}/opt/group/b/"

    # Hit A 3 times
    for i in range(3):
        resp = requests.get(url_a)
        if not check(resp, 200, f"Group A Request {i+1}"):
            return False

    # Hit B 2 times
    for i in range(2):
        resp = requests.get(url_b)
        if not check(resp, 200, f"Group B Request {i+1}"):
            return False

    # Hit A (Total 6) -> Block
    resp = requests.get(url_a)
    if not check(resp, 429, "Group A 6th Request (Shared)"):
        return False
    print("  [PASS] Group Limit Shared (Blocked after 5 total)")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://localhost:8002")
    args = parser.parse_args()

    try:
        if verify_user_key(args.target) and verify_groups(args.target):
            print("\n[SUCCESS] Manual Verification Passed")
        else:
            print("\n[FAILURE] Manual Verification Failed")
            exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        exit(1)
