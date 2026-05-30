# Migration Guide: v2.x → v3.0.0

django-smart-ratelimit 3.0.0 is a **mostly additive** major release. All
existing `@rate_limit(...)` and `RateLimitMiddleware` call-sites keep
working as-is. This guide covers the one behavioral change you should
verify and walks through the new features you may want to adopt.

## TL;DR

```bash
pip install django-smart-ratelimit==3.0.0
```

For 95% of deployments that's the entire migration. Read the **Breaking
change** section below to make sure you're not in the remaining 5%.

---

## Breaking change: empty keys now raise

**Before (v2.x):** a key function that returned `""` or `None` silently
worked — every matching request collapsed onto the same bucket.

**After (v3.0.0):** that path raises `KeyGenerationError` so the bug is
loud instead of silent.

### Why

An empty key meant every request shared a single rate-limit bucket. Under
load this looked like "my service is being rate-limited to nothing" even
though the intent was per-user limiting. We'd rather surface the config
bug than silently turn your limiter into a global kill-switch.

### What to do

Audit custom key functions and make sure they always return a
non-empty string:

```python
from django_smart_ratelimit.exceptions import RateLimitException

def key_for_authenticated_user(request):
    user_id = getattr(request.user, "id", None)
    if user_id is None:
        # Choose one of the two options below:
        return "anonymous"           # put all anons in the same bucket
        # raise RateLimitException   # skip rate limiting entirely
    return f"user:{user_id}"
```

If you have a bespoke pipeline that genuinely needs the old behavior,
call `resolve_effective_rate(..., validate_key=False)` from
`django_smart_ratelimit.pipeline`.

---

## New features you can opt into

All optional — your existing code runs unchanged without touching any of
these.

### Shadow mode (validate a new limit without blocking)

```python
from django_smart_ratelimit import rate_limit

@rate_limit(key="ip", rate="10/m", shadow=True)
def view(request):
    ...
```

Requests over the limit still succeed, but emit a structured log line
(`SHADOW_RATE_LIMIT_BLOCK`) and an OpenTelemetry attribute. Run this
for a day, inspect the logs, then flip `shadow=False`.

Middleware equivalent:

```python
RATELIMIT_MIDDLEWARE = {
    "DEFAULT_RATE": "100/m",
    "SHADOW": True,
}
```

### Cost-based (weighted) limiting

```python
@rate_limit(key="ip", rate="100/m", cost=5)
def expensive_op(request):
    ...

# Or dynamically:
@rate_limit(key="ip", rate="100/m", cost=lambda r: 5 if r.method == "POST" else 1)
def view(request):
    ...
```

`cost` is clamped to a minimum of 1, so you can't use `cost=0` to bypass
the limiter. Backends that don't natively support cost fall back to a
loop of single-token increments.

### CIDR allow/deny lists

```python
@rate_limit(
    key="ip",
    rate="100/m",
    allow_list=["10.0.0.0/8"],            # internal traffic, skip the limit
    deny_list=["/etc/ratelimit/block.txt"], # explicit blocks (deny wins)
)
def view(request):
    ...
```

Accepts:

- an `IPList` instance,
- an iterable of CIDR strings,
- a filesystem path to a file with one CIDR per line,
- a URL that returns the same.

Middleware equivalent:

```python
RATELIMIT_MIDDLEWARE = {
    "ALLOW_LIST": ["10.0.0.0/8"],
    "DENY_LIST": "https://internal/badguys.txt",
}
```

### DRF throttle adapter

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "django_smart_ratelimit.integrations.drf.UserRateLimitThrottle",
        "django_smart_ratelimit.integrations.drf.AnonRateLimitThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "1000/hour",
        "anon": "100/hour",
    },
}
```

Or subclass `SmartRateLimitThrottle` for full control.

### pytest fixtures

The `django-smart-ratelimit` package now registers a `pytest11` entry
point. Any test that `import django_smart_ratelimit.testing` (or just
runs in a project that depends on the package) picks up fixtures for
clearing backend state between tests.

### OpenTelemetry exporter

Install the optional dep:

```bash
pip install "django-smart-ratelimit[opentelemetry]"
```

Every rate-limit check emits a span (`ratelimit.check`) and metrics
(`ratelimit.requests`, `ratelimit.blocks`). Shadow decisions show up as
span attributes, not separate blocks.

### Shared evaluation pipeline

Third-party adapters can now reuse the same evaluation primitives the
built-in decorator uses:

```python
from django_smart_ratelimit import (
    POLICY_ALLOW, POLICY_DENY, POLICY_CONTINUE,
    apply_policy_lists, handle_shadow_decision, resolve_effective_rate,
)
```

See `django_smart_ratelimit/pipeline.py` for the full contract.

---

## Other behavior changes worth knowing

- **Reset times for first-request-aligned windows are now stable per key**
  inside a single process. Repeat callers in the same window see the
  same `X-RateLimit-Reset`. Clock-aligned reset times were already
  stable and are unchanged. No action needed; your `Retry-After`
  headers just got more honest.
- **Generic token-bucket fallback is now serialized within-process** via
  a per-key lock. For multi-process production use, backends must
  implement atomic `token_bucket_check` — this was already the expected
  contract, now it's documented explicitly in the algorithm source.
- **DRF `wait()` now returns a non-`None` value** on the throttled path,
  so clients get an accurate `Retry-After`.

---

## Questions, issues, regressions

Open an issue on GitHub: <https://github.com/YasserShkeir/django-smart-ratelimit/issues>

Please include the v2.x version you're upgrading from and a minimal
reproduction if you hit something unexpected.
