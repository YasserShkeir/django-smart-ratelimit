# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.2] - 2026-01-15

### Added

- 🧪 **Comprehensive Test Suite**: Added tox.ini for multi-version testing (Python 3.9-3.13, Django 3.2-5.1)
- 🚀 **Parallel Test Runner**: Added `run_parallel_tests.py` for parallel tox/docker test execution with live status display
- 📚 **Documentation Hosting**: Added ReadTheDocs and MkDocs configuration for hosted documentation
- 🔧 **CI Improvements**: Added GitHub Actions workflow for integration tests across backend matrix

### Fixed

- 🐛 **MongoDB Backend**: Fixed `w="majority"` write concern issue for standalone MongoDB instances

## [1.0.1] - 2026-01-14

### Added

- ✨ **`ratelimit` Alias**: Added `ratelimit` as an alias for `rate_limit` decorator to match the naming convention of `django-ratelimit` and other rate limiting libraries. Both `@ratelimit` and `@rate_limit` are now supported.

## [1.0.0] - 2026-01-14

### Added

- ⏰ **Window Alignment Configuration**: New `RATELIMIT_ALIGN_WINDOW_TO_CLOCK` setting to control whether rate limit windows align to clock boundaries (default: `True`) or start from the first request (`False`). This affects `fixed_window` and `sliding_window` algorithms.

### ⚠️ CRITICAL BREAKING CHANGES

This is a **MAJOR RE-ARCHITECTURE** of the library.
**DO NOT UPDATE** unless you have read this guide. This version is **NOT** backward compatible with 0.x.

- **REMOVED Database Models**: `RateLimitRule` and `RateLimitEntry` models have been removed from the core package.
- **REMOVED Database Backend**: The `DatabaseBackend` has been moved to the `django-smart-ratelimit-pro` package.
- **REMOVED Django Admin Integration**: You can no longer configure rate limits via Django Admin in the core package.
- **REMOVED Management Commands**: `cleanup_ratelimit` command has been removed.

**Migration Path**:

- If you rely on **Database-backed Rate Limits**, **Dynamic Configuration**, or **Dashboards**, you MUST install [django-smart-ratelimit-pro](https://github.com/YasserShkeir/django-smart-ratelimit-pro).
- If you only use **Decorators** (`@rate_limit`), **Redis**, **Memory**, or **MongoDB** backends defined in code/settings, you can upgrade safely but check your settings.

## [Beta] - Pre-1.0.0

The following features were introduced during the beta development phase leading up to the 1.0.0 release.

### Fixed

- **Decorator**: Fixed `@ratelimit_batch` to correctly respect the `group` parameter in configuration dictionaries, preventing key collisions when multiple limits use the same key function.

### Architecture & Improvements

- 🏗️ **Dependency Injection**: Replaced direct Django settings access with a centralized `RateLimitSettings` class, improving testability and modularity.
- 🏭 **Backend Factory**: Implemented a factory pattern for backend instantiation, supporting custom plugins via entry points.
- 🔄 **Multi-Backend**: Improved `MultiBackend` with better thread safety (locking) and resource management.
- 🧊 **Circuit Breaker**: Added distributed state support using Redis for the Circuit Breaker pattern.
- 🔌 **Context Object**: Added `request.ratelimit` context object for accessing rate limit data directly in views.

### Performance

- ⚡ **Async Support**: Full support for asynchronous views and middleware via `@aratelimit` and `AsyncRedisBackend` (using `redis.asyncio`).
- 📦 **Batch Operations**: Added `check_batch` backend method and `@ratelimit_batch` decorator for high-performance multi-key checks.
- 💾 **Memory Optimization**: Optimized `MemoryBackend` using `__slots__` and efficient structure interactions to reduce overhead.
- 🚀 **Database Optimizations** (Moved to Pro): Implemented bulk deletes, atomic increments, and caching for the database backend before it was moved to the Pro package.

### Security & Reliability

- 🔓 **Fail-Open Mechanism**: Implemented configurable fail-open behavior (`RATELIMIT_FAIL_OPEN=True`) to ensure backend errors don't block legitimate traffic.
- 🛡️ **Standardized Exceptions**: Introduced a consistent exception hierarchy (`BackendError`, `ConfigurationError`, `CircuitBreakerOpen`) for better error handling.
- 🧹 **Cleanup**: Added background cleanup threads for the Memory backend to prevent memory leaks.

### Fixed

- 🐛 **Rate Limiting Accuracy**: Fixed issues with hardcoded periods in `get_count()` methods.
- 🧵 **Concurrency**: Resolved thread-safety issues in `MultiBackend` round-robin selection.
- 🪟 **Sliding Window**: Improved boundary handling for the sliding window algorithm.
- 🧹 **Code Quality**: Addressed numerous linting warnings, added type hints (strict mypy), and standardized formatting.
