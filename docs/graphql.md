# GraphQL Rate Limiting

`django-smart-ratelimit` can rate-limit GraphQL operations for both
[Graphene](https://graphene-python.org/) and
[Strawberry](https://strawberry.rocks/). It plugs in as a Graphene *middleware*
or a Strawberry *schema extension*, reuses your configured backend, and can
optionally weight the limit by query complexity so that expensive queries
consume more of the allowance.

Everything lives in `django_smart_ratelimit.graphql`. Graphene and Strawberry
are optional: the module imports nothing from either at load time, so it is safe
to import without them installed. The Strawberry extension imports Strawberry
lazily, only when you build it.

## Installation

The Graphene middleware needs Graphene:

```bash
pip install "django-smart-ratelimit[graphql]"
```

This pulls in `graphene>=3.0`. For Strawberry, install
[`strawberry-graphql`](https://strawberry.rocks/) yourself — it is not part of
the `graphql` extra. If you call `make_strawberry_extension()` without
Strawberry installed, it raises `django.core.exceptions.ImproperlyConfigured`.

## Graphene

Add `GrapheneRateLimitMiddleware` to the `middleware` list you pass to
`schema.execute()`:

```python
from django_smart_ratelimit.graphql import GrapheneRateLimitMiddleware

result = schema.execute(
    query,
    context=request,
    middleware=[GrapheneRateLimitMiddleware(rate="100/m")],
)
```

`GrapheneRateLimitMiddleware` accepts:

- `rate` — the limit string in `count/period` form (default `"60/m"`), e.g.
  `"100/m"`, `"1000/h"`. Periods are the same ones used everywhere else in the
  library (`s`, `m`, `h`, `d`).
- `key` — an optional callable `request -> str` that produces the limiter key.
  If omitted, the client IP is used (`django_smart_ratelimit.key_functions.get_ip_key`,
  which respects your proxy-trust settings).
- `complexity_cost` — `bool`, default `False`. When `True`, each operation is
  charged `estimate_query_complexity(query)` instead of `1`. See below.

### Only top-level operations are limited

The middleware checks the limit once per operation, on the top-level resolver
(`root is None`). Nested field resolvers are passed straight through and never
counted, so a query that selects many fields still costs a single increment (or
a single complexity-weighted increment). This keeps the count proportional to
the number of operations a client sends, not the number of resolvers Graphene
happens to invoke.

### Per-user keys

```python
from django_smart_ratelimit.graphql import GrapheneRateLimitMiddleware


def user_or_ip(request):
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return f"user:{user.pk}"
    from django_smart_ratelimit.key_functions import get_ip_key

    return get_ip_key(request)


middleware = [GrapheneRateLimitMiddleware(rate="200/m", key=user_or_ip)]
```

The `request` handed to your `key` function is taken from the execution
context: Graphene's `info.context` is the Django request itself.

### Handling the limit

When an operation is denied, the middleware raises
`GraphQLRateLimitExceeded`:

```python
from django_smart_ratelimit.graphql import GraphQLRateLimitExceeded

try:
    result = schema.execute(query, context=request, middleware=[...])
except GraphQLRateLimitExceeded:
    ...  # return a 429 or a GraphQL error to the client
```

Graphene surfaces resolver exceptions in `result.errors`, so depending on how
you run the schema you may also find the message
`"GraphQL rate limit exceeded. Try again later."` there.

## Strawberry

Build a schema extension with `make_strawberry_extension(rate, key)` and pass it
to your `strawberry.Schema`:

```python
import strawberry

from django_smart_ratelimit.graphql import make_strawberry_extension

schema = strawberry.Schema(
    query=Query,
    extensions=[make_strawberry_extension("100/m")],
)
```

`make_strawberry_extension` takes the same `rate` (default `"60/m"`) and
optional `key` callable as the Graphene middleware, and returns a Strawberry
`SchemaExtension` subclass. The extension runs `on_operation`, checking the
limit once per operation and raising `GraphQLRateLimitExceeded` when it is
exceeded.

Strawberry exposes the Django request on the context, so the `key` callable
receives the request whether your context is the request directly or an object
with a `.request` attribute.

```python
def by_tenant(request):
    return f"tenant:{request.headers.get('X-Tenant-ID', 'default')}"


schema = strawberry.Schema(
    query=Query,
    extensions=[make_strawberry_extension("500/m", key=by_tenant)],
)
```

> Note: the Strawberry extension applies a flat per-operation cost. Complexity
> weighting is currently available through the Graphene middleware only.

## Complexity-weighted limiting

`estimate_query_complexity(query)` returns a cheap, dependency-free estimate of
how expensive a query is. It counts the field-like identifiers in the query
(ignoring keywords such as `query`, `mutation`, `fragment`, `on`, `true`,
`false`, `null`) and adds a surcharge for nesting depth. The result is always at
least `1`; an empty string returns `1`.

```python
from django_smart_ratelimit.graphql import estimate_query_complexity

estimate_query_complexity("{ user { id } }")                 # small
estimate_query_complexity("query { a { b { c d } } posts { t } }")  # larger
```

Enable complexity weighting on the Graphene middleware so deep or wide queries
draw down the limit faster than trivial ones:

```python
from django_smart_ratelimit.graphql import GrapheneRateLimitMiddleware

middleware = [
    GrapheneRateLimitMiddleware(rate="1000/m", complexity_cost=True),
]
```

With `complexity_cost=True`, the cost charged for an operation is the estimated
complexity of its query rather than `1`. A `rate` of `"1000/m"` therefore means
"up to 1000 units of query complexity per minute" — a client can run many cheap
queries or fewer expensive ones, but not an unbounded number of large nested
queries.

You can also use `estimate_query_complexity` on its own to reject queries that
exceed a hard ceiling before they ever execute.

## Backend and keys

GraphQL limiting uses the same backend as the rest of the library (configured
via `RATELIMIT_BACKEND`); no extra configuration is required. Keys are stored
under a `graphql:` prefix, so they share a namespace with neither the decorator
nor the DRF integration. The default IP-based key honors
`RATELIMIT_TRUSTED_PROXIES` / `RATELIMIT_TRUST_FORWARDED_HEADERS` just like the
rest of the project.
