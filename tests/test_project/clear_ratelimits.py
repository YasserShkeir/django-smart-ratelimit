import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "integration_test_project.settings")
django.setup()

from django_smart_ratelimit.models import RateLimitEntry


def clear_limits():
    count, _ = RateLimitEntry.objects.all().delete()
    print(f"Deleted {count} rate limit entries.")


if __name__ == "__main__":
    clear_limits()
