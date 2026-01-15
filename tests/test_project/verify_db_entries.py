import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from django_smart_ratelimit.models import RateLimitEntry


def verify_entries():
    count = RateLimitEntry.objects.count()
    print(f"RateLimitEntry count: {count}")
    if count > 0:
        print("[PASS] RateLimitEntry objects found.")
        return True
    else:
        print("[FAIL] No RateLimitEntry objects found.")
        return False


if __name__ == "__main__":
    if verify_entries():
        sys.exit(0)
    else:
        sys.exit(1)
