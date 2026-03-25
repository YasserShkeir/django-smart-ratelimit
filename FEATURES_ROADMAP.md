# Django Smart Ratelimit - Core Features Roadmap

**Last Updated:** 2026-01-19
**Current Version:** 1.0.3

This document tracks the feature status for **Django Smart Ratelimit (Core)**.
For database-backed features, analytics, and enterprise capabilities, see the [Pro Roadmap](../django-smart-ratelimit-pro/FEATURES_ROADMAP.md).

## Quick Status Overview

**Completed Features** (Core)

- â In-Memory Backend
- â Multi-Backend Support
- â MongoDB Backend
- â Token Bucket Algorithm
- â Circuit Breaker Pattern
- â Health Checks
- â Configuration Validation
- â Async Support (Views & Decorators)
- â Fail-Open Mechanism
- â Leaky Bucket Algorithm
- â Database Backend (Django ORM)
- â Adaptive Rate Limiting (Load-based)
- â Type-Safe Enums
- â Custom Response Handlers
- â Custom Time Windows

**High Priority - Next to Implement**

1. [Batch Operations](#batch-operations) (Performance)
2. [Prometheus Metrics](#prometheus-metrics) (Stateless Monitoring)

## Core Feature Categories

### ð§  Algorithms

- [x] **Token Bucket**: Standard burst-handling algorithm.
- [x] **Sliding Window**: Precise time-window tracking.
- [x] **Leaky Bucket**: Queue-based smoothing.

### ð­ Backends (Stateless)

- [x] **Memory**: High-speed, local instance.
- [x] **Redis**: Distributed, atomic (Lua scripts).
- [x] **MongoDB**: NoSQL distributed storage.
- [x] **MultiBackend**: Failover chaining.
- [x] **Database Backend**: Django ORM for persistence.
- [ ] **Memcached**: Simple key-value store adapter (Planned).

### â¡ Performance & Async

- [x] **Async Views**: Native `@aratelimit` decorator.
- [x] **Async Redis**: `redis.asyncio` support.
- [ ] **Batch Operations**: Pipelined checks for multiple keys.
- [ ] **Connection Pooling**: Advanced Redis pool management options.

### ð¡ï¸ Reliability

- [x] **Circuit Breaker**: Auto-disable backends on failure.
- [x] **Fail Open**: Configurable pass-through on error.
- [x] **Health Checks**: `manage.py ratelimit_health`.

### ð Stateless Monitoring

- [ ] **Prometheus Metrics**: Expose `/metrics` endpoint for scraper (no database req).
- [ ] **Standard Logging**: Structured JSON logging for ELK stacks.

### ð¯ Adaptive Rate Limiting

- [x] **Load Indicators**: CPU, Memory, Latency, Connection Count.
- [x] **Adaptive Adjustment**: Dynamic rate limiting based on system metrics.
- [x] **Custom Indicators**: Support for user-defined load metrics.

### ð Configuration & Developer Experience

- [x] **Type-Safe Enums**: Algorithm and RateLimitKey enums.
- [x] **Custom Response Handlers**: Per-decorator response callbacks.
- [x] **Custom Time Windows**: Flexible window configuration.

---

## Feature Status Overview

### â Complete (v1.0.x)

The Core library is **feature-complete** for production use. All essential rate limiting capabilities are implemented.

| Category                 | Features                                                           |
| ------------------------ | ------------------------------------------------------------------ |
| **Algorithms**           | Token Bucket, Sliding Window, Fixed Window                         |
| **Backends**             | Memory, Redis, MongoDB, MultiBackend                               |
| **Reliability**          | Circuit Breaker, Fail-Open, Health Checks                          |
| **Async**                | Async Views, Async Middleware, Async Redis                         |
| **Developer Experience** | Decorator API, Middleware, Request Context, Key Functions, Headers |

---

## Core Feature Details

### ð§  Algorithms

| Algorithm      | Status      | Description                                  |
| -------------- | ----------- | -------------------------------------------- |
| Token Bucket   | â Complete | Burst-handling with configurable refill rate |
| Sliding Window | â Complete | Precise time-window tracking                 |
| Fixed Window   | â Complete | Clock-aligned rate limiting windows          |

### ð­ Backends (Stateless)

| Backend      | Status      | Description                                    |
| ------------ | ----------- | ---------------------------------------------- |
| Memory       | â Complete | High-speed local instance with cleanup threads |
| Redis        | â Complete | Distributed, atomic Lua scripts, async support |
| MongoDB      | â Complete | NoSQL distributed storage with TTL indexes     |
| MultiBackend | â Complete | Failover chaining with health monitoring       |

### ð¡ï¸ Reliability

| Feature         | Status      | Description                          |
| --------------- | ----------- | ------------------------------------ |
| Circuit Breaker | â Complete | Auto-disable failing backends        |
| Fail-Open       | â Complete | Configurable pass-through on errors  |
| Health Checks   | â Complete | `manage.py ratelimit_health` command |

### â¡ Performance & Async

| Feature          | Status      | Description                             |
| ---------------- | ----------- | --------------------------------------- |
| Async Views      | â Complete | `@aratelimit` decorator for async views |
| Async Middleware | â Complete | Full ASGI support                       |
| Async Redis      | â Complete | `redis.asyncio` integration             |

### ð§ Developer Experience

| Feature          | Status      | Description                      |
| ---------------- | ----------- | -------------------------------- |
| Decorator API    | â Complete | `@rate_limit` / `@ratelimit`     |
| Middleware       | â Complete | Global rate limiting             |
| Request Context  | â Complete | `request.ratelimit` object       |
| Key Functions    | â Complete | 10+ built-in key generators      |
| Response Headers | â Complete | `X-RateLimit-*` standard headers |
| Configuration    | â Complete | Django settings integration      |

---

## Future Enhancements (v2.x+)

These features are **nice-to-have** and may be implemented in future major versions. They are not blockers for current use.

### Low Priority

| Feature                 | Description                   | Rationale                              |
| ----------------------- | ----------------------------- | -------------------------------------- |
| Leaky Bucket Algorithm  | Queue-based request smoothing | Token Bucket covers most use cases     |
| Memcached Backend       | Simple key-value adapter      | Redis/Memory cover most deployments    |
| Prometheus Metrics      | Stateless `/metrics` endpoint | Can be added via middleware externally |
| Structured JSON Logging | ELK-compatible log format     | Standard Python logging works          |

### Moved to Pro

The following features were originally planned for Core but are better suited for **Pro** due to their enterprise/stateful nature:

| Feature                     | Reason for Pro                                 |
| --------------------------- | ---------------------------------------------- |
| Batch Operations            | Complex use case, enterprise performance needs |
| Adaptive Rate Limiting      | Requires state/analytics to adjust rates       |
| Advanced Connection Pooling | Enterprise-scale configuration                 |

---

## Architecture Decisions

### Core vs Pro Separation

**Core (Open Source):**

- Stateless rate limiting
- In-memory and cache-based backends
- Algorithm implementations
- Basic reliability (circuit breaker, fail-open)

**Pro (Enterprise):**

- Database-backed persistence
- Dynamic configuration via Admin
- User tier integration
- Analytics and dashboards
- Multi-tenant support

> **Principle**: Core should have zero database dependencies and work purely with cache/memory backends.

---

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for setup.

For Core contributions:

- Bug fixes and performance improvements
- Documentation improvements
- Test coverage expansion

For new features, please open a discussion first to determine if it belongs in Core or Pro.
