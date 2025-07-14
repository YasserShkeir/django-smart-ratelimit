"""
Example usage of MongoDB backend for Django Smart Ratelimit.

This example demonstrates how to configure and use the MongoDB backend
for rate limiting in a Django application.
"""

import os
import sys

import django
from django.conf import settings

# Add the project directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Configure Django settings for the example
if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY="example-secret-key-for-mongodb-demo",
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django_smart_ratelimit",
        ],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        # MongoDB backend configuration
        RATELIMIT_BACKEND="mongodb",
        RATELIMIT_MONGODB={
            "host": "localhost",
            "port": 27017,
            "database": "example_ratelimit",
            "collection": "rate_limit_entries",
            "counter_collection": "rate_limit_counters",
            "username": None,  # Set if authentication is required
            "password": None,  # Set if authentication is required
            "auth_source": "admin",  # Set if authentication is required
            "algorithm": "sliding_window",  # or 'fixed_window'
            "max_pool_size": 50,
            "server_selection_timeout": 5000,
        },
        USE_TZ=True,
    )

django.setup()

from django.http import HttpRequest, HttpResponse

# Now we can import and use the MongoDB backend
from django_smart_ratelimit.backends import get_backend
from django_smart_ratelimit.decorator import rate_limit


def example_basic_usage() -> None:
    """Example of basic MongoDB backend usage."""
    print("=== Basic MongoDB Backend Usage ===")

    try:
        # Get the MongoDB backend
        backend = get_backend()
        print(f"Backend type: {backend.__class__.__name__}")

        # Test basic operations
        test_key = "example_user_127.0.0.1"

        # Increment counter
        count1 = backend.incr(test_key, 60)  # 60 second window
        print(f"First _request count: {count1}")

        count2 = backend.incr(test_key, 60)
        print(f"Second _request count: {count2}")

        # Get current count
        current_count = backend.get_count(test_key)
        print(f"Current count: {current_count}")

        # Get reset time
        reset_time = backend.get_reset_time(test_key)
        print(f"Reset time: {reset_time}")

        # Reset counter
        backend.reset(test_key)
        print("Counter reset")

        # Check count after reset
        count_after_reset = backend.get_count(test_key)
        print(f"Count after reset: {count_after_reset}")

        # Health check (if available)
        if hasattr(backend, "health_check"):
            is_healthy = backend.health_check()
            print(f"Backend healthy: {is_healthy}")

        # Get stats (if available)
        if hasattr(backend, "get_stats"):
            stats = backend.get_stats()
            print(f"Backend stats: {stats}")

    except Exception as e:
        print(f"Error: {e}")
        print("Note: This example requires MongoDB to be installed and running.")
        print("Install MongoDB backend with: pip install pymongo")


def example_decorator_usage() -> None:
    """Example of using MongoDB backend with decorators."""
    print("\n=== MongoDB Backend with Decorators ===")

    @rate_limit(key="ip", rate="5/1m", backend="mongodb")
    def api_endpoint(_request: HttpRequest) -> HttpResponse:
        return HttpResponse("API response")

    # Create mock _request
    _request = HttpRequest()
    _request.META["REMOTE_ADDR"] = "127.0.0.1"

    try:
        # Test multiple requests
        for i in range(7):
            response = api_endpoint(_request)
            print(f"Request {i+1}: Status {response.status_code}")

    except Exception as e:
        print(f"Error: {e}")


def example_atlas_configuration() -> None:
    """Example of MongoDB Atlas configuration."""
    print("\n=== MongoDB Atlas Configuration Example ===")

    atlas_config = {
        "RATELIMIT_BACKEND": "mongodb",
        "RATELIMIT_MONGODB": {
            "host": "cluster0.mongodb.net",
            "port": 27017,
            "database": "ratelimit",
            "username": "your-username",
            "password": "your-password",
            "auth_source": "admin",
            "tls": True,
            "replica_set": "atlas-replica-set",
            "algorithm": "sliding_window",
            "max_pool_size": 50,
            "server_selection_timeout": 10000,
        },
    }

    print("MongoDB Atlas configuration:")
    print("```python")
    print("# settings.py")
    for key, value in atlas_config.items():
        if isinstance(value, dict):
            print(f"{key} = {{")
            for k, v in value.items():
                print(f"    '{k}': {repr(v)},")
            print("}")
        else:
            print(f"{key} = {repr(value)}")
    print("```")


def example_performance_configuration() -> None:
    """Example of performance-optimized MongoDB configuration."""
    print("\n=== Performance-Optimized MongoDB Configuration ===")

    perf_config = {
        "RATELIMIT_BACKEND": "mongodb",
        "RATELIMIT_MONGODB": {
            "host": "mongodb-cluster.example.com",
            "port": 27017,
            "database": "ratelimit",
            "collection": "rate_limit_entries",
            "counter_collection": "rate_limit_counters",
            "username": "ratelimit_user",
            "password": "secure_password",
            "auth_source": "admin",
            "replica_set": "rs0",
            "algorithm": "fixed_window",  # Generally faster than sliding_window
            "max_pool_size": 100,  # Increased for high load
            "min_pool_size": 10,  # Keep connections warm
            "server_selection_timeout": 5000,
            "socket_timeout": 10000,
            "connect_timeout": 5000,
        },
    }

    print("Performance-optimized MongoDB configuration:")
    print("```python")
    print("# settings.py")
    for key, value in perf_config.items():
        if isinstance(value, dict):
            print(f"{key} = {{")
            for k, v in value.items():
                print(f"    '{k}': {repr(v)},")
            print("}")
        else:
            print(f"{key} = {repr(value)}")
    print("```")


def example_algorithm_comparison() -> None:
    """Example comparing sliding window vs fixed window algorithms."""
    print("\n=== Algorithm Comparison ===")

    print("Sliding Window Algorithm:")
    print("- More accurate rate limiting")
    print("- Higher memory usage (stores individual requests)")
    print("- Slightly slower performance")
    print("- Better for strict rate limiting requirements")
    print()

    print("Fixed Window Algorithm:")
    print("- Less accurate (burst at window boundaries)")
    print("- Lower memory usage (stores only counters)")
    print("- Faster performance")
    print("- Good for general rate limiting needs")
    print()

    print("Configuration examples:")
    print("```python")
    print("# Sliding window (default)")
    print("RATELIMIT_MONGODB = {")
    print("    'algorithm': 'sliding_window',")
    print("    # ... other config")
    print("}")
    print()
    print("# Fixed window")
    print("RATELIMIT_MONGODB = {")
    print("    'algorithm': 'fixed_window',")
    print("    # ... other config")
    print("}")
    print("```")


def example_advanced_decorator_usage() -> None:
    """Example of advanced usage with algorithm and skip_if parameters."""
    print("\n=== MongoDB Backend with Advanced Decorators ===")

    # Example: MongoDB backend with algorithm and skip_if parameters
    @rate_limit(
        key="ip",
        rate="50/h",
        backend="mongodb",
        algorithm="sliding_window",
        skip_if=lambda _request: _request.META.get("REMOTE_ADDR", "").startswith(
            "127."
        ),
    )
    def mongodb_api_with_algorithm(_request: HttpRequest) -> HttpResponse:
        """
        MongoDB-backed API with sliding window and localhost bypass.

        Uses MongoDB for storage with sliding window algorithm.
        Bypasses rate limiting for localhost requests.
        """
        ip = _request.META.get("REMOTE_ADDR", "unknown")
        is_localhost = ip.startswith("127.")

        return HttpResponse(
            f"""
        MongoDB Rate Limiting with Algorithm
        IP: {ip}
        Algorithm: sliding_window
        Bypassed: {is_localhost}
        Rate Limit: {'No limit for localhost' if is_localhost else '50/h sliding window'}
        """
        )

    @rate_limit(
        key="user",
        rate="100/h",
        backend="mongodb",
        algorithm="fixed_window",
        skip_if=lambda _request: _request.user.is_staff,
    )
    def mongodb_user_api_with_bypass(_request: HttpRequest) -> HttpResponse:
        """
        MongoDB-backed user API with fixed window and staff bypass.

        Uses MongoDB for storage with fixed window algorithm.
        Staff users bypass rate limiting entirely.
        """
        user_id = _request.user.id if _request.user.is_authenticated else "anonymous"
        is_staff = _request.user.is_staff

        return HttpResponse(
            f"""
        MongoDB User Rate Limiting with Fixed Window
        User: {user_id}
        Algorithm: fixed_window
        Bypassed: {is_staff}
        Rate Limit: {'No limit for staff' if is_staff else '100/h fixed window'}
        """
        )

    # Create mock requests
    request1 = HttpRequest()
    request1.META["REMOTE_ADDR"] = "127.0.0.1"

    request2 = HttpRequest()
    request2.META["REMOTE_ADDR"] = "192.168.1.10"
    request2.user = type(
        "User", (object,), {"is_authenticated": True, "id": 1, "is_staff": False}
    )

    request3 = HttpRequest()
    request3.META["REMOTE_ADDR"] = "10.0.0.5"
    request3.user = type(
        "User", (object,), {"is_authenticated": True, "id": 2, "is_staff": True}
    )

    try:
        # Test advanced API with algorithm and skip_if
        print("Testing mongodb_api_with_algorithm:")
        for i in range(3):
            response = mongodb_api_with_algorithm(request1)
            print(f"Request {i+1}: Status {response.status_code}")

        print("Testing mongodb_user_api_with_bypass:")
        response2 = mongodb_user_api_with_bypass(request2)
        print(f"User _request (non-staff): Status {response2.status_code}")

        response3 = mongodb_user_api_with_bypass(request3)
        print(f"User _request (staff): Status {response3.status_code}")

    except Exception as e:
        print(f"Error: {e}")


def main() -> None:
    """Run all examples."""
    print("Django Smart Ratelimit - MongoDB Backend Examples")
    print("=" * 50)

    example_basic_usage()
    example_decorator_usage()
    example_atlas_configuration()
    example_performance_configuration()
    example_algorithm_comparison()
    example_advanced_decorator_usage()

    print("\n" + "=" * 50)
    print("MongoDB Backend Features:")
    print("✓ TTL collections for automatic cleanup")
    print("✓ Connection pooling for performance")
    print("✓ Both sliding window and fixed window algorithms")
    print("✓ MongoDB Atlas support")
    print("✓ Replica set support")
    print("✓ TLS/SSL support")
    print("✓ Authentication support")
    print("✓ Health checks and monitoring")
    print("✓ Detailed statistics")
    print("✓ Graceful error handling")
    print()
    print("For more information, see the documentation at:")
    print(
        "https://django-smart-ratelimit.readthedocs.io/en/latest/backends/mongodb.html"
    )


if __name__ == "__main__":
    main()
