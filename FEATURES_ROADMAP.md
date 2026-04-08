# Django Smart Ratelimit - Core Features Roadmap

**Last Updated:** 2026-04-08
**Current Version:** 2.2.1

This document tracks the feature status for Django Smart Ratelimit (Core). For database-backed features, analytics, and enterprise capabilities, see the [Pro Roadmap](../django-smart-ratelimit-pro/FEATURES_ROADMAP.md).

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

**Next to Implement:**

1. [Batch Operations](#batch-operations) (Performance)

---

## Core Feature Categories

### Algorithms

- [x] **Token Bucket**: Standard burst-handling algorithm
- [x] **Sliding Window**: Precise time-window tracking
- [x] **Fixed Window**: Clock-aligned rate limiting windows
- [x] **Leaky Bucket**: Queue-based smoothing

### Backends (Stateless)

- [x] **Memory**: High-speed, local instance
- [x] **Redis**: Distributed, atomic (Lua scripts)
- [x] **MongoDB**: NoSQL distributed storage
- [x] **MultiBackend**: Failover chaining
- [x] **Database Backend**: Django ORM for persistence
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

### Stateless Monitoring

- [x] **Prometheus Metrics**: Expose `/metrics` endpoint for scraping (no database required)
- [x] **Structured JSON Logging**: ELK/Datadog/Splunk-compatible log output

### Adaptive Rate Limiting

- [x] **Load Indicators**: CPU, memory, latency, connection count
- [x] **Adaptive Adjustment**: Dynamic rate limiting based on system metrics
- [x] **Custom Indicators**: Support for user-defined load metrics

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

---

## Future Enhancements (v2.x+)

These features are planned for future releases. They are not blockers for current use.

### Low Priority

| Feature | Description | Rationale |
| --- | --- | --- |
| Memcached Backend | Simple key-value adapter | Redis/Memory cover most deployments |

### Moved to Pro

The following features were originally planned for Core but are better suited for Pro due to their enterprise/stateful nature:

| Feature | Reason for Pro |
| --- | --- |
| Batch Operations | Complex use case, enterprise performance needs |
| Advanced Connection Pooling | Enterprise-scale configuration |

---

## Architecture Decisions

### Core vs Pro Separation

**Core (Open Source):**

- Stateless rate limiting
- In-memory and cache-based backends
- Algorithm implementations
- Basic reliability (circuit breaker, fail-open)
- Prometheus metrics and structured logging

**Pro (Enterprise):**

- Database-backed persistence
- Dynamic configuration via Admin
- User tier integration
- Analytics and dashboards
- Multi-tenant support

> **Principle**: Core should have zero database dependencies and work purely with cache/memory backends.

---

## Contributing

We welcome contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup.

For core contributions: bug fixes, performance improvements, documentation improvements, and test coverage expansion.

For new features, please open a discussion first to determine if it belongs in Core or Pro.
