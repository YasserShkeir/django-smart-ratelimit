"""Multi-tenant rate limiting (roadmap Phase 5.5).

Extracts a tenant identifier from a request (header, subdomain, JWT claim, or the
authenticated user), exposes a ``tenant_key`` key function, and resolves a
per-tenant rate from the optional :class:`TenantQuota` model. Designed to compose
with django-tenants (which sets ``request.tenant``) but does not require it.
"""

from typing import Any, Optional


def extract_tenant(request: Any) -> Optional[str]:
    """Extract a tenant id from a request.

    Resolution order: ``request.tenant`` (django-tenants) -> ``X-Tenant-ID``
    header -> the authenticated user's ``tenant_id`` attribute -> the first
    subdomain of the Host header. Returns ``None`` if nothing matches.
    """
    # django-tenants sets request.tenant (a model instance); use its schema/name.
    tenant_obj = getattr(request, "tenant", None)
    if tenant_obj is not None:
        return str(
            getattr(tenant_obj, "schema_name", None)
            or getattr(tenant_obj, "pk", None)
            or tenant_obj
        )

    headers = getattr(request, "headers", None)
    if headers is not None:
        header_value = headers.get("X-Tenant-ID")
        if header_value:
            return header_value

    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        tenant_id = getattr(user, "tenant_id", None)
        if tenant_id:
            return str(tenant_id)

    host = ""
    if headers is not None:
        host = headers.get("Host", "") or ""
    if not host:
        host = request.META.get("HTTP_HOST", "") if hasattr(request, "META") else ""
    host = host.split(":", 1)[0]  # strip port
    parts = host.split(".")
    if len(parts) >= 3:  # sub.domain.tld -> "sub"
        return parts[0]

    return None


def tenant_key(request: Any, *args: Any, **kwargs: Any) -> str:
    """Key function: bucket a request by its tenant (``tenant:<id>``)."""
    return f"tenant:{extract_tenant(request) or 'default'}"


def get_tenant_quota(tenant_id: Optional[str]) -> Optional[str]:
    """Return the active per-tenant rate for ``tenant_id``, or ``None``."""
    if not tenant_id:
        return None

    from .models import TenantQuota

    try:
        quota = TenantQuota.objects.get(tenant_id=tenant_id, is_active=True)
    except TenantQuota.DoesNotExist:
        return None
    return quota.rate


def resolve_tenant_rate(request: Any, default_rate: str) -> str:
    """Return the request's tenant quota rate, else ``default_rate``."""
    rate = get_tenant_quota(extract_tenant(request))
    return rate if rate is not None else default_rate
