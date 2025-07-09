#!/usr/bin/env python
"""
Test runner for DRF integration tests.

This script runs DRF integration tests and provides information about
DRF availability and test coverage.
"""

import os
import sys

import django
from django.conf import settings
from django.test.utils import get_runner

# Add the parent directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_drf_availability():
    """Check if DRF is available and return status."""
    try:
        import rest_framework

        return True, rest_framework.VERSION
    except ImportError:
        return False, None


def setup_django():
    """Setup Django for testing."""
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE", "tests.drf_integration.settings_drf"
    )
    django.setup()


def run_drf_tests():
    """Run DRF integration tests."""
    print("Django Smart Ratelimit - DRF Integration Tests")
    print("=" * 50)

    # Check DRF availability
    drf_available, drf_version = check_drf_availability()

    if drf_available:
        print(f"✓ DRF is available (version: {drf_version})")
    else:
        print("✗ DRF is not available")
        print("  Install DRF with: pip install djangorestframework")
        print("  Some tests will be skipped.")

    print()

    # Setup Django
    setup_django()

    # Get test runner
    TestRunner = get_runner(settings)
    test_runner = TestRunner()

    # Run specific DRF tests
    test_labels = [
        "tests.drf_integration.test_drf_integration",
        "tests.drf_integration.test_drf_mock",
        "examples.drf_integration.tests",
    ]

    print("Running DRF integration tests...")
    failures = test_runner.run_tests(test_labels)

    if failures:
        print(f"\n✗ {failures} test(s) failed")
        sys.exit(1)
    else:
        print("\n✓ All DRF integration tests passed!")


def main():
    """Main function."""
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print(__doc__)
        print("Usage: python run_drf_tests.py [--help]")
        print()
        print("Options:")
        print("  --help    Show this help message")
        print()
        print("This script will:")
        print("  1. Check if DRF is available")
        print("  2. Setup Django test environment")
        print("  3. Run DRF integration tests")
        print("  4. Report test results")
        return

    try:
        run_drf_tests()
    except Exception as e:
        print(f"Error running tests: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
