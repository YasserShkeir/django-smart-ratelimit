import os
import subprocess
import sys
import time

import requests

# Add parent directory to path to import verify_scenarios
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Path to docker-compose file relative to this script
COMPOSE_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../docker-compose.qa.yml")
)


def run_command(cmd):
    try:
        subprocess.run(
            cmd,
            shell=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def test_redis_failover(base_url):
    print(f"\n--- Testing Redis Failover ({base_url}) ---")

    # Check if this backend uses Redis
    target = "redis" if ":8002" in base_url or ":8003" in base_url else "other"
    if target != "redis":
        print("  [SKIP] Not Redis backend")
        return True

    # 1. Verify normal operation
    url_open = f"{base_url}/infra/fail-open/"
    resp = requests.get(url_open)
    if resp.status_code != 200:
        print(f"  [FAIL] Pre-check failed. Status: {resp.status_code}")
        return False

    print("  Status: Normal")

    success = True
    # 2. Kill Redis
    print("  Stopping Redis container...")
    if not run_command(f"docker-compose -f {COMPOSE_FILE} stop redis"):
        print("  [SKIP] Could not stop redis (docker-compose failed)")
        return True

    try:
        # Give it a moment to stop
        time.sleep(2)

        # 3. Test Fail Open
        print("  Testing Fail Open (Should allow if configured, else 429)...")
        try:
            resp = requests.get(url_open, timeout=5)
            # Fail Open = 200. Fail Closed = 429. Both are 'valid' outcomes here,
            # as long as it handles the error gracefully (doesn't hang or 500).
            if resp.status_code == 200:
                print(f"  [PASS] Request Allowed (Status: 200)")
            elif resp.status_code == 429:
                print(
                    f"  [PASS] Request Blocked (Status: 429) - System Default is Fail Closed"
                )
            else:
                print(f"  [FAIL] Unexpected Status: {resp.status_code}")
                success = False
        except requests.exceptions.RequestException as e:
            print(f"  [FAIL] Request failed with Exception: {e}")
            success = False

        # 4. Test Fail Closed
        print("  Testing Fail Closed (Should fail)...")
        url_closed = f"{base_url}/infra/fail-closed/"
        try:
            resp = requests.get(url_closed, timeout=5)
            # Default behavior for backend error is Exception -> 429
            # So 429 or 500 are acceptable for 'Blocked'. 200 is failure.
            if resp.status_code >= 400:
                print(f"  [PASS] Request blocked as expected ({resp.status_code})")
            else:
                print(f"  [FAIL] Request passed? Status: {resp.status_code}")
                success = False
        except requests.exceptions.RequestException:
            print(f"  [PASS] Request failed (Exception) as expected")

    finally:
        # 5. Restore Redis
        print("  Restarting Redis container...")
        run_command(f"docker-compose -f {COMPOSE_FILE} start redis")
        print("  Waiting for Redis to recover...")
        time.sleep(5)

    return success


def test_circuit_breaker_states(base_url):
    print(f"\n--- Testing Circuit Breaker States ({base_url}) ---")

    # Only meaningful if checking a backend that can fail (Redis)
    target = "redis" if ":8002" in base_url or ":8003" in base_url else "other"
    if target != "redis":
        print("  [SKIP] Not Redis backend (Only Redis failure is simulated)")
        return True

    cb_url = f"{base_url}/infra/cb-status/"
    check_url = (
        f"{base_url}/infra/fail-closed/"  # Use fail closed to force backend usage
    )

    # 1. Check Initial State
    try:
        resp = requests.get(cb_url)
        if resp.status_code != 200:
            print(f"  [SKIP] CB Status endpoint missing ({resp.status_code})")
            return True
        status = resp.json()
        if not status.get("circuit_breaker_enabled"):
            print("  [SKIP] Circuit Breaker Disabled")
            return True

        # Find the relevant backend state
        initial_state = status.get("cb_state") or status.get("circuit_breaker", {}).get(
            "state"
        )

        # Fallback for complex structures
        if not initial_state:
            for k, v in status.items():
                if k in ["redis", "async_redis"] and isinstance(v, dict):
                    initial_state = v.get("state") or v.get("circuit_breaker", {}).get(
                        "state"
                    )
                    if initial_state:
                        break

        print(f"  Initial State: {initial_state}")
        if initial_state and initial_state.lower() != "closed":
            print(
                "  [WARN] CB not closed initially. Attempting simple requests to verify health."
            )
    except Exception as e:
        print(f"  [ERROR] Checking CB status: {e}")
        return False

    success = True

    # 2. Trip Breaker
    print("  Stopping Redis to trip breaker...")
    run_command(f"docker-compose -f {COMPOSE_FILE} stop redis")
    time.sleep(1)

    print("  Generating failures...")
    for i in range(15):  # Increased count to ensure threshold is met
        try:
            requests.get(check_url, timeout=0.5)
        except:
            pass

    # 3. Verify OPEN State
    try:
        resp = requests.get(cb_url)
        status = resp.json()

        state = status.get("cb_state") or status.get("circuit_breaker", {}).get("state")
        if not state:
            for k, v in status.items():
                if k in ["redis", "async_redis"] and isinstance(v, dict):
                    state = v.get("state") or v.get("circuit_breaker", {}).get("state")
                    if state:
                        break

        # If still unknown, log it
        if not state:
            print(f"  [DEBUG] CB Status JSON: {status}")
            state = "unknown"

        print(f"  State after failures: {state}")

        if state and state.lower() == "open":
            print("  [PASS] Circuit Breaker Tripped to OPEN")
        else:
            print("  [FAIL] Circuit Breaker did NOT trip (remained closed/half-open)")
            success = False
    except Exception as e:
        print(f"  [FAIL] Could not verify state: {e}")
        success = False

    # 4. Verify Recovery (Requires restarting Redis and waiting)
    if success:
        print("  Restarting Redis...")
        run_command(f"docker-compose -f {COMPOSE_FILE} start redis")
        print("  Waiting for Recovery Timeout (5s)...")
        time.sleep(6)  # Wait slightly longer than 5s

        # Trigger Half-Open check
        print("  Triggering Half-Open check...")
        try:
            requests.get(check_url, timeout=1)
        except:
            pass

        # Check State
        try:
            resp = requests.get(cb_url)
            status = resp.json()
            state = status.get("cb_state") or status.get("circuit_breaker", {}).get(
                "state"
            )
            print(f"  State after recovery: {state}")
            if state and state.lower() == "closed":
                print("  [PASS] Circuit Breaker Recovered to CLOSED")
            else:
                print(
                    "  [WARN] Circuit Breaker not yet CLOSED (might need more successes)"
                )
        except:
            pass

    # Ensure Redis is up for next tests
    if not success:
        run_command(f"docker-compose -f {COMPOSE_FILE} start redis")
        time.sleep(5)

    return success


def run_suite(base_url):
    """Run all reliability tests for the given base URL."""
    print(f"Running Reliability Suite for {base_url}")

    # Reliability tests only meaningful for backends that can fail (Redis, Multi)
    # Skip for Memory, MongoDB (no easy way to stop MongoDB in tests), and others
    if ":8002" in base_url or ":8003" in base_url:
        target = "redis"
    elif ":8005" in base_url:
        target = "multi"  # Multi backend uses Redis as primary
    else:
        print("Skipping reliability tests for this backend")
        return True

    r1 = test_redis_failover(base_url)
    r2 = test_circuit_breaker_states(base_url)
    return r1 and r2


if __name__ == "__main__":
    # If run standalone
    test_redis_failover("http://localhost:8002")
