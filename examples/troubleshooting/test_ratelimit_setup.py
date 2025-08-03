#!/usr/bin/env python
"""
Quick test script to verify rate limiting behavior.

Run this script to test if your rate limiting setup is working correctly
and to identify common issues like double-counting or browser interference.

Usage:
    python test_ratelimit_setup.py [--url http://localhost:8000/api/test/]

    # Simulate browser behavior that caused GitHub issue #6
    python test_ratelimit_setup.py --simulate-browser

    # Test specific endpoint with more requests
    python test_ratelimit_setup.py --endpoint api/my-view/ --requests 10
"""

import argparse
import json
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def simulate_browser_behavior(base_url, endpoint="api/test-behavior/"):
    """
    Simulate browser behavior that was causing the user's issues.

    Browsers typically make multiple requests:
    1. Main request
    2. favicon.ico
    3. Preflight OPTIONS (for CORS)
    """
    url = urljoin(base_url.rstrip("/") + "/", endpoint)
    results = []

    print("\nSimulating browser behavior (like in GitHub issue #6):")
    print("=" * 60)

    # 1. Main request
    try:
        req = Request(url)
        req.add_header("User-Agent", "Mozilla/5.0 (Browser simulation)")

        with urlopen(req) as response:
            data = (
                json.loads(response.read().decode()) if response.status == 200 else {}
            )
            backend_counts_1 = data.get("current_state", {}).get("backend_counts", {})
            print(f"1. Main request: Backend counts = {backend_counts_1}")
            results.append({"type": "main", "counts": backend_counts_1})
    except Exception as e:
        print(f"1. Main request failed: {e}")

    time.sleep(0.1)

    # 2. Favicon request (common browser secondary request)
    try:
        favicon_url = urljoin(base_url.rstrip("/") + "/", "favicon.ico")
        req = Request(favicon_url)
        req.add_header("User-Agent", "Mozilla/5.0 (Browser simulation)")

        with urlopen(req) as response:
            # This might 404, but that's ok - we're testing if it affects rate limiting
            print(f"2. Favicon request: Status {response.status}")
            results.append({"type": "favicon", "status": response.status})
    except Exception as e:
        print(f"2. Favicon request: {e}")

    time.sleep(0.1)

    # 3. Another main request to see if count increased properly
    try:
        req = Request(url)
        req.add_header("User-Agent", "Mozilla/5.0 (Browser simulation)")

        with urlopen(req) as response:
            data = (
                json.loads(response.read().decode()) if response.status == 200 else {}
            )
            backend_counts_2 = data.get("current_state", {}).get("backend_counts", {})
            print(f"3. Second main request: Backend counts = {backend_counts_2}")
            results.append({"type": "main", "counts": backend_counts_2})

            # Check if count increased by more than 1
            if backend_counts_1 and backend_counts_2:
                for key in backend_counts_1:
                    if key in backend_counts_2:
                        diff = backend_counts_2[key] - backend_counts_1[key]
                        if diff > 1:
                            print(
                                f"⚠️  ISSUE DETECTED: Count for '{key}' increased by {diff} (expected 1)"
                            )
                            print(
                                "   This matches the user's reported issue in GitHub #6"
                            )
                        elif diff == 1:
                            print(f"✅ Count for '{key}' increased correctly by 1")
                        else:
                            print(f"🤔 Count for '{key}' increased by {diff}")

    except Exception as e:
        print(f"3. Second main request failed: {e}")

    return results


def test_rate_limit_endpoint(base_url, endpoint="api/test-behavior/", num_requests=5):
    """
    Test rate limiting by making multiple requests to an endpoint.

    Args:
        base_url: Base URL of your Django application
        endpoint: Endpoint to test (should have rate limiting applied)
        num_requests: Number of requests to make for testing

    Returns:
        dict: Test results and analysis
    """
    url = urljoin(base_url.rstrip("/") + "/", endpoint)
    results = []

    print(f"Testing rate limiting at: {url}")
    print(f"Making {num_requests} requests...")
    print("-" * 50)

    for i in range(num_requests):
        try:
            # Make request
            req = Request(url)
            req.add_header("User-Agent", "RateLimitTest/1.0")
            req.add_header("X-Test-Request", f"request-{i+1}")

            with urlopen(req) as response:
                status_code = response.getcode()
                headers = dict(response.headers)

                # Get rate limit headers
                limit = headers.get("X-RateLimit-Limit", "Not set")
                remaining = headers.get("X-RateLimit-Remaining", "Not set")
                reset = headers.get("X-RateLimit-Reset", "Not set")

                # Try to get response data
                try:
                    data = json.loads(response.read().decode())
                except:
                    data = {}

                result = {
                    "request_num": i + 1,
                    "status_code": status_code,
                    "limit": limit,
                    "remaining": remaining,
                    "reset": reset,
                    "backend_counts": data.get("current_state", {}).get(
                        "backend_counts", {}
                    ),
                    "middleware_processed": data.get("current_state", {}).get(
                        "middleware_processed", False
                    ),
                }

                results.append(result)

                print(
                    f"Request {i+1}: Status={status_code}, "
                    f"Limit={limit}, Remaining={remaining}"
                )

                # Small delay between requests
                time.sleep(0.1)

        except HTTPError as e:
            if e.code == 429:  # Rate limited
                headers = dict(e.headers)
                result = {
                    "request_num": i + 1,
                    "status_code": 429,
                    "limit": headers.get("X-RateLimit-Limit", "Not set"),
                    "remaining": headers.get("X-RateLimit-Remaining", "Not set"),
                    "reset": headers.get("X-RateLimit-Reset", "Not set"),
                    "rate_limited": True,
                }
                results.append(result)
                print(f"Request {i+1}: RATE LIMITED (429)")
            else:
                print(f"Request {i+1}: HTTP Error {e.code}")

        except Exception as e:
            print(f"Request {i+1}: Error - {e}")

    return analyze_results(results)


def analyze_results(results):
    """Analyze test results and provide recommendations."""
    analysis = {
        "total_requests": len(results),
        "successful_requests": len([r for r in results if r["status_code"] == 200]),
        "rate_limited_requests": len(
            [r for r in results if r.get("rate_limited", False)]
        ),
        "issues_found": [],
        "recommendations": [],
    }

    print("\n" + "=" * 50)
    print("ANALYSIS RESULTS")
    print("=" * 50)

    # Check for inconsistent counting (user's main issue)
    backend_counts = [
        r.get("backend_counts", {}) for r in results if r.get("backend_counts")
    ]
    if len(backend_counts) >= 2:
        # Compare counts between requests
        for i in range(1, len(backend_counts)):
            prev_counts = backend_counts[i - 1]
            curr_counts = backend_counts[i]

            for key in prev_counts:
                if key in curr_counts:
                    diff = curr_counts[key] - prev_counts[key]
                    if diff > 1:
                        analysis["issues_found"].append(
                            f"Count increased by {diff} between requests {i} and {i+1} "
                            f"for key '{key}' - possible double-counting (GitHub issue #6)"
                        )
                    elif diff == 0:
                        analysis["issues_found"].append(
                            f"Count did not increase between requests {i} and {i+1} "
                            f"for key '{key}' - possible skip condition or error"
                        )

    # Check for header consistency (user's second issue)
    limits = [r["limit"] for r in results if r["limit"] != "Not set"]
    if limits and len(set(limits)) > 1:
        analysis["issues_found"].append(
            f"Inconsistent rate limit headers: {set(limits)} - "
            "possible middleware/decorator conflict (GitHub issue #6)"
        )

    # Check for header vs configured limit mismatch (user reported limit 600 but headers showed different)
    if limits:
        unique_limits = set(limits)
        if len(unique_limits) == 1:
            reported_limit = list(unique_limits)[0]
            try:
                int(reported_limit)
                # Check if remaining counts are behaving correctly
                remaining_values = [
                    r["remaining"] for r in results if r["remaining"] != "Not set"
                ]
                if remaining_values:
                    remaining_ints = []
                    for rem in remaining_values:
                        try:
                            remaining_ints.append(int(rem))
                        except:
                            pass

                    if len(remaining_ints) >= 2:
                        # Check if remaining is decreasing properly (should decrease by 1 per request)
                        for i in range(1, len(remaining_ints)):
                            expected_remaining = remaining_ints[i - 1] - 1
                            actual_remaining = remaining_ints[i]
                            if (
                                actual_remaining != expected_remaining
                                and actual_remaining >= 0
                            ):
                                analysis["issues_found"].append(
                                    f"Remaining count changed from {remaining_ints[i-1]} to {actual_remaining}, "
                                    f"expected {expected_remaining} - possible counting inconsistency"
                                )
            except:
                pass

    # Check for missing headers
    missing_headers = any(
        r["limit"] == "Not set" for r in results if r["status_code"] == 200
    )
    if missing_headers:
        analysis["issues_found"].append("Missing rate limit headers in some responses")

    # Generate recommendations
    if analysis["issues_found"]:
        analysis["recommendations"].extend(
            [
                "Review troubleshooting.md for common issues",
                "Check if both middleware and decorator are applied to the same endpoint",
                "Verify skip_if conditions to avoid counting unwanted requests",
                "Use debug_ratelimit_status() function for detailed debugging",
            ]
        )
    else:
        analysis["recommendations"].append(
            "Rate limiting appears to be working correctly!"
        )

    # Print analysis
    print(f"Total requests: {analysis['total_requests']}")
    print(f"Successful: {analysis['successful_requests']}")
    print(f"Rate limited: {analysis['rate_limited_requests']}")

    if analysis["issues_found"]:
        print("\nISSUES FOUND:")
        for issue in analysis["issues_found"]:
            print(f"⚠️  {issue}")
    else:
        print("\n✅ No issues detected!")

    print("\nRECOMMENDATIONS:")
    for rec in analysis["recommendations"]:
        print(f"💡 {rec}")

    return analysis


def main():
    """Main function to run the rate limiting test script."""
    parser = argparse.ArgumentParser(description="Test Django rate limiting setup")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/",
        help="Base URL of your Django application (default: http://localhost:8000/)",
    )
    parser.add_argument(
        "--endpoint",
        default="api/test-behavior/",
        help="Endpoint to test (default: api/test-behavior/)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=5,
        help="Number of test requests to make (default: 5)",
    )

    parser.add_argument(
        "--simulate-browser",
        action="store_true",
        help="Simulate browser behavior that caused issues in GitHub #6",
    )

    args = parser.parse_args()

    try:
        if args.simulate_browser:
            # Run browser simulation
            simulate_browser_behavior(args.url, args.endpoint)
            print("\nNow running standard test...")

        results = test_rate_limit_endpoint(args.url, args.endpoint, args.requests)
        return 0 if not results["issues_found"] else 1
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        return 1
    except Exception as e:
        print(f"Test failed: {e}")
        print("\nMake sure your Django server is running and the endpoint exists.")
        print("You may need to add the test endpoint to your urls.py:")
        print("    path('api/test-behavior/', views.test_rate_limit_behavior)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
