"""URL patterns for the rate-limit analytics dashboard (Phase 4).

Include in your project's urls.py::

    path("ratelimit/", include("django_smart_ratelimit.urls"))
"""

from django.urls import path

from .views import RateLimitDashboardView, offenders_csv_view

app_name = "django_smart_ratelimit"

urlpatterns = [
    path("dashboard/", RateLimitDashboardView.as_view(), name="dashboard"),
    path("dashboard/offenders.csv", offenders_csv_view, name="offenders-csv"),
]
