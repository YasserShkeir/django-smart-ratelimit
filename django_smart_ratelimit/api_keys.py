"""API-key extraction, lookup, and a key function for API-key limiting (Phase 3).

Works with the optional :class:`~django_smart_ratelimit.models.APIKey` model, or
purely on the raw key string when you manage keys elsewhere.
"""

from typing import Any, Optional


def extract_api_key(request: Any) -> Optional[str]:
    """Extract an API key from a request.

    Checks, in order: the ``X-API-Key`` header, an ``api_key`` query parameter,
    and a ``Bearer`` ``Authorization`` token.
    """
    headers = getattr(request, "headers", None)
    if headers is not None:
        key = headers.get("X-API-Key")
        if key:
            return key
    else:  # pragma: no cover - very old request objects without .headers
        key = request.META.get("HTTP_X_API_KEY")
        if key:
            return key

    get = getattr(request, "GET", None)
    if get is not None:
        key = get.get("api_key")
        if key:
            return key

    auth = ""
    if headers is not None:
        auth = headers.get("Authorization", "") or ""
    else:  # pragma: no cover
        auth = request.META.get("HTTP_AUTHORIZATION", "") or ""
    if auth.startswith("Bearer "):
        return auth[7:]

    return None


def get_api_key_record(key: str, touch: bool = False) -> Optional[Any]:
    """Return the active :class:`APIKey` row for ``key``, or ``None``.

    If ``touch`` is True, update ``last_used_at`` (without bumping ``updated``
    semantics elsewhere).
    """
    if not key:
        return None

    from .models import APIKey

    try:
        record = APIKey.objects.select_related("tier").get(key=key, is_active=True)
    except APIKey.DoesNotExist:
        return None

    if touch:
        from django.utils import timezone

        APIKey.objects.filter(pk=record.pk).update(last_used_at=timezone.now())

    return record


def api_key_key(request: Any, *args: Any, **kwargs: Any) -> str:
    """Key function: bucket a request by its API key (falls back to IP)."""
    key = extract_api_key(request)
    if key:
        return f"api_key:{key}"
    from .key_functions import get_ip_key

    return get_ip_key(request)


def get_api_key_tier(request: Any) -> Optional[Any]:
    """Return the :class:`UserTier` for the request's API key, or ``None``."""
    key = extract_api_key(request)
    if not key:
        return None
    record = get_api_key_record(key)
    return getattr(record, "tier", None) if record is not None else None
