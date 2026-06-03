# Dynamic Rate-Limit Rules

Dynamic rules let you define and change rate limits at runtime, from the Django
admin or the ORM, without editing settings or redeploying. Rules are stored in
the database as `RateLimitRule` rows. When the rate-limit middleware handles a
request, it matches the request against the active rules and, if one matches,
uses that rule's `rate`, `key`, and `block` instead of the static
`RATELIMIT_MIDDLEWARE` configuration.

This is a middleware feature: it applies to requests flowing through
`RateLimitMiddleware`. It does not change the behavior of the `@rate_limit`
decorator.

## Setup

### 1. Add the app and run migrations

`RateLimitRule` is a Django model, so the app must be installed and its
migrations applied.

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django_smart_ratelimit",
]

MIDDLEWARE = [
    # ...
    "django_smart_ratelimit.middleware.RateLimitMiddleware",
]
```

```bash
python manage.py migrate
```

### 2. Enable dynamic rules

Dynamic rules are off by default. Turn them on with a single setting:

```python
# settings.py
RATELIMIT_USE_DYNAMIC_RULES = True

# Optional: how long (seconds) the active rule set is cached. Default 60.
RATELIMIT_RULE_CACHE_TIMEOUT = 60

# The middleware still needs its normal config; matching rules override it.
RATELIMIT_MIDDLEWARE = {
    "BACKEND": "redis",
    "DEFAULT_RATE": "1000/m",
}
```

With `RATELIMIT_USE_DYNAMIC_RULES = False` (the default), the middleware never
queries the rule table and behaves exactly as before.

## Defining a rule

You can create rules in the Django admin (the `RateLimitRule` admin is
registered automatically when the app is installed) or directly via the ORM.

```python
from django_smart_ratelimit.models import RateLimitRule

RateLimitRule.objects.create(
    name="api-strict",
    path_pattern=r"^/api/",   # regex matched against request.path
    method="ALL",             # or "GET,POST"
    rate="2/m",               # 2 requests per minute
    key="ip",                 # ip | user | header:X-API-Key
    algorithm="fixed_window",
    block=True,
    priority=10,
    is_active=True,
)
```

### Fields

| Field          | Type   | Default          | Description                                                                                                                |
| :------------- | :----- | :--------------- | :------------------------------------------------------------------------------------------------------------------------- |
| `name`         | str    | required, unique | Identifier for the rule. Also used in the rate-limit key (`rule:<name>:...`) and in recorded events.                       |
| `description`  | str    | `""`             | Free-text note for operators.                                                                                              |
| `path_pattern` | str    | required         | A regular expression matched against `request.path` with `re.search`, e.g. `^/api/`. Validated at save time.               |
| `method`       | str    | `"ALL"`          | `ALL`, or a comma-separated list of HTTP methods such as `GET,POST`. Case-insensitive.                                     |
| `rate`         | str    | required         | Rate string such as `100/m`, `1000/h`, or `10/30s`. Validated at save time.                                                |
| `key`          | str    | `"ip"`           | Per-client key: `ip`, `user` (falls back to IP for anonymous users), or `header:<Header-Name>` such as `header:X-API-Key`. |
| `algorithm`    | str    | `"fixed_window"` | One of `fixed_window`, `sliding_window`, `token_bucket`, `leaky_bucket`.                                                    |
| `block`        | bool   | `True`           | When `True`, requests over the limit get a `429`. When `False`, the limit is counted but not enforced.                     |
| `is_active`    | bool   | `True`           | Only active rules are loaded and matched. Inactive rules are ignored.                                                      |
| `priority`     | int    | `0`              | Higher priority wins when several rules match the same request.                                                            |

Both the admin save and `RateLimitRule.save()` run `full_clean()`, so an invalid
`rate` string or an invalid `path_pattern` regex raises a `ValidationError`
before the row is written.

## How matching and priority work

For each request, the middleware asks the rule engine for the single
highest-priority active rule that matches. A rule matches when:

1. `re.search(rule.path_pattern, request.path)` finds a match, and
2. the request's HTTP method is in `rule.method` (or the rule's method is `ALL`).

Active rules are ordered by `-priority` then `name`, so when several rules match
the same request, the one with the highest `priority` is applied. If no rule
matches, the request falls back to the static middleware configuration.

```python
RateLimitRule.objects.create(name="lo", path_pattern="^/api/", rate="9/m", priority=1)
RateLimitRule.objects.create(name="hi", path_pattern="^/api/", rate="1/m", priority=9)
# A GET /api/x request matches both; "hi" (priority 9) is applied -> 1/m.
```

## Overriding static config

When dynamic rules are enabled and a rule matches, that rule fully determines
the limit for the request: its `rate`, its `block` flag, and a key derived from
its `key` field. This overrides whatever the static `RATE_LIMITS` /
`DEFAULT_RATE` settings would have produced.

```python
# settings.py
RATELIMIT_USE_DYNAMIC_RULES = True
RATELIMIT_MIDDLEWARE = {"BACKEND": "memory", "DEFAULT_RATE": "1000/m"}
```

```python
# A rule scoped to /api/ at 2/m.
RateLimitRule.objects.create(
    name="api-strict", path_pattern=r"^/api/", rate="2/m", key="ip", priority=10
)
```

With the rule above, requests to `/api/...` are limited to `2/m` (the rule
wins), while requests to any other path still use the static `DEFAULT_RATE` of
`1000/m` (no rule matches, so the fallback applies).

Each rule gets its own counter namespace: the key the middleware uses is
`rule:<name>:<client>`, where `<client>` is the IP, `user:<pk>`, or the header
value, according to the rule's `key`. So two rules with overlapping path
patterns count independently.

## Caching and invalidation

Loading every active rule from the database on every request would be expensive,
so the rule engine caches the active rule set in process memory. The cache TTL
is `RATELIMIT_RULE_CACHE_TIMEOUT` seconds (default `60`).

Edits made through the ORM or the admin take effect immediately: the app wires
Django `post_save` and `post_delete` signals on `RateLimitRule` (from
`AppConfig.ready()`) so that saving or deleting a rule invalidates the cache.
The TTL is the upper bound on staleness for changes that bypass those signals
(for example a bulk `UPDATE` run directly against the database, or an edit made
in a different process/worker).

```python
# Editing a rule at runtime takes effect on the next request in this process.
rule = RateLimitRule.objects.get(name="api-strict")
rule.rate = "10/m"
rule.save()   # post_save signal invalidates the cache
```

If you need to drop the cache by hand:

```python
from django_smart_ratelimit.rules import rule_engine

rule_engine.invalidate_cache()
```

## Reloading rules manually

After a change that bypasses the model signals (a bulk DB import, a raw SQL
update, or an edit applied in another worker), invalidate the cache in this
process with the management command:

```bash
python manage.py ratelimit_reload_rules
```

It invalidates the rule cache so the next request reloads from the database, and
reports how many active rules there are:

```
Rate-limit rule cache reloaded (3 active rule(s)).
```

Note that, like the in-process cache itself, this affects only the process it
runs in. With multiple workers, rely on the per-process signal invalidation and
the `RATELIMIT_RULE_CACHE_TIMEOUT` TTL for changes to propagate everywhere, or
run the command (or restart) per worker.

## Managing rules in the admin

The `RateLimitRule` admin is registered automatically. It lists `name`,
`path_pattern`, `method`, `rate`, `key`, `algorithm`, `is_active`, and
`priority`, with `is_active` and `priority` editable inline. It also provides
two bulk actions, **Enable selected rules** and **Disable selected rules**,
which save each rule individually so the cache is invalidated.

The admin also exposes a read-only **Rate Limit Counter** view
(`RateLimitCounter`) for inspecting live fixed-window counters; these rows are
created by the limiter and cannot be added or edited by hand.
