# Multi-Tenant Rate Limiting

In a multi-tenant (SaaS) application every request belongs to a tenant, and you
usually want to give each tenant its own rate budget rather than a single global
one. The `django_smart_ratelimit.tenants` module resolves a tenant id from the
request, exposes a `tenant_key` key function so all of a tenant's traffic shares
one bucket, and resolves a per-tenant rate from the optional `TenantQuota` model.

It is designed to compose with [django-tenants](https://django-tenants.readthedocs.io/)
(which sets `request.tenant`) but does not require it — the resolver also reads a
header, the authenticated user, or the Host subdomain.

```python
from django_smart_ratelimit import tenants
```

## Tenant resolution

`extract_tenant(request)` returns the tenant id as a string, or `None` when no
source matches. Sources are tried in this fixed order, and the first match wins:

1. **`request.tenant`** — the model instance django-tenants attaches to the
   request. Its `schema_name` is used, falling back to its `pk`, then its
   `str()`.
2. **`X-Tenant-ID` header** — read from `request.headers`.
3. **`request.user.tenant_id`** — only for authenticated users, when the user
   model carries a `tenant_id` attribute.
4. **Host subdomain** — the first label of the Host header when it has at least
   three labels (`acme.example.com` -> `acme`). The port is stripped first.

```python
from django_smart_ratelimit import tenants

tenants.extract_tenant(request)   # -> "acme", or None if nothing matches
```

A bare domain with no subdomain (`example.com`) and an unauthenticated request
with no header both resolve to `None`.

## tenant_key as a key function

`tenant_key` is a key function with the standard `(request, *args, **kwargs)`
signature, so you can pass it directly to the `@rate_limit` decorator or to a
backend call. It buckets every request by its tenant as `tenant:<id>`, and falls
back to `tenant:default` when no tenant can be resolved.

```python
from django_smart_ratelimit import rate_limit, tenants

@rate_limit(key=tenants.tenant_key, rate="1000/h")
def api_view(request):
    ...
```

```python
tenants.tenant_key(request)   # "tenant:acme"  (or "tenant:default")
```

This gives every tenant the same limit. To give tenants *different* limits, see
per-tenant quotas below.

## Per-tenant quotas

`TenantQuota` stores a rate string per tenant in the database, so you can change
a tenant's budget at runtime without a redeploy.

```python
from django_smart_ratelimit.models import TenantQuota

TenantQuota.objects.create(tenant_id="acme", rate="500/h")
```

Fields:

| Field        | Type      | Notes                                                     |
| :----------- | :-------- | :-------------------------------------------------------- |
| `tenant_id`  | `str`     | Unique, indexed. Matches the value from `extract_tenant`. |
| `rate`       | `str`     | Rate string, e.g. `"1000/h"`, `"100/m"`, `"10/30s"`.      |
| `is_active`  | `bool`    | Defaults to `True`. Inactive quotas are ignored.          |
| `created_at` | datetime  | Auto-set on creation.                                     |
| `updated_at` | datetime  | Auto-updated on save.                                     |

The `rate` string is validated on `save()` (via `full_clean()`), so an invalid
value like `"nope"` raises `django.core.exceptions.ValidationError` before it
ever reaches the database.

### Resolving a tenant's rate

`resolve_tenant_rate(request, default_rate)` extracts the tenant from the request,
looks up its active quota, and returns that rate — or `default_rate` when the
tenant has no active quota (or no tenant could be resolved).

```python
from django_smart_ratelimit import tenants

# With TenantQuota(tenant_id="acme", rate="500/h") active:
tenants.resolve_tenant_rate(request_for_acme, "100/m")   # -> "500/h"
tenants.resolve_tenant_rate(request_no_tenant, "100/m")  # -> "100/m"
```

`get_tenant_quota(tenant_id)` is the lower-level lookup if you already have the
id. It returns the active quota's rate string, or `None`:

```python
tenants.get_tenant_quota("acme")    # -> "500/h"
tenants.get_tenant_quota("ghost")   # -> None  (no active quota)
tenants.get_tenant_quota(None)      # -> None
```

### Applying per-tenant rates

Because `resolve_tenant_rate` needs the request to pick the rate, combine it with
`tenant_key` inside your own view or wrapper rather than as a static decorator
argument. A simple pattern:

```python
from django.http import HttpResponse

from django_smart_ratelimit import rate_limit, tenants


def api_view(request):
    rate = tenants.resolve_tenant_rate(request, "100/m")

    @rate_limit(key=tenants.tenant_key, rate=rate)
    def _limited(request):
        return HttpResponse("ok")

    return _limited(request)
```

`tenant_key` keeps each tenant in its own `tenant:<id>` bucket while
`resolve_tenant_rate` decides how large that bucket is for the current tenant.

## Composing with django-tenants

When django-tenants is installed and its middleware runs, it attaches the active
tenant model to `request.tenant`. Because that is the first source `extract_tenant`
checks, no extra configuration is needed — `tenant_key` and `resolve_tenant_rate`
pick up the django-tenants tenant automatically.

Make sure the django-tenants middleware runs **before** any rate-limit middleware
or view so that `request.tenant` is already set when the tenant is resolved. The
`schema_name` of the tenant model is used as the id, so a `TenantQuota.tenant_id`
should match the tenant's schema name:

```python
from django_smart_ratelimit.models import TenantQuota

# tenant whose django-tenants schema_name is "acme"
TenantQuota.objects.create(tenant_id="acme", rate="2000/h")
```

If django-tenants is not installed, nothing changes — resolution simply falls
through to the header, user, and subdomain sources.

## Admin

`TenantQuota` is registered in the Django admin (via
`django_smart_ratelimit.admin`), so operators can create and adjust quotas
without code. The list view shows `tenant_id`, `rate`, `is_active`, and
`updated_at`; `rate` and `is_active` are editable inline; and you can filter by
`is_active` and search by `tenant_id`.

Edits validate the `rate` string on save (the same `full_clean()` check as the
ORM), so an invalid rate is rejected in the admin form.

## See also

- [Decorator](decorator.md) — passing a callable as the `key` argument.
- [Utilities](utilities.md) — `get_tenant_key`, a separate key function that
  reads a configurable user/header/query field and prefixes the per-user bucket
  with the tenant id (distinct from this module's `tenant_key`).
- [Observability](observability.md) — exporting check outcomes to your monitoring
  stack.
