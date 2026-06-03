# User-Aware Rate Limiting

`django-smart-ratelimit` can adjust a request's limit to the authenticated user
behind it: a named **tier** (e.g. free / premium), the user's **Django groups**,
a temporary **per-user override**, or the tier attached to an **API key**.

When enabled, an authenticated user is limited at *their* effective rate and in
their *own* bucket, so two users sharing a key (such as an IP) never compete for
the same budget. Anonymous requests are unaffected and fall through to the base
rate.

This is the roadmap Phase 3 / v4.3.0 feature set; the `@rate_limit` decorator
reached parity with the middleware in v4.6.0, which also added the `tier_key`
key function and the `create_user_override` helper.

## Enabling

The feature is off by default. Turn it on with a single Django setting:

```python
# settings.py
RATELIMIT_USE_USER_TIERS = True
```

This is read by both the middleware and the decorator. With it off, every
symbol on this page still imports and runs, but limiting behaves exactly as it
did before (no tier, override, or per-user bucketing is applied).

The models live in the app, so make sure migrations are applied:

```bash
python manage.py migrate django_smart_ratelimit
```

All five models (`UserTier`, `UserTierAssignment`, `GroupRateLimit`,
`UserRateLimitOverride`, `APIKey`) are registered in the Django admin, so most
day-to-day management can happen there.

## Precedence

For an authenticated request, the effective rate is resolved in this order
(`resolve_effective_user_rate`):

1. **An active per-user override** (`UserRateLimitOverride`) — highest priority.
2. **The user's tier** (`UserTier`) — from an explicit `UserTierAssignment` if
   present and not expired, otherwise from the highest-priority tier mapped to
   one of the user's Django groups. The tier is applied to the base rate.
3. **The base rate**, unchanged — if neither of the above applies.

## Tiers

A `UserTier` either scales the base rate by `rate_multiplier` or replaces it
outright per scope via `explicit_limits`. An explicit limit for the active scope
always wins; otherwise the base limit is scaled (rounded, minimum 1).

```python
from django_smart_ratelimit.models import UserTier, UserTierAssignment
from django.contrib.auth import get_user_model

User = get_user_model()

# A multiplier tier: 3x the base limit everywhere.
premium = UserTier.objects.create(name="premium", rate_multiplier=3.0)

# An explicit-limits tier: fixed per-scope limits, 2x elsewhere.
enterprise = UserTier.objects.create(
    name="enterprise",
    rate_multiplier=2.0,
    explicit_limits={"api": "5000/h", "upload": "100/d"},
)

# Assign a user to a tier (optionally with an expiry).
user = User.objects.get(username="alice")
UserTierAssignment.objects.create(user=user, tier=premium)
```

`apply_tier_to_rate` shows the resolution rules directly:

```python
from django_smart_ratelimit.tiers import apply_tier_to_rate

apply_tier_to_rate("10/m", premium)            # "30/60s"  (multiplier)
apply_tier_to_rate("10/m", enterprise, "api")  # "5000/h"  (explicit scope wins)
apply_tier_to_rate("10/m", None)               # "10/m"    (no tier -> unchanged)
```

A `UserTierAssignment` is a one-to-one link (`user.ratelimit_tier`). If it has an
`expires_at` in the past, it is ignored and resolution falls back to the user's
groups.

`UserTier.priority` breaks ties: when a user resolves to several tiers (e.g.
through multiple groups), the highest-priority tier wins.

`get_user_tier(user)` returns the effective tier (explicit assignment first,
then groups), or `None` for anonymous users and users with no tier.

## Group-based tiers

Map a Django `auth.Group` to a tier with `GroupRateLimit`. Any user in that
group inherits the tier (unless they have an explicit assignment, which takes
priority). When a user belongs to several mapped groups, the tier with the
highest `priority` is chosen.

```python
from django.contrib.auth.models import Group
from django_smart_ratelimit.models import GroupRateLimit, UserTier

vip = UserTier.objects.create(name="vip", rate_multiplier=5.0, priority=10)
group = Group.objects.create(name="vips")
GroupRateLimit.objects.create(group=group, tier=vip)

# Now every member of "vips" resolves to the vip tier.
user.groups.add(group)
```

`GroupRateLimit.tier` is optional (it may be `None`); only group configs that
point at a tier participate in resolution.

## Per-user overrides

A `UserRateLimitOverride` grants a specific user a custom rate for a bounded
window. It outranks any tier. A scope-specific override (matching `rule_name`)
beats a blank one (`rule_name=""`, which applies to all scopes).

Create one programmatically with `create_user_override` — a convenience wrapper
around the model that validates the rate and computes the expiry for you:

```python
from django_smart_ratelimit.tiers import create_user_override

# Applies to everything for ~1 hour by default.
create_user_override(user, "50/h", reason="support ticket")

# Scoped to a single rule/endpoint, for a fixed duration.
create_user_override(user, "10/m", scope="upload", duration_seconds=60)

# Or pin an absolute expiry instead of a duration.
from django.utils import timezone
from datetime import timedelta
create_user_override(
    user, "1000/h", expires_at=timezone.now() + timedelta(days=7)
)
```

Signature:

```python
create_user_override(
    user,
    rate,
    *,
    scope="",              # maps to the override's rule_name; "" = all scopes
    duration_seconds=None, # relative to now; defaults to 3600 if neither given
    expires_at=None,       # absolute expiry; provide this OR duration_seconds
    reason="",
    created_by=None,
)
```

`scope` maps to the model's `rule_name`. Provide at most one of
`duration_seconds` or `expires_at`; if neither is given the override lasts one
hour. An invalid `rate` raises `django.core.exceptions.ValidationError` before
any row is written.

You can also create the row directly via the ORM or the admin:

```python
from django_smart_ratelimit.models import UserRateLimitOverride
from django.utils import timezone
from datetime import timedelta

UserRateLimitOverride.objects.create(
    user=user,
    rate="999/m",
    rule_name="",  # blank = all scopes
    expires_at=timezone.now() + timedelta(hours=1),
)
```

`get_user_override(user, scope="")` returns the active override's rate string (or
`None`), applying the scope-then-blank fallback.

## How it applies (middleware and decorator)

When `RATELIMIT_USE_USER_TIERS` is on, both entry points run the same
resolution and bucketing for an authenticated user:

- the rate becomes the user's effective rate (override → tier → base), and
- the key becomes per-user (`user:<pk>:<scope-or-key>`), so users at different
  tiers behind a shared key are limited independently.

Nothing changes for your call sites — you write your usual rules and the
adjustment happens underneath.

**Middleware** (handled by `_maybe_apply_tiers`):

```python
# settings.py
RATELIMIT_USE_USER_TIERS = True
RATELIMIT_MIDDLEWARE = {"BACKEND": "redis", "DEFAULT_RATE": "100/m"}
```

A premium user (`rate_multiplier=3.0`) against a `100/m` rule is allowed `300/m`,
in their own bucket.

**Decorator** (v4.6.0, handled by `_apply_user_tiers`):

```python
from django.http import HttpResponse
from django_smart_ratelimit import rate_limit

@rate_limit(key="ip", rate="2/m")
def my_view(request):
    return HttpResponse("ok")
```

With the setting on, an authenticated premium user hitting this view gets `6/m`
even though the rule says `2/m`, and is bucketed by user rather than by IP. An
anonymous request still gets the plain `2/m` base rate.

## Bucketing by tier with `tier_key`

The above gives each user their own bucket. If instead you want everyone in the
same tier to *share* one budget, use the `tier_key` key function:

```python
from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.tiers import tier_key

@rate_limit(key=tier_key, rate="1000/m")
def shared_pool(request):
    ...
```

`tier_key` returns:

- `tier:anonymous` for unauthenticated requests,
- `tier:default` for authenticated users with no resolved tier,
- `tier:<name>` otherwise (e.g. `tier:premium`).

There is a matching `group_key` in `django_smart_ratelimit.groups` that buckets
by the user's sorted group names (`group:<a,b>`, or `group:anonymous`).

## API-key tiers

Attach a tier to an `APIKey` to give keyed clients a limit independent of any
logged-in user.

```python
from django_smart_ratelimit.models import APIKey, UserTier

api_tier = UserTier.objects.create(name="api-gold", rate_multiplier=4.0)
APIKey.objects.create(key="live_abc123", name="Acme prod", tier=api_tier)
```

`extract_api_key(request)` pulls a key from the request, checking in order:

1. the `X-API-Key` header,
2. an `api_key` query parameter,
3. a `Bearer` token in the `Authorization` header.

Bucket requests by their API key with the `api_key_key` key function (it falls
back to the client IP when no key is present):

```python
from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.api_keys import api_key_key

@rate_limit(key=api_key_key, rate="1000/h")
def api_view(request):
    ...
```

`api_key_key` returns `api_key:<key>` when a key is found, otherwise the IP key.

Supporting helpers in `django_smart_ratelimit.api_keys`:

- `get_api_key_record(key, touch=False)` — the active `APIKey` row for a key (or
  `None`); pass `touch=True` to update `last_used_at`.
- `get_api_key_tier(request)` — the `UserTier` attached to the request's API key,
  or `None`.

```python
from django_smart_ratelimit.api_keys import get_api_key_tier
from django_smart_ratelimit.tiers import apply_tier_to_rate

tier = get_api_key_tier(request)          # UserTier or None
rate = apply_tier_to_rate("100/h", tier)  # scaled by the key's tier
```

> Note: the middleware/decorator integration described above resolves tiers from
> the authenticated **user**. API-key tiers are exposed through the key function
> and helpers, so combine `api_key_key` with `get_api_key_tier` /
> `apply_tier_to_rate` when you want a key's tier to also change its rate.
