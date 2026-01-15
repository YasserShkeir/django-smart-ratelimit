import argparse
import contextlib
import io
import os
import subprocess
import sys
import time

# Add current directory to path to find the test modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import benchmark_serialization
import test_async
import test_batch
import test_concurrency
import test_core_algorithms
import test_headers_options
import test_keys
import test_middleware_drf
import test_real_world
import test_reliability

PORTS = {
    "Memory": 8001,
    "Redis": 8002,
    "RedisAsync": 8003,
    "MongoDB": 8004,
    "Multi": 8005,
}


def flush_redis():
    """
    Flush all Redis data to clear rate limit counters between backend tests.
    """
    try:
        cmd = "docker exec django-ratelimit-base-redis-1 redis-cli FLUSHALL"
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
    except Exception:
        pass  # Ignore if redis container not accessible


def invoke_reset_containers():
    """
    Restarts the docker containers to ensure a clean state (clears memory/redis limits).
    """
    print("\n[INFO] Restarting containers to clear rate limit state...")
    try:
        # Resolve path to docker-compose.qa.yml
        # Script is in integration_test_project/scripts/
        # Project root is ../../
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(script_dir))
        compose_file = os.path.join(project_root, "docker-compose.qa.yml")

        # Verify file exists
        if not os.path.exists(compose_file):
            print(f"[WARN] Docker Compose file not found at {compose_file}")
            return

        cmd = f"docker-compose -f {compose_file} restart"
        print(f"[INFO] Running: {cmd}")
        subprocess.run(cmd, shell=True, check=True)

        # Flush Redis to clear any persisted counters
        flush_redis()

        print("[INFO] Waiting 10s for services to stabilize...")
        time.sleep(10)
    except Exception as e:
        print(f"[WARN] Failed to restart containers: {e}")


def run_all(target_env=None):
    # Always restart first to prevent 429s from previous runs
    invoke_reset_containers()

    results = {}
    failure_details = {}

    targets = PORTS.items()
    if target_env:
        targets = [(k, v) for k, v in PORTS.items() if k == target_env]

    for name, port in targets:
        url = f"http://localhost:{port}"
        print(f"\n{'='*60}")
        print(f"RUNNING SUITE AGAINST: {name} ({url})")
        print(f"{'='*60}")

        # Flush Redis before each backend to ensure clean state
        flush_redis()

        suite_output = io.StringIO()
        success = False

        # Capture stdout to parse for [FAIL]
        # We need to print to real stdout AS WELL so user sees progress
        # So we can't just redirect_stdout. We need a Tee.
        # But simpler: Redirect, then print captured value.

        with contextlib.redirect_stdout(suite_output):
            try:
                # We run suites sequentially. If one fails, we still try others but mark environment as failed.
                # Must check each return value to detect failure
                # but we want to run ALL to get full report

                # Using a list to run all and collect results
                suites = [
                    ("Core Algorithms", test_core_algorithms.run_suite),
                    ("Keys", test_keys.run_suite),
                    ("Headers", test_headers_options.run_suite),
                    ("Middleware DRF", test_middleware_drf.run_suite),
                    ("Batch Decorator", test_batch.run_suite),
                    ("Async Views", test_async.run_suite),
                    ("Concurrency", test_concurrency.run_suite),
                    ("Real World", test_real_world.run_suite),
                    ("Benchmark", benchmark_serialization.run_suite),
                    ("Reliability", test_reliability.run_suite),
                ]

                env_success = True
                for suite_name, suite_func in suites:
                    print(f"\n>>> Running {suite_name}...")
                    try:
                        if not suite_func(url):
                            print(f"[FAIL] {suite_name} Suite Failed")
                            env_success = False
                    except Exception as ex:
                        print(f"[FAIL] {suite_name} Suite Exception: {ex}")
                        env_success = False

                success = env_success
                results[name] = success

            except Exception as e:
                print(f"CRITICAL ERROR testing {name}: {e}")
                results[name] = False
                success = False

        # Restore stdout and print what we captured
        full_log = suite_output.getvalue()
        sys.__stdout__.write(full_log)

        if not success:
            # Parse failures
            # Logic: Look for lines containing "[FAIL]"
            fails = [
                model_line
                for model_line in full_log.split("\n")
                if "[FAIL]" in model_line
            ]
            failure_details[name] = fails

    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    all_pass = True
    for name, result in results.items():
        status = "PASS" if result else "FAIL"
        if not result:
            all_pass = False
        print(f"{name:15}: {status}")

        if not result and name in failure_details:
            for fail_line in failure_details[name]:
                # Indent failure details
                print(f"  -> {fail_line.strip()}")

    return all_pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env", choices=PORTS.keys(), help="Run against specific environment"
    )
    args = parser.parse_args()

    success = run_all(args.env)
    sys.exit(0 if success else 1)
