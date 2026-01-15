import argparse
import sys
from typing import Dict

import requests

# Default to 8002 if not provided (legacy default)
DEFAULT_URL = "http://localhost:8002"


class Tester:
    def __init__(self, base_url: str = None):
        self.base_url = base_url or DEFAULT_URL
        self.session = requests.Session()

    def check_rate_limit(
        self,
        endpoint: str,
        limit: int,
        period_desc: str,
        expected_status: int = 429,
        headers: Dict = None,
        params: Dict = None,
        check_headers: bool = True,
    ):
        """
        Verifies that an endpoint allows 'limit' requests and blocks the next one.
        """
        url = f"{self.base_url}{endpoint}"
        print(f"Testing {endpoint} (Limit: {limit}/{period_desc})...")

        # Reset session to ensure clean state (though server-side state persists)
        # For IP-based limits, we are the same IP.

        # 1. Consume the limit
        for i in range(limit):
            response = self.session.get(url, headers=headers, params=params)
            if response.status_code != 200:
                print(
                    f"  [FAIL] Request {i+1}/{limit} failed with status {response.status_code}: {response.text}"
                )
                return False

            # Verify headers on allowed requests
            if check_headers:
                if (
                    "X-RateLimit-Limit" not in response.headers
                    or "X-RateLimit-Remaining" not in response.headers
                ):
                    print(
                        f"  [FAIL] Missing RateLimit headers on allowed request {i+1}"
                    )
                    return False

            print(f"  [PASS] Request {i+1}/{limit} allowed.")

        # 2. Verify blocking
        response = self.session.get(url, headers=headers, params=params)
        if response.status_code == expected_status:
            print(
                f"  [PASS] Request {limit+1} blocked with status {response.status_code}."
            )
            # Verify headers on blocked requests
            if check_headers:
                if (
                    "X-RateLimit-Retry-After" not in response.headers
                    and "Retry-After" not in response.headers
                ):
                    print("  [WARN] Missing Retry-After header on blocked request")
            return True
        else:
            print(
                f"  [FAIL] Request {limit+1} NOT blocked. Status: {response.status_code}, Body: {response.text}"
            )
            return False

    def login(self, username, password):
        login_url = f"{self.base_url}/admin/login/"
        # Get CSRF token
        resp_get = self.session.get(login_url)
        if resp_get.status_code != 200:
            print(
                f"  [FAIL] Could not fetch login page. Status: {resp_get.status_code}"
            )
            return False

        if "csrftoken" in self.session.cookies:
            csrftoken = self.session.cookies["csrftoken"]
        else:
            print("  [FAIL] No CSRF token found in cookies.")
            return False

        login_data = {
            "username": username,
            "password": password,
            "csrfmiddlewaretoken": csrftoken,
            "next": "/admin/",
        }
        resp = self.session.post(
            login_url, data=login_data, headers={"Referer": login_url}
        )

        # Admin login redirects on success
        if resp.status_code in (200, 302) and "sessionid" in self.session.cookies:
            print(f"  [PASS] Logged in as {username}")
            return True
        else:
            print(f"  [FAIL] Login failed for {username}. Status: {resp.status_code}")
            # Print a snippet of the response to debug
            print(f"  [DEBUG] Response snippet: {resp.text[:500]}")
            return False

    def run_all(self):
        results = []

        print("=== Starting Verification Scenarios ===")

        # Test A: Algorithms
        # algo_fixed: 5/m
        results.append(self.check_rate_limit("/algo/fixed/", 5, "m"))

        # algo_sliding: 5/m
        # Note: Sliding window might behave differently depending on implementation details,
        # but for a fresh start, it should allow 5 and block 6th.
        results.append(self.check_rate_limit("/algo/sliding/", 5, "m"))

        # algo_token: 5/m
        results.append(self.check_rate_limit("/algo/token/", 5, "m"))

        # algo_async: 5/m
        print("Testing /algo/async/ (Async)...")
        results.append(self.check_rate_limit("/algo/async/", 5, "m"))

        # Test B: Keys
        # key_ip: 5/m (Already implicitly tested above, but good to be explicit)
        results.append(self.check_rate_limit("/key/ip/", 5, "m"))

        # key_header: 5/m (x-api-key)
        results.append(
            self.check_rate_limit(
                "/key/header/", 5, "m", headers={"x-api-key": "test-key-1"}
            )
        )

        # key_param: 5/m (tenant_id)
        results.append(
            self.check_rate_limit(
                "/key/param/", 5, "m", params={"tenant_id": "tenant-1"}
            )
        )

        # key_custom: 5/m
        results.append(self.check_rate_limit("/key/custom/", 5, "m"))

        # key_user: 5/m (Authenticated)
        print("Testing /key/user/ (Authenticated)...")
        if self.login("testuser", "password"):
            results.append(self.check_rate_limit("/key/user/", 5, "m"))
        else:
            print("  [SKIP] Skipping /key/user/ test due to login failure.")
            results.append(False)

        # Test C: Options
        # opt_block_false: 5/m, block=False
        # Should allow > 5 requests, but return 'limited': True in body
        print("Testing /opt/block_false/ (Limit: 5/m, block=False)...")
        url = f"{self.base_url}/opt/block_false/"
        success = True
        for i in range(6):
            resp = self.session.get(url)
            try:
                data = resp.json()
            except Exception:
                print(
                    f"  [FAIL] Request {i+1} returned invalid JSON. Status: {resp.status_code}"
                )
                with open("error_response.html", "w") as f:
                    f.write(resp.text)
                print("  Saved response body to error_response.html")
                success = False
                break

            if i < 5:
                if data.get("limited") is True:
                    print(f"  [FAIL] Request {i+1} marked as limited prematurely.")
                    success = False
            else:
                if data.get("limited") is True:
                    print(
                        f"  [PASS] Request {i+1} correctly marked as limited (but allowed)."
                    )
                else:
                    print(f"  [FAIL] Request {i+1} NOT marked as limited.")
                    success = False
        results.append(success)

        # Test Shared Group
        print("Testing Shared Group (/opt/group/a/ and /opt/group/b/)...")
        # Consume 5 on A
        url_a = f"{self.base_url}/opt/group/a/"
        for i in range(5):
            self.session.get(url_a)

        # Check B (should be blocked)
        url_b = f"{self.base_url}/opt/group/b/"
        resp = self.session.get(url_b)
        if resp.status_code == 429:
            print("  [PASS] Shared group limit enforced.")
            results.append(True)
        else:
            print(
                f"  [FAIL] Shared group limit NOT enforced. Status: {resp.status_code}"
            )
            results.append(False)

        # Test Method Specific
        print("Testing Method Specific (/opt/methods/)...")
        url_m = f"{self.base_url}/opt/methods/"
        # GET should be unlimited (try 10)
        get_failed = False
        for i in range(10):
            if self.session.get(url_m).status_code != 200:
                get_failed = True
                break

        if get_failed:
            print("  [FAIL] GET requests were limited.")
            results.append(False)
        else:
            print("  [PASS] GET requests allowed.")
            # POST should be limited to 5
            # Consume 5
            for i in range(5):
                self.session.post(url_m)

            # 6th should fail
            if self.session.post(url_m).status_code == 429:
                print("  [PASS] POST requests limited.")
                results.append(True)
            else:
                print("  [FAIL] POST requests NOT limited.")
                results.append(False)

        # Test D: Frameworks
        # DRF APIView
        results.append(self.check_rate_limit("/drf/apiview/", 5, "m"))

        # DRF ViewSet (list action)
        results.append(self.check_rate_limit("/drf/viewset/", 5, "m"))

        # Async Middleware Test
        print("Testing /middleware/async/ (Async Middleware)...")
        results.append(self.check_rate_limit("/middleware/async/", 5, "m"))

        # Summary
        print("\n=== Test Summary ===")
        passed = results.count(True)
        total = len(results)
        print(f"Passed: {passed}/{total}")

        if passed == total:
            sys.exit(0)
        else:
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run rate limit verification scenarios"
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Base URL of the server (e.g., http://localhost:8000)",
    )
    args = parser.parse_args()

    # Wait for server to be ready (manual step usually, but we can add a retry loop)
    tester = Tester(base_url=args.url)
    try:
        requests.get(tester.base_url)
    except requests.exceptions.ConnectionError:
        print(f"Server not running at {tester.base_url}. Please start it first.")
        sys.exit(1)

    tester.run_all()
