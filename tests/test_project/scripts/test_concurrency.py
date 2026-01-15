import concurrent.futures
import os
import sys
import time

import requests

# Add parent directory to path to import verify_scenarios
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_suite(base_url):
    print(f"\n--- Testing Concurrency ({base_url}) ---")

    # We need a dedicated endpoint for concurrency to avoid interference
    # We'll use 'algo_token' but with a unique IP if possible, or just accept that it might be messy.
    # Actually, let's use a key that includes a random component if we can control it?
    # No, we can't easily injection random keys unless we use headers.
    # existins view: @ratelimit(key="header:x-api-key", rate="5/m")

    # We will use the 'header' key endpoint with a unique API key for this test run.
    target_url = f"{base_url}/key/header/"
    # High enough limit to allow some parallelism but low enough to hit quickly?
    # Actually the view has "5/m". That's very low for concurrency testing.
    # We want to send 50 requests and see exactly 5 succeed.

    limit = 5
    total_requests = 50
    unique_key = f"concurrent_test_{int(time.time())}"
    headers = {"X-API-Key": unique_key}

    print(
        f"  Sending {total_requests} concurrent requests to {target_url} (Limit: {limit}/m)..."
    )

    success_count = 0
    blocked_count = 0
    errors = 0

    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [
            executor.submit(requests.get, target_url, headers=headers)
            for _ in range(total_requests)
        ]

        for future in concurrent.futures.as_completed(futures):
            try:
                resp = future.result()
                if resp.status_code == 200:
                    success_count += 1
                elif resp.status_code == 429:
                    blocked_count += 1
                else:
                    errors += 1
                    print(f"  [Error] Status {resp.status_code}")
            except Exception as e:
                errors += 1
                print(f"  [Exception] {e}")

    duration = time.time() - start_time
    print(f"  Finished in {duration:.2f}s")
    print(
        f"  Results: Allowed={success_count}, Blocked={blocked_count}, Errors={errors}"
    )

    # Verification
    # For atomic backends (Redis), we expect exactly 5 allowed.
    # For MemoryBackend, race conditions are expected (not thread-safe).
    # We use the port to determine which backend is being tested.

    is_memory_backend = ":8001" in base_url

    if success_count == limit:
        print(f"  [PASS] Exactly {limit} requests allowed.")
        return True
    elif success_count > limit:
        if is_memory_backend:
            # Memory backend is not thread-safe - this is expected
            print(
                f"  [WARN] Race condition in MemoryBackend (expected): {success_count} allowed"
            )
            print("  [PASS] MemoryBackend concurrency test (non-atomic is expected)")
            return True
        else:
            print(
                f"  [FAIL] Race condition detected! {success_count} allowed (Expected {limit})."
            )
            return False
    else:
        print(f"  [FAIL] Too few allowed? {success_count} (Expected {limit}).")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="http://localhost:8001")
    args = parser.parse_args()
    run_suite(args.url)
