#!/usr/bin/env python
"""
Run Database Backend QA Tests across all database types.

This script runs the database backend tests against:
- SQLite (port 8006)
- PostgreSQL (port 8007)
- MySQL (port 8008)

Prerequisites:
    docker-compose -f docker-compose.qa.yml up -d postgres mysql app-database-sqlite app-database-postgres app-database-mysql

Usage:
    python run_database_qa.py
    python run_database_qa.py --sqlite-only
    python run_database_qa.py --postgres-only
    python run_database_qa.py --mysql-only
"""

import argparse
import subprocess
import sys
import time

import requests

# Database backend configurations
BACKENDS = {
    "sqlite": {
        "name": "SQLite",
        "url": "http://localhost:8006",
        "container": "ratelimit-qa-database-sqlite",
    },
    "postgres": {
        "name": "PostgreSQL",
        "url": "http://localhost:8007",
        "container": "ratelimit-qa-database-postgres",
    },
    "mysql": {
        "name": "MySQL",
        "url": "http://localhost:8008",
        "container": "ratelimit-qa-database-mysql",
    },
}


def wait_for_backend(url, timeout=60):
    """Wait for a backend to become available."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{url}/db/health/", timeout=5)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def run_tests_for_backend(backend_key):
    """Run tests for a specific backend."""
    backend = BACKENDS[backend_key]
    print(f"\n{'='*60}")
    print(f"Testing {backend['name']} Backend")
    print(f"URL: {backend['url']}")
    print(f"{'='*60}")

    # Wait for backend to be ready
    print(f"Waiting for {backend['name']} to be ready...")
    if not wait_for_backend(backend["url"]):
        print(f"[FAIL] {backend['name']} did not become ready within timeout")
        return False

    print(f"{backend['name']} is ready!")

    # Run the test script
    result = subprocess.run(
        [sys.executable, "test_database_backend.py", "--url", backend["url"]],
        cwd=sys.path[0] or ".",
        capture_output=False,
    )

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Run Database Backend QA Tests")
    parser.add_argument("--sqlite-only", action="store_true", help="Test SQLite only")
    parser.add_argument(
        "--postgres-only", action="store_true", help="Test PostgreSQL only"
    )
    parser.add_argument("--mysql-only", action="store_true", help="Test MySQL only")
    args = parser.parse_args()

    # Determine which backends to test
    if args.sqlite_only:
        backends_to_test = ["sqlite"]
    elif args.postgres_only:
        backends_to_test = ["postgres"]
    elif args.mysql_only:
        backends_to_test = ["mysql"]
    else:
        backends_to_test = ["sqlite", "postgres", "mysql"]

    print("\n" + "=" * 60)
    print("Database Backend QA Test Runner")
    print("=" * 60)
    print(
        f"Testing backends: {', '.join(BACKENDS[b]['name'] for b in backends_to_test)}"
    )

    results = {}
    for backend_key in backends_to_test:
        try:
            results[backend_key] = run_tests_for_backend(backend_key)
        except Exception as e:
            print(f"[ERROR] Failed to test {BACKENDS[backend_key]['name']}: {e}")
            results[backend_key] = False

    # Print summary
    print("\n" + "=" * 60)
    print("Overall Summary")
    print("=" * 60)

    all_passed = True
    for backend_key, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {BACKENDS[backend_key]['name']}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\nAll database backend tests passed!")
    else:
        print("\nSome tests failed!")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
