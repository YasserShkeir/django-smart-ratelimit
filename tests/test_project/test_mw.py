import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "integration_test_project.settings")

import django

django.setup()

from django.http import JsonResponse
from django.test import RequestFactory

from django_smart_ratelimit.middleware import RateLimitMiddleware


def mock_view(request):
    return JsonResponse({"status": "ok"})


# Create middleware with mock response
middleware = RateLimitMiddleware(mock_view)

# Create a request
factory = RequestFactory()
request = factory.get("/middleware/async/")

print(f"Request path: {request.path}")
print(f"Middleware enabled: {middleware.enabled}")
print(f"Middleware async_mode: {middleware.async_mode}")

# Call middleware
try:
    response = middleware(request)
    print(f"\nResponse status: {response.status_code}")
    print(
        f"Response headers: {dict(response.headers) if hasattr(response, 'headers') else 'No headers attr'}"
    )
except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()
