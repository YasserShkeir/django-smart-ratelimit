# Django Smart Ratelimit - Core Features Roadmap

**Last Updated:** 2026-06-03
**Current Version:** 4.5.0

This document tracks the feature status for Django Smart Ratelimit. The core library works with cache/memory backends out of the box and also ships an optional Django ORM (database) backend for SQL-backed persistence.

## Quick Status Overview

**Completed Features** (Core):

- In-Memory Backend
- Multi-Backend Support
- MongoDB Backend
- Token Bucket Algorithm
- Sliding Window Algorithm
- Fixed Window Algorithm
- Leaky Bucket Algorithm
- Circuit Breaker Pattern
- Health Checks
- Configuration Validation
- Async Support (Views and Decorators)
- Fail-Open Mechanism
- Database Backend (Django ORM)
- Adaptive Rate Limiting (Load-based)
- Type-Safe Enums
- Custom Response Handlers
- Custom Time Windows
- Prometheus Metrics
- Structured JSON Logging

**Completed Features** (Advanced, v4.x):

- Dynamic database-backed rules (Django Admin editable, hot-reloaded)
- User-aware limiting: tiers, Django-group mapping, per-user overrides
- API-key-aware limiting
- Analytics: event logging, traffic summaries, offender reporting, CSV export
- Staff analytics dashboard
- Geographic (per-country) rate limiting
- Multi-tenant rate limiting with per-tenant quotas
- GraphQL rate limiting (Graphene middleware, Strawberry extension)

**Next to Implement:**

1. [Batch Operations](#batch-operations) (Performance)
2. [Memcached Backend](#backends) (Backend adapter)

---

## Core Feature Categories

### Algorithms

- [x] **Token Bucket**: Standard burst-handling algorithm
- [x] **Sliding Window**: Precise time-window tracking
- [x] **Fixed Window**: Clock-aligned rate limiting windows
- [x] **Leaky Bucket**: Queue-based smoothing

### Backends

- [x] **Memory**: High-speed, local instance
- [x] **Redis**: Distributed, atomic (Lua scripts)
- [x] **MongoDB**: NoSQL distributed storage
- [x] **MultiBackend**: Failover chaining
- [x] **Database Backend**: Django ORM persistence (PostgreSQL, MySQL, SQLite)
- [ ] **Memcached**: Simple key-value store adapter (planned)

### Performance and Async

- [x] **Async Views**: Native `@aratelimit` decorator
- [x] **Async Redis**: `redis.asyncio` support
- [ ] **Batch Operations**: Pipelined checks for multiple keys
- [ ] **Connection Pooling**: Advanced Redis pool management options

### Reliability

- [x] **Circuit Breaker**: Auto-disable backends on failure
- [x] **Fail Open**: Configurable pass-through on error
- [x] **Health Checks**: `manage.py ratelimit_health`

### Monitoring and Observability

- [x] **Prometheus Metrics**: Expose `/metrics` endpoint for scraping
- [x] **OpenTelemetry**: Spans and metrics via `instrument_rate_limit()`
- [x] **Structured JSON Logging**: ELK/Datadog/Splunk-compatible log output

### Adaptive Rate Limiting

- [x] **Load Indicators**: CPU, memory, latency, connection count
- [x] **Adaptive Adjustment**: Dynamic rate limiting based on system metrics
- [x] **Custom Indicators**: Support for user-defined load metrics

### Dynamic and User-Aware Limiting

- [x] **Dynamic Rules**: Database-backed `RateLimitRule` model, editable in Django
      Admin and hot-reloaded via cache invalidation (opt-in,
      `RATELIMIT_USE_DYNAMIC_RULES`)
- [x] **User Tiers**: Named tiers with multipliers, Django-group mapping, and
      per-user overrides (opt-in, `RATELIMIT_USE_USER_TIERS`)
- [x] **API Keys**: API-key extraction, lookup, and per-key tiers

### Analytics and Reporting

- [x] **Event Logging**: Per-decision `RateLimitEvent` rows (opt-in,
      `RATELIMIT_LOG_EVENTS`), best-effort so logging never breaks a request
- [x] **Aggregations**: Traffic summary, top offenders, per-rule hit counts
- [x] **Dashboard**: Staff-only HTML dashboard plus CSV export view
- [x] **Retention**: `RateLimitEvent.cleanup_old()` for pruning history

### Multi-Tenant and Geographic

- [x] **Geographic Limiting**: `geo_key` country bucketing, per-country rates with
      a `"*"` wildcard, and a pluggable `GeoProvider` (MaxMind/GeoIP2 via the
      optional `geoip2` package, `RATELIMIT_GEOIP_PATH`)
- [x] **Multi-Tenant Limiting**: Tenant extraction (django-tenants, header, user,
      or subdomain), `tenant_key`, and per-tenant quotas via the `TenantQuota`
      model
- [x] **GraphQL Limiting**: Graphene middleware (top-level operations, optional
      complexity weighting), a Strawberry extension factory, and a
      dependency-free query-complexity estimator

### Configuration and Developer Experience

- [x] **Type-Safe Enums**: Algorithm and RateLimitKey enums
- [x] **Custom Response Handlers**: Per-decorator response callbacks
- [x] **Custom Time Windows**: Flexible window configuration

---

## Feature Status Overview

### Complete (v1.0.x)

The core library is feature-complete for production use. All essential rate limiting capabilities are implemented.

| Category | Features |
| --- | --- |
| **Algorithms** | Token Bucket, Sliding Window, Fixed Window |
| **Backends** | Memory, Redis, MongoDB, MultiBackend |
| **Reliability** | Circuit Breaker, Fail-Open, Health Checks |
| **Async** | Async Views, Async Middleware, Async Redis |
| **Developer Experience** | Decorator API, Middleware, Request Context, Key Functions, Headers |

### Complete (v2.0.0 - v2.2.0)

| Category | Features |
| --- | --- |
| **Monitoring** | Prometheus Metrics (built-in fallback + prometheus-client support) |
| **Logging** | Structured JSON Logging (ELK/Datadog/Splunk compatible) |
| **Algorithms** | Leaky Bucket |
| **Backends** | Database Backend (Django ORM) |
| **Adaptive** | Load-based adaptive rate limiting with custom indicators |
| **Developer Experience** | Type-Safe Enums, Custom Response Handlers, Custom Time Windows |

### Complete (v4.x)

These advanced capabilities are opt-in and self-contained; each is gated behind a
setting and/or optional extra, so they do not change default behavior or add hard
dependencies.

| Version | Category | Features |
| --- | --- | --- |
| **v4.2.0** | Dynamic config | Database-backed `RateLimitRule` model, Django Admin editing, rule engine with cache invalidation |
| **v4.3.0** | User integration | User tiers, Django-group mapping, per-user overrides, API-key tiers |
| **v4.4.0** | Analytics | Event logging, traffic/offender aggregations, staff dashboard, CSV export |
| **v4.5.0** | Geo / multi-tenant / GraphQL | Per-country limiting, per-tenant quotas, Graphene middleware + Strawberry extension |

---

## Future Enhancements

These features are planned for future releases. They are not blockers for current use.

### Low Priority

| Feature | Description | Rationale |
| --- | --- | --- |
| Memcached Backend | Simple key-value adapter | Redis/Memory cover most deployments |
| Batch Operations | Pipelined checks for multiple keys | Niche performance use case |
| Advanced Connection Pooling | Enterprise-scale Redis pool tuning | Default pooling covers most deployments |

---

## Architecture Decisions

### Backend Flexibility

The library is backend-agnostic: every backend implements the same `BaseBackend`
interface, so you can choose the storage that fits your deployment.

- **Cache/memory backends** (memory, Redis, async Redis, MongoDB) for fast,
  distributed rate limiting with no database involvement.
- **Database backend** (Django ORM) for deployments that prefer SQL persistence
  over running Redis. It ships its own models and migrations and supports
  PostgreSQL, MySQL, and SQLite.
- **MultiBackend** for failover chaining across the above.

> **Principle**: keep the core lightweight and gate optional integrations
> (Redis, MongoDB, DRF, Prometheus, OpenTelemetry, GeoIP, GraphQL) behind optional
> extras, while letting users pick the backend that matches their infrastructure.

### Opt-In Advanced Features

The advanced v4.x capabilities (dynamic rules, user tiers, analytics, geographic,
multi-tenant, and GraphQL limiting) follow the same principle: each is disabled by
default and activated by an explicit setting and/or an optional dependency extra.
Installing the base package and upgrading never changes behavior until a feature is
deliberately turned on.

---

## Contributing

We welcome contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup.

Contributions of all kinds are welcome: bug fixes, performance improvements, documentation improvements, and test coverage expansion.

For larger new features, please open a discussion first so we can agree on scope and where the feature fits.
