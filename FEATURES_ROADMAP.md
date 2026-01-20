# Django Smart Ratelimit - Core Features Roadmap

This document tracks the planned improvements and new features for **Django Smart Ratelimit (Core)**.
For database-backed features, analytics, and advanced enterprise capabilities, see the [Pro Roadmap](../django-smart-ratelimit-pro/FEATURES_ROADMAP.md).

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

**High Priority - Next to Implement**

1. [Batch Operations](#batch-operations) (Performance)
2. [Prometheus Metrics](#prometheus-metrics) (Stateless Monitoring)

## Core Feature Categories

### 🧠 Algorithms

- [x] **Token Bucket**: Standard burst-handling algorithm.
- [x] **Sliding Window**: Precise time-window tracking.
- [x] **Leaky Bucket**: Queue-based smoothing.

### 🏭 Backends (Stateless)

- [x] **Memory**: High-speed, local instance.
- [x] **Redis**: Distributed, atomic (Lua scripts).
- [x] **MongoDB**: NoSQL distributed storage.
- [x] **MultiBackend**: Failover chaining.
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

- [ ] **Prometheus Metrics**: Expose `/metrics` endpoint for scraper (no database req).
- [ ] **Standard Logging**: Structured JSON logging for ELK stacks.

---

## How to Contribute

We welcome contributions to the Core library!

1. Check [CONTRIBUTING.md](CONTRIBUTING.md) for setup.
2. Pick an item from **High Priority**.
3. Submit a PR against `main`.

> **Note**: Do not add database models or stateful features here. Those belong in Pro.
