# DRF API throttling

Throttle a Django REST Framework view using the throttle classes shipped in
`django_smart_ratelimit.integrations.drf`. Authenticated users get a generous
limit; anonymous traffic gets a tighter one.

Requires: `pip install "django-smart-ratelimit[drf]"`

- `settings.py` — wire the throttle classes and their rates into DRF.
- `views.py` — a view that uses `throttle_classes` (and a scoped variant).

See the full guide in [`docs/drf.md`](../../docs/drf.md).
