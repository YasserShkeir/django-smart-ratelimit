import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from django.contrib.auth.models import User


def create_test_user():
    username = "testuser"
    password = "password"
    email = "testuser@example.com"

    if not User.objects.filter(username=username).exists():
        user = User.objects.create_user(
            username=username, email=email, password=password
        )
        user.is_staff = True
        user.save()
        print(f"User '{username}' created and set as staff.")
    else:
        user = User.objects.get(username=username)
        if not user.is_staff:
            user.is_staff = True
            user.save()
            print(f"User '{username}' updated to staff.")
        else:
            print(f"User '{username}' already exists and is staff.")


if __name__ == "__main__":
    create_test_user()
