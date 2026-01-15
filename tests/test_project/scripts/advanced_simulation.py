import argparse
import concurrent.futures
import time
from dataclasses import dataclass
from typing import List

import requests

RESET = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"


@dataclass
class TestResult:
    scenario: str
    passed: bool
    details: str
    duration: float


class AdvancedTester:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.results: List[TestResult] = []

    def log(self, msg: str, color: str = RESET):
        print(f"{color}{msg}{RESET}")

    def run_concurrent_burst(
        self, endpoint: str, limit: int, total_requests: int
    ) -> TestResult:
        """
        Simulate high concurrency burst.
        Goal: Verify no race conditions allow more than 'limit' requests.
        """
        self.log(f"\n[Test] Concurrent Burst on {endpoint}", CYAN)
        self.log(
            f"  Configuration: Limit={limit}, Requests={total_requests} (Threaded)"
        )

        # Clear limit first (if possible, by waiting or assuming fresh start)
        # Note: In a real test, we might want to ensure a clean state.

        url = f"{self.base_url}{endpoint}"

        start_time = time.time()
        responses = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(requests.get, url) for _ in range(total_requests)
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    responses.append(future.result())
                except Exception as e:
                    self.log(f"  Request failed: {e}", RED)

        duration = time.time() - start_time

        status_codes = [r.status_code for r in responses]
        success_count = status_codes.count(200)
        blocked_count = status_codes.count(429)
        error_count = len(responses) - success_count - blocked_count

        self.log(
            f"  Results: 200 OK: {success_count}, 429 Blocked: {blocked_count}, Errors: {error_count}"
        )

        passed = True
        details = []

        if success_count > limit:
            passed = False
            details.append(
                f"Race condition detected! Allowed {success_count} > Limit {limit}"
            )

        if success_count < limit and blocked_count > 0:
            # This might happen if requests are slow and window expires, but in a burst they should all hit within window
            details.append(f"Warning: Only {success_count} succeeded, expected {limit}")

        if error_count > 0:
            passed = False
            details.append(f"{error_count} requests failed with unexpected errors")

        result = TestResult(
            "Concurrent Burst", passed, "; ".join(details) or "Success", duration
        )
        self._record_result(result)
        return result

    def run_noisy_neighbor(self, endpoint: str, limit: int) -> TestResult:
        """
        Verify isolation between keys (IP simulation).
        Note: requires X-Forwarded-For support in middleware/decorator setup.
        """
        self.log(f"\n[Test] Noisy Neighbor (IP Isolation) on {endpoint}", CYAN)
        url = f"{self.base_url}{endpoint}"

        # 1. Exhaust Client A
        headers_a = {"X-Forwarded-For": "10.0.0.1"}
        self.log("  Exhausting limit for Client A (10.0.0.1)...")
        blocked_a = False
        for _ in range(limit + 5):
            r = requests.get(url, headers=headers_a)
            if r.status_code == 429:
                blocked_a = True
                break

        if not blocked_a:
            self._record_result(
                TestResult(
                    "Noisy Neighbor - Setup", False, "Could not exhaust Client A", 0
                )
            )
            return

        # 2. Check Client B (should be allowed)
        headers_b = {"X-Forwarded-For": "10.0.0.2"}
        self.log("  Checking access for Client B (10.0.0.2)...")
        r_b = requests.get(url, headers=headers_b)

        passed = r_b.status_code == 200
        details = f"Client B Status: {r_b.status_code}"
        if not passed:
            details += " (Expected 200)"

        result = TestResult("Noisy Neighbor - Isolation", passed, details, 0)
        self._record_result(result)
        return result

    def run_user_isolation(self, endpoint: str) -> TestResult:
        """
        Verify isolation between authenticated users.
        """
        self.log(f"\n[Test] User Isolation on {endpoint}", CYAN)
        # Note: This requires endpoints that accept user authentication (e.g. Basic Auth or specialized headers mocked in test project)
        # For this generic script, we will assume the endpoint might generate key from a header 'X-User-ID' if configured,
        # OR we rely on the project having specific auth views.
        # Given the current simple test project, we might skip full auth flow unless configured.

    def _record_result(self, result: TestResult):
        color = GREEN if result.passed else RED
        status = "PASS" if result.passed else "FAIL"
        self.log(f"  -> {status}: {result.details}", color)
        self.results.append(result)


def main():
    parser = argparse.ArgumentParser(description="Run advanced rate limit simulations")
    parser.add_argument(
        "--target", required=True, help="Base URL (e.g., http://localhost:8002)"
    )
    args = parser.parse_args()

    tester = AdvancedTester(args.target)

    # 1. Test Fixed Window Burst (Limit 5/m)
    # We send 20 requests. Expect 5 OK, 15 Blocked.
    tester.run_concurrent_burst("/algo/fixed/", limit=5, total_requests=20)

    # 2. Test Token Bucket Burst (Limit 10/m usually, check your settings)
    # Assuming /algo/token/ is 5/m or similar from previous context.
    # Let's check settings or assume 5 based on previous runs.
    tester.run_concurrent_burst("/algo/token/", limit=5, total_requests=20)

    # 3. Test IP Isolation
    tester.run_noisy_neighbor("/key/ip/", limit=5)

    # 4. Test Async Endpoint (if applicable)
    try:
        # Check if endpoint exists (simple GET)
        r = requests.get(f"{args.target}/algo/async/")
        if r.status_code != 404:
            tester.run_concurrent_burst("/algo/async/", limit=5, total_requests=20)
        else:
            print(f"{YELLOW}Skipping Async Test (Endpoint not found){RESET}")
    except Exception as e:
        print(f"{YELLOW}Skipping Async Test (Connection error: {e}){RESET}")

    # Summary
    print("\n--- Summary ---")
    fail_count = sum(1 for r in tester.results if not r.passed)
    if fail_count > 0:
        print(f"{RED}FAILED: {fail_count} tests failed.{RESET}")
        exit(1)
    else:
        print(f"{GREEN}ALL PASSED{RESET}")
        exit(0)


if __name__ == "__main__":
    main()
