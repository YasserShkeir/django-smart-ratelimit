# Django Smart Ratelimit - Features Roadmap

**Last Updated:** 2026-01-19
**Current Version:** 1.0.3

This document tracks all features for **Django Smart Ratelimit**.

---

## Feature Status Overview

### ✅ Complete (v1.0.x)

All essential rate limiting capabilities are implemented and production-ready.

| Category                 | Features                                                           |
| ------------------------ | ------------------------------------------------------------------ |
| **Algorithms**           | Token Bucket, Sliding Window, Fixed Window                         |
| **Backends**             | Memory, Redis, MongoDB, MultiBackend                               |
| **Reliability**          | Circuit Breaker, Fail-Open, Health Checks                          |
| **Async**                | Async Views, Async Middleware, Async Redis                         |
| **Developer Experience** | Decorator API, Middleware, Request Context, Key Functions, Headers |

---

## Current Features (v1.0.x)

### 🧠 Algorithms

| Algorithm      | Status      | Description                                  |
| -------------- | ----------- | -------------------------------------------- |
| Token Bucket   | ✅ Complete | Burst-handling with configurable refill rate |
| Sliding Window | ✅ Complete | Precise time-window tracking                 |
| Fixed Window   | ✅ Complete | Clock-aligned rate limiting windows          |

### 🏭 Backends

| Backend      | Status      | Description                                    |
| ------------ | ----------- | ---------------------------------------------- |
| Memory       | ✅ Complete | High-speed local instance with cleanup threads |
| Redis        | ✅ Complete | Distributed, atomic Lua scripts, async support |
| MongoDB      | ✅ Complete | NoSQL distributed storage with TTL indexes     |
| MultiBackend | ✅ Complete | Failover chaining with health monitoring       |

### 🛡️ Reliability

| Feature         | Status      | Description                          |
| --------------- | ----------- | ------------------------------------ |
| Circuit Breaker | ✅ Complete | Auto-disable failing backends        |
| Fail-Open       | ✅ Complete | Configurable pass-through on errors  |
| Health Checks   | ✅ Complete | `manage.py ratelimit_health` command |

### ⚡ Performance & Async

| Feature          | Status      | Description                             |
| ---------------- | ----------- | --------------------------------------- |
| Async Views      | ✅ Complete | `@aratelimit` decorator for async views |
| Async Middleware | ✅ Complete | Full ASGI support                       |
| Async Redis      | ✅ Complete | `redis.asyncio` integration             |

### 🔧 Developer Experience

| Feature          | Status      | Description                      |
| ---------------- | ----------- | -------------------------------- |
| Decorator API    | ✅ Complete | `@rate_limit` / `@ratelimit`     |
| Middleware       | ✅ Complete | Global rate limiting             |
| Request Context  | ✅ Complete | `request.ratelimit` object       |
| Key Functions    | ✅ Complete | 10+ built-in key generators      |
| Response Headers | ✅ Complete | `X-RateLimit-*` standard headers |
| Configuration    | ✅ Complete | Django settings integration      |

---

## Planned Features (v2.0)

The following features are planned for v2.0, providing database persistence, dynamic configuration, and enterprise capabilities.

### 💾 Database Backend

| Feature              | Priority | Description                                   |
| -------------------- | -------- | --------------------------------------------- |
| Database Backend     | High     | SQL-based storage (PostgreSQL, MySQL, SQLite) |
| RateLimitEntry Model | High     | Per-request rate limit tracking               |
| RateLimitCounter     | High     | Fixed window counter storage                  |
| Django Migrations    | High     | Database schema management                    |
| Cleanup Command      | Medium   | Management command for expired entries        |

### 🎛️ Dynamic Configuration

| Feature           | Priority | Description                       |
| ----------------- | -------- | --------------------------------- |
| RateLimitRule     | High     | Database-backed dynamic rules     |
| Admin Interface   | High     | Manage rules via Django Admin     |
| Hot Reloading     | Medium   | Live rule updates without restart |
| Environment Rules | Low      | Separate rules for staging/prod   |

### 👤 User Integration

| Feature               | Priority | Description                   |
| --------------------- | -------- | ----------------------------- |
| User Tiers            | High     | Premium/Free tier rate limits |
| Django Groups Support | High     | Group-based rate limiting     |
| API Key Integration   | Medium   | Native API key rate limiting  |
| Custom Overrides      | Medium   | Per-user temporary overrides  |

### 📈 Analytics & Visibility

| Feature              | Priority | Description                 |
| -------------------- | -------- | --------------------------- |
| Traffic Dashboard    | Medium   | Admin view for monitoring   |
| Historical Reporting | Medium   | Daily/weekly blocking stats |
| Offender Analysis    | Low      | Identify abusive IPs/users  |

### 🏢 Enterprise Features

| Feature              | Priority | Description                       |
| -------------------- | -------- | --------------------------------- |
| Batch Operations     | Medium   | High-performance multi-key checks |
| Adaptive Limiting    | Low      | Load-based rate adjustment        |
| Multi-Tenant Support | Low      | Tenant-aware rate limiting        |
| GraphQL Support      | Low      | Graphene/Strawberry adapters      |

---

## Low Priority / Future (v3.0+)

| Feature                 | Description                   | Rationale                              |
| ----------------------- | ----------------------------- | -------------------------------------- |
| Leaky Bucket Algorithm  | Queue-based request smoothing | Token Bucket covers most use cases     |
| Memcached Backend       | Simple key-value adapter      | Redis/Memory cover most deployments    |
| DynamoDB Backend        | AWS serverless storage        | Complex, niche use case                |
| Cassandra Backend       | High-write distributed store  | Complex, niche use case                |
| Prometheus Metrics      | Stateless `/metrics` endpoint | Can be added via middleware externally |
| Structured JSON Logging | ELK-compatible log format     | Standard Python logging works          |

---

## Definition of Done

**A feature is NOT complete until all of the following are done:**

1. ✅ **Unit Tests** - Tests in `tests/` covering the feature with 80%+ coverage
2. ✅ **Integration Tests** - End-to-end tests verifying the feature works in a real Django project
3. ✅ **Documentation** - Updated docs in `docs/` explaining usage, configuration, and examples
4. ✅ **CHANGELOG Entry** - Added entry to `CHANGELOG.md` describing the change
5. ✅ **FEATURES_ROADMAP Update** - Feature marked as complete in this file
6. ✅ **Code Review** - PR approved and merged to main

---

## Development Phases

### Phase 1: Foundation (v2.0.0) - High Priority

- [ ] Database Backend implementation
  - [ ] Unit tests for DatabaseBackend
  - [ ] Integration tests with real database
- [ ] RateLimitEntry, RateLimitCounter models
  - [ ] Model tests
  - [ ] Migration tests
- [ ] Django migrations
- [ ] Admin interface for rules
  - [ ] Admin tests
- [ ] Cleanup management command
  - [ ] Command tests
- [ ] Documentation for all v2.0 features
- [ ] Overall test coverage 80%+

### Phase 2: User Integration (v2.1.0)

- [ ] User tier rate limits (`RATELIMIT_USER_TIERS`)
  - [ ] Unit tests for tier logic
  - [ ] Integration tests with Django auth
- [ ] Integration with Django Groups
  - [ ] Tests for group-based limits
- [ ] Per-user overrides
  - [ ] Override tests
- [ ] Documentation for user integration

### Phase 3: Monitoring (v2.2.0)

- [ ] Traffic dashboard admin view
  - [ ] Dashboard tests
- [ ] Historical reporting
  - [ ] Reporting tests
- [ ] Batch operations for high-volume sites
  - [ ] Batch operation tests
- [ ] Documentation for monitoring features

### Phase 4: Enterprise (v3.0+)

- [ ] Multi-tenant support
  - [ ] Multi-tenant tests
- [ ] GraphQL integration
  - [ ] GraphQL adapter tests
- [ ] Adaptive rate limiting
  - [ ] Adaptive algorithm tests

---

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for setup.

**How to contribute:**

- Bug fixes and performance improvements
- Documentation improvements
- Test coverage expansion
- New features (please open a discussion first)
