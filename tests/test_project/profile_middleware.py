import cProfile
import os
import pstats

import django
from django.http import HttpResponse
from django.test import RequestFactory

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "integration_test_project.settings")
django.setup()

from django_smart_ratelimit.middleware import RateLimitMiddleware


def get_response(request):
    return HttpResponse("OK")


# Initialize middleware
try:
    middleware = RateLimitMiddleware(get_response)
    factory = RequestFactory()

    print("Starting profiling...")

    def run_profile():
        # Create a request
        request = factory.get("/ratelimit_demo/ip/")

        # Warm up (and hit the limit potentially)
        middleware(request)

        # Profile 1000 requests
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(1000):
            middleware(request)
        pr.disable()

        # Print stats
        ps = pstats.Stats(pr).sort_stats("cumulative")
        print("\nTop 15 cumulatively time-consuming functions:")
        ps.print_stats(15)

    if __name__ == "__main__":
        run_profile()

except Exception as e:
    print(f"Error: {e}")
