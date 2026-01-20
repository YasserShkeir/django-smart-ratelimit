"""
Database Backend QA Tests (v2.0)

Tests for the DatabaseBackend with SQLite, PostgreSQL, and MySQL.
These tests run against the Docker containers defined in docker-compose.qa.yml.

Usage:
    # Test SQLite backend (port 8006)
    python test_database_backend.py --url http://localhost:8006

    # Test PostgreSQL backend (port 8007)
    python test_database_backend.py --url http://localhost:8007

    # Test MySQL backend (port 8008)
    python test_database_backend.py --url http://localhost:8008
"""

import argparse
import os
import sys

# Add parent directory to path to import verify_scenarios
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from verify_scenarios import Tester


def test_health_check(base_url):
    """Test database backend health check endpoint."""
    tester = Tester(base_url)
    print(f"\n--- Testing Database Health Check ({base_url}) ---")

    url = f"{base_url}/db/health/"
    resp = tester.session.get(url)

    if resp.status_code != 200:
        print(f"  [FAIL] Health check failed: {resp.status_code}")
        return False

    data = resp.json()
    if data.get("status") != "healthy":
        print(f"  [FAIL] Backend not healthy: {data}")
        return False

    print(f"  [PASS] Health check passed")
    print(f"         Database: {data.get('database_vendor', 'unknown')}")
    print(f"         Response time: {data.get('response_time', -1):.4f}s")
    return True


def test_fixed_window(base_url):
    """Test fixed window rate limiting with database backend."""
    tester = Tester(base_url)
    print(f"\n--- Testing Fixed Window ({base_url}) ---")
    return tester.check_rate_limit("/db/fixed/", 5, "minute")


def test_sliding_window(base_url):
    """Test sliding window rate limiting with database backend."""
    tester = Tester(base_url)
    print(f"\n--- Testing Sliding Window ({base_url}) ---")
    return tester.check_rate_limit("/db/sliding/", 5, "minute")


def test_token_bucket(base_url):
    """Test token bucket rate limiting with database backend."""
    tester = Tester(base_url)
    print(f"\n--- Testing Token Bucket ({base_url}) ---")
    return tester.check_rate_limit("/db/token/", 5, "minute")


def test_leaky_bucket(base_url):
    """Test leaky bucket rate limiting with database backend."""
    tester = Tester(base_url)
    print(f"\n--- Testing Leaky Bucket ({base_url}) ---")
    return tester.check_rate_limit("/db/leaky/", 5, "minute")


def test_stats(base_url):
    """Test database backend statistics endpoint."""
    tester = Tester(base_url)
    print(f"\n--- Testing Database Stats ({base_url}) ---")

    url = f"{base_url}/db/stats/"
    resp = tester.session.get(url)

    if resp.status_code != 200:
        print(f"  [FAIL] Stats endpoint failed: {resp.status_code}")
        return False

    data = resp.json()
    if data.get("status") != "ok":
        print(f"  [FAIL] Stats request failed: {data}")
        return False

    stats = data.get("stats", {})
    print(f"  [PASS] Stats retrieved successfully")
    print(f"         Active counters: {stats.get('active_counters', 0)}")
    print(f"         Token buckets: {stats.get('token_buckets', 0)}")
    print(f"         Leaky buckets: {stats.get('leaky_buckets', 0)}")
    print(f"         Total records: {stats.get('total_records', 0)}")
    return True


def test_cleanup(base_url):
    """Test database backend cleanup endpoint."""
    tester = Tester(base_url)
    print(f"\n--- Testing Database Cleanup ({base_url}) ---")

    url = f"{base_url}/db/cleanup/"
    resp = tester.session.get(url)

    if resp.status_code != 200:
        print(f"  [FAIL] Cleanup endpoint failed: {resp.status_code}")
        return False

    data = resp.json()
    if data.get("status") != "ok":
        print(f"  [FAIL] Cleanup request failed: {data}")
        return False

    cleanup = data.get("cleanup", {})
    print(f"  [PASS] Cleanup completed successfully")
    print(f"         Counters cleaned: {cleanup.get('counters', 0)}")
    print(f"         Entries cleaned: {cleanup.get('entries', 0)}")
    print(f"         Token buckets cleaned: {cleanup.get('token_buckets', 0)}")
    print(f"         Leaky buckets cleaned: {cleanup.get('leaky_buckets', 0)}")
    return True


def test_rate_limit_persistence(base_url):
    """Test that rate limits persist correctly in database.

    Note: This test verifies that stats show persisted counters.
    Since previous tests may have already hit rate limits, we check
    that the database has active records rather than trying to make
    new requests.
    """
    tester = Tester(base_url)
    print(f"\n--- Testing Rate Limit Persistence ({base_url}) ---")

    # Check stats - should show counters from previous tests
    stats_url = f"{base_url}/db/stats/"
    resp = tester.session.get(stats_url)

    if resp.status_code != 200:
        print(f"  [FAIL] Stats endpoint failed: {resp.status_code}")
        return False

    stats = resp.json().get("stats", {})
    total_records = stats.get("total_records", 0)
    active_counters = stats.get("active_counters", 0)

    if total_records > 0:
        print(f"  [PASS] Database has persisted records: {total_records} total")
        print(f"         Active counters: {active_counters}")
        print(f"         Token buckets: {stats.get('token_buckets', 0)}")
        print(f"         Leaky buckets: {stats.get('leaky_buckets', 0)}")
        print(f"         Sliding entries: {stats.get('sliding_entries', 0)}")
        return True
    else:
        print(f"  [FAIL] No persisted records found in database")
        return False


def test_concurrent_requests(base_url):
    """Test concurrent request handling (basic).

    This test verifies that the database backend handles concurrent requests
    without errors. We use the sliding window endpoint which creates individual
    entries, making concurrent access testing more meaningful.
    """
    import threading

    import requests

    print(f"\n--- Testing Concurrent Requests ({base_url}) ---")

    results = []
    errors = []
    lock = threading.Lock()

    def make_request():
        try:
            # Use a fresh session per thread to simulate different clients
            session = requests.Session()
            url = f"{base_url}/db/sliding/"
            resp = session.get(url)
            with lock:
                results.append(resp.status_code)
        except Exception as e:
            with lock:
                errors.append(str(e))

    # Create 10 threads
    threads = [threading.Thread(target=make_request) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Check for errors
    if errors:
        print(f"  [FAIL] Errors during concurrent requests: {errors[:3]}")
        return False

    count_200 = results.count(200)
    count_429 = results.count(429)

    print(f"  [INFO] Results: {count_200} allowed, {count_429} blocked")

    # Success if we got responses without errors - rate limiting behavior depends
    # on previous test state
    if len(results) == 10:
        print(
            f"  [PASS] All {len(results)} concurrent requests completed without errors"
        )
        return True
    else:
        print(f"  [FAIL] Only {len(results)}/10 requests completed")
        return False


def run_suite(base_url):
    """Run all database backend tests."""
    print(f"\n{'='*60}")
    print(f"Database Backend QA Test Suite")
    print(f"Target: {base_url}")
    print(f"{'='*60}")

    results = [
        ("Health Check", test_health_check(base_url)),
        ("Fixed Window", test_fixed_window(base_url)),
        ("Sliding Window", test_sliding_window(base_url)),
        ("Token Bucket", test_token_bucket(base_url)),
        ("Leaky Bucket", test_leaky_bucket(base_url)),
        ("Stats", test_stats(base_url)),
        ("Cleanup", test_cleanup(base_url)),
        ("Persistence", test_rate_limit_persistence(base_url)),
        ("Concurrent", test_concurrent_requests(base_url)),
    ]

    print(f"\n{'='*60}")
    print("Summary:")
    print(f"{'='*60}")

    passed = 0
    failed = 0
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Database Backend QA Tests")
    parser.add_argument(
        "--url",
        default="http://localhost:8006",
        help="Base URL of the test server (default: http://localhost:8006 for SQLite)",
    )
    args = parser.parse_args()

    success = run_suite(args.url)
    sys.exit(0 if success else 1)
