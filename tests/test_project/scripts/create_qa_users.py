import os
import sys

import django

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "integration_test_project.settings")
django.setup()

from django.contrib.auth.models import User


def create_user(username):
    if not User.objects.filter(username=username).exists():
        u = User.objects.create_user(
            username=username, email=f"{username}@example.com", password="password"
        )
        u.is_staff = True
        u.save()
        print(f"Created {username} (is_staff=True)")
    else:
        u = User.objects.get(username=username)
        if not u.is_staff:
            u.is_staff = True
            u.save()
            print(f"Updated {username} to staff")
        else:
            print(f"User {username} exists")


if __name__ == "__main__":
    create_user("testuser")
    create_user("testuser2")
