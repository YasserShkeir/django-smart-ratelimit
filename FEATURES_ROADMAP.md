# Django Smart Ratelimit - Core Features Roadmap

**Last Updated:** 2026-03-26
**Current Version:** 2.2.0

This document tracks the feature status for **Django Smart Ratelimit (Core)**. For database-backed features, analytics, and enterprise capabilities, see the [Pro Roadmap](../django-smart-ratelimit-pro/FEATURES_ROADMAP.md).

## Quick Status Overview

**Completed Features** (Core)
- ✅ In-Memory Backend
- ✅ Multi-Backend Support
- ✅ MongoDB Backend
- ✅ Token Bucket Algorithm
- ✅ Circuit Breaker Pattern
- ✅ Health Checks
- ✅ Configuration Validation
- ✅ Async Support (Views & Decorators)
- ✅ Fail-Open Mechanism
- ✅ Leaky Bucket Algorithm
- ✅ Database Backend (Django ORM)
- ✅ Adaptive Rate Limiting (Load-based)
- ✅ Type-Safe Enums
- ✅ Custom Response Handlers
- ✅ Custom Time Windows
- ✅ Prometheus Metrics
- ✅ Structured JSON Logging

**Next to Implement**
1. [Batch Operations](#batch-operations) (Performance)

## Core Feature Categories

### 🧪 Algorithms
- [x] **Token Bucket**: Standard burst-handling algorithm.
- [x] **Sliding Window**: Precise time-window tracking.
- [x] **Leaky Bucket**: Queue-based smoothing.

### 🏭 Backends (Stateless)
- [x] **Memory**: High-speed, local instance.
- [x] **Redis**: Distributed, atomic (Lua scripts).
- [x] **MongoDB**: NoSQL distributed storage.
- [x] **MultiBackend**: Failover chaining.
- [x] **Database Backend**: Django ORM for persistence.
- [ ] **Memcached**: Simple key-value store adapter (Planned).

### ⚡ Performance & Async
- [x] **Async Views**: Native `@aratelimit` decorator.
- [x] **Async Redis**: `redis.asyncio` support.
- [ ] **Batch Operations**: Pipelined checks for multiple keys.
- [ ] **Connection Pooling**: Advanced Redis pool management options.

### 🛡️ Reliability
- [x] **Circuit Breaker**: Auto-disable backends on failure.
- [x] **Fail Open**: Configurable pass-through on error.
- [x] **Health Checks**: `manage.py ratelimit_health`.

### 📊 Stateless Monitoring
- [x] **Prometheus Metrics**: Expose `/metrics` endpoint for scraper (no database req).
- [x] **Standard Logging**: Structured JSON logging for ELK stacks.

### 🎯 Adaptive Rate Limiting
- [x] **Load Indicators**: CPU, Memory, Latency, Connection Count.
- [x] **Adaptive Adjustment**: Dynamic rate limiting based on system metrics.
- [x] **Custom Indicators**: Support for user-defined load metrics.

### 🔧 Configuration & Developer Experience
- [x] **Type-Safe Enums**: Algorithm and RateLimitKey enums.
- [x] **Custom Response Handlers**: Per-decorator response callbacks.
- [x] **Custom Time Windows**: Flexible window configuration.

---

## Feature Status Overview

### ✅ Complete (v1.0.x)

The Core library is **feature-complete** for production use. All essential rate limiting capabilities are implemented.

| Category                 | Features                                                           |
| ------------------------ | ------------------------------------------------------------------ |
| **Algorithms**           | Token Bucket, Sliding Window, Fixed Window                         |
| **Backends**             | Memory, Redis, MongoDB, MultiBackend                               |
| **Reliability**          | Circuit Breaker, Fail-Open, Health Checks                          |
| **Async**                | Async Views, Async Middleware, Async Redis                         |
| **Developer Experience** | Decorator API, Middleware, Request Context, Key Functions, Headers  |

### ✅ Complete (v2.0.0)

| Category                 | Features                                                           |
| ------------------------ | ------------------------------------------------------------------ |
| **Monitoring**           | Prometheus Metrics (built-in fallback + prometheus-client support)  |
| **Algorithms**           | Leaky Bucket                                                       |
| **Backends**             | Database Backend (Django ORM)                                      |
| **Adaptive**             | Load-based adaptive rate limiting with custom indicators           |
| **Developer Experience** | Type-Safe Enums, Custom Response Handlers, Custom Time Windows     |

---

## Core Feature Details

### 🧪 Algorithms

| Algorithm      | Status      | Description                                  |
| -------------- | ----------- | -------------------------------------------- |
| Token Bucket   | ✅ Complete | Burst-handling with configurable refill rate  |
| Sliding Window | ✅ Complete | Precise time-window tracking                 |
| Fixed Window   | ✅ Complete | Clock-aligned rate limiting windows           |

### 🏭 Backends (Stateless)

| Backend      | Status      | Description                                    |
| ------------ | ----------- | ---------------------------------------------- |
| Memory       | ✅ Complete | High-speed local instance with cleanup threads |
| Redis        | ✅ Complete | Distributed, atomic Lua scripts, async support |
| MongoDB      | ✅ Complete | NoSQL distributed storage with TTL indexes     |
| MultiBackend | ✅ Complete | Failover chaining with health monitoring       |

### 🛡️ Reliability

| Feature         | Status      | Description                                |
| --------------- | ----------- | ------------------------------------------ |
| Circuit Breaker | ✅ Complete | Auto-disable failing backends              |
| Fail-Open       | ✅ Complete | Configurable pass-through on errors        |
| Health Checks   | ✅ Complete | `manage.py ratelimit_health` command       |

### ⚡ Performance & Async

| Feature          | Status      | Description                                   |
| ---------------- | ----------- | --------------------------------------------- |
| Async Views      | ✅ Complete | `@aratelimit` decorator for async views       |
| Async Middleware  | ✅ Complete | Full ASGI support                             |
| Async Redis      | ✅ Complete | `redis.asyncio` integration                   |

### 📊 Stateless Monitoring

| Feature            | Status      | Description                                          |
| ------------------ | ----------- | ---------------------------------------------------- |
| Prometheus Metrics | ✅ Complete | `/metrics` endpoint with built-in fallback metrics   |

### 🔧 Developer Experience

| Feature          | Status      | Description                            |
| ---------------- | ----------- | -------------------------------------- |
| Decorator API    | ✅ Complete | `@rate_limit` / `@ratelimit`          |
| Middleware       | ✅ Complete | Global rate limiting                   |
| Request Context  | ✅ Complete | `request.ratelimit` object             |
| Key Functions    | ✅ Complete | 10+ built-in key generators            |
| Response Headers | ✅ Complete | `X-RateLimit-*` standard headers       |
| Configuration    | ✅ Complete | Django settings integration            |

---

## Future Enhancements (v2.x+)

These features are **nice-to-have** and may be implemented in future major versions. They are not blockers for current use.

### Low Priority

| Feature                 | Description                   | Rationale                              |
| ----------------------- | ----------------------------- | -------------------------------------- |
| Memcached Backend       | Simple key-value adapter      | Redis/Memory cover most deployments    |
| ~~Structured JSON Logging~~ | ~~ELK-compatible log format~~ | ✅ Complete in v2.2.0               |

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
