import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")

import django

django.setup()

from django_smart_ratelimit.utils import get_rate_for_path

# Test path matching
rate_limits = {"/middleware/async/": "5/m"}
path = "/middleware/async/"
result = get_rate_for_path(path, rate_limits, "2000/m")
print(f"Path: {path}")
print(f"Rate limits: {rate_limits}")
print(f"Result: {result}")

# Also test middleware initialization
from django_smart_ratelimit.middleware import RateLimitMiddleware


def dummy_response(request):
    return None


mw = RateLimitMiddleware(dummy_response)
print(f"\nMiddleware enabled: {mw.enabled}")
print(f"Middleware async_mode: {mw.async_mode}")
print(f"Middleware skip_paths: {mw.skip_paths}")
print(f"Middleware rate_limits: {mw.rate_limits}")
print(f"Middleware default_rate: {mw.default_rate}")
