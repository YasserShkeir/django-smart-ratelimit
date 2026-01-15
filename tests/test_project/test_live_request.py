"""Test: Make actual HTTP request and see what happens"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "integration_test_project.settings")
django.setup()

from django.test import Client

# Create test client
client = Client()

# Test the middleware async endpoint
print("Testing /middleware/async/ via Django test client...")
response = client.get("/middleware/async/")
print(f"Status: {response.status_code}")
print(f"Headers: {dict(response.headers)}")
print(f"Content: {response.content.decode()}")
print()

# Compare with /algo/fixed/
print("Testing /algo/fixed/ via Django test client...")
response2 = client.get("/algo/fixed/")
print(f"Status: {response2.status_code}")
print(f"Headers: {dict(response2.headers)}")
print(f"Content: {response2.content.decode()}")
