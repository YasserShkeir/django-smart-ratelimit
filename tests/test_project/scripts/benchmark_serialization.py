import os
import statistics
import sys
import time

import requests

# Add parent directory to path to import verify_scenarios
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def measure_endpoint(url, count=20):
    latencies = []
    headers = {"X-API-KEY": "benchmark"}
    for _ in range(count):
        start = time.perf_counter()
        resp = requests.get(url, headers=headers)
        duration = (time.perf_counter() - start) * 1000  # ms
        latencies.append(duration)
    return latencies


def run_suite(base_url):
    print(f"\n--- Benchmarking Serialization ({base_url}) ---")

    # Compare Overhead
    # 1. No Rate Limit (Control) - We don't have a view without rate limit explicitly
    # except maybe if we use a key that is skipped or very high limit?
    # We can use /opt/skip/ with admin user? But we can't login easily.
    # We can use /opt/methods/ with GET (which is skipped).

    url_control = f"{base_url}/opt/methods/"
    print(f"  Measuring Baseline (No Rate Limit logic executed)...")
    base_latencies = measure_endpoint(url_control)

    avg_base = statistics.mean(base_latencies)
    print(f"  Baseline Avg: {avg_base:.2f}ms")

    # 2. Rate Limited (Active)
    # Use Fixed Window
    url_active = f"{base_url}/algo/fixed/"
    print(f"  Measuring Active Rate Limit (Fixed Window)...")
    # We might hit 429, but that still measures overhead of logic.
    active_latencies = measure_endpoint(url_active)

    avg_active = statistics.mean(active_latencies)
    print(f"  Active Avg:   {avg_active:.2f}ms")

    overhead = avg_active - avg_base
    print(f"  Estimated Overhead: {overhead:.2f}ms")

    if overhead > 10:
        print("  [WARN] Overhead > 10ms! This might be slow.")
        # Not a failure condition per se, but a warning.
    else:
        print("  [PASS] Overhead is acceptable.")

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="http://localhost:8001")
    args = parser.parse_args()
    run_suite(args.url)
