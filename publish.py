#!/usr/bin/env python3
"""
Publishing script for django-smart-ratelimit
"""

import os
import subprocess
import sys
from pathlib import Path

def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"🚀 {description}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Error: {result.stderr}")
        sys.exit(1)
    print(f"✅ {description} - Done!")
    return result.stdout

def main():
    print("📦 Django Smart Ratelimit Publishing Script")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not Path("pyproject.toml").exists():
        print("❌ Error: pyproject.toml not found. Are you in the right directory?")
        sys.exit(1)
    
    # Clean previous builds
    print("🧹 Cleaning previous builds...")
    if Path("dist").exists():
        run_command("rm -rf dist", "Cleaning dist directory")
    if Path("build").exists():
        run_command("rm -rf build", "Cleaning build directory")
    
    # Run tests
    run_command("python3 -m pytest", "Running tests")
    
    # Build package
    run_command("python3 -m build", "Building package")
    
    # Check package
    run_command("python3 -m twine check dist/*", "Checking package")
    
    print("\n📋 Package built successfully!")
    print("Next steps:")
    print("1. Set up PyPI account at https://pypi.org/account/register/")
    print("2. Create API token at https://pypi.org/manage/account/")
    print("3. Upload to TestPyPI first:")
    print("   python3 -m twine upload --repository testpypi dist/*")
    print("4. Test install from TestPyPI:")
    print("   pip install --index-url https://test.pypi.org/simple/ django-smart-ratelimit")
    print("5. Upload to PyPI:")
    print("   python3 -m twine upload dist/*")
    
    print("\n🎉 Ready to publish!")

if __name__ == "__main__":
    main()
