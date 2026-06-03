"""GraphQL rate limiting (roadmap Phase 5.6).

A Graphene middleware and a Strawberry extension that rate-limit GraphQL
operations, plus a small query-complexity estimator for complexity-weighted
limits. Graphene/Strawberry are optional: nothing is imported at module load, so
this module is safe to import without either installed; the Strawberry extension
factory imports Strawberry lazily.
"""

import re
from typing import Any, Callable, Optional


class GraphQLRateLimitExceeded(Exception):
    """Raised when a GraphQL operation exceeds its rate limit."""


def estimate_query_complexity(query: str) -> int:
    """Estimate a GraphQL query's complexity.

    A cheap, dependency-free heuristic: the number of selected fields (identifiers
    inside selection sets), with a small surcharge for nesting depth. Useful as a
    ``cost`` so expensive queries consume more of the limit. Minimum 1.
    """
    if not query:
        return 1
    # Count field-like identifiers (skip arguments and the leading operation kw).
    fields = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query)
    keywords = {
        "query",
        "mutation",
        "subscription",
        "fragment",
        "on",
        "true",
        "false",
        "null",
    }
    field_count = sum(1 for f in fields if f not in keywords)
    depth = query.count("{")
    return max(1, field_count + depth)


def _request_from_context(context: Any) -> Any:
    """Extract the Django request from a GraphQL execution context."""
    # Graphene: info.context IS the request. Strawberry: context has .request.
    return getattr(context, "request", context)


def _check_rate(request: Any, key_value: str, rate: str, cost: int = 1) -> bool:
    """Increment the limiter for ``key_value`` by ``cost``; True if still allowed."""
    from .backends import get_backend
    from .backends.utils import parse_rate

    limit, period = parse_rate(rate)
    backend = get_backend()
    key = f"graphql:{key_value}"
    count = 0
    for _ in range(max(1, cost)):
        try:
            count = backend.incr(key, period, cost)  # type: ignore[call-arg]
            break
        except TypeError:
            count = backend.incr(key, period)
    return count <= limit


def _client_key(request: Any) -> str:
    from .key_functions import get_ip_key

    return get_ip_key(request)


class GrapheneRateLimitMiddleware:
    """Graphene middleware that rate-limits top-level operations.

    Add to your schema execution::

        schema.execute(query, middleware=[GrapheneRateLimitMiddleware(rate="100/m")])

    Only the top-level resolver (``root is None``) is limited, so nested field
    resolvers don't multiply the count. ``complexity_cost=True`` weights the
    limit by :func:`estimate_query_complexity`.
    """

    def __init__(
        self,
        rate: str = "60/m",
        key: Optional[Callable[[Any], str]] = None,
        complexity_cost: bool = False,
    ) -> None:
        """Configure the operation rate, key function, and complexity weighting."""
        self.rate = rate
        self.key = key
        self.complexity_cost = complexity_cost

    def resolve(self, next_: Callable, root: Any, info: Any, **args: Any) -> Any:
        """Limit the top-level operation, then delegate to the next resolver."""
        if root is None:
            request = _request_from_context(getattr(info, "context", None))
            key_value = self.key(request) if self.key else _client_key(request)
            cost = 1
            if self.complexity_cost:
                query = getattr(getattr(info, "operation", None), "loc", None)
                source = getattr(getattr(query, "source", None), "body", "") or ""
                cost = estimate_query_complexity(source)
            if not _check_rate(request, key_value, self.rate, cost):
                raise GraphQLRateLimitExceeded(
                    "GraphQL rate limit exceeded. Try again later."
                )
        return next_(root, info, **args)


def make_strawberry_extension(
    rate: str = "60/m", key: Optional[Callable[[Any], str]] = None
) -> Any:
    """Build a Strawberry ``SchemaExtension`` that rate-limits each operation.

    Imports Strawberry lazily so this module stays importable without it::

        schema = strawberry.Schema(query=Query,
                                   extensions=[make_strawberry_extension("100/m")])
    """
    try:
        from strawberry.extensions import SchemaExtension
    except ImportError as exc:  # pragma: no cover - optional dependency
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "GraphQL (Strawberry) rate limiting requires the 'strawberry-graphql' "
            "package."
        ) from exc

    class RateLimitExtension(SchemaExtension):
        """Strawberry extension applying a per-operation rate limit."""

        def on_operation(self) -> Any:
            context = getattr(self.execution_context, "context", None)
            request = _request_from_context(context)
            key_value = key(request) if key else _client_key(request)
            if not _check_rate(request, key_value, rate):
                raise GraphQLRateLimitExceeded(
                    "GraphQL rate limit exceeded. Try again later."
                )
            yield

    return RateLimitExtension
