# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-04-17

This is a major release that consolidates and hardens the v2.x runtime. Existing
`@rate_limit(...)` and `RateLimitMiddleware` call-sites keep working unchanged;
new keyword arguments are all optional. See `MIGRATION.md` for upgrade notes.

### Added

- **Shadow mode** (`shadow=True` on the decorator and `SHADOW` in the
  middleware config). Requests that would have been blocked are allowed
  through and logged with a `SHADOW_RATE_LIMIT_BLOCK` event plus an
  OpenTelemetry `ratelimit.shadow.block` attribute. Use this to validate a
  new limit in production before flipping enforcement on.
- **Cost-based (weighted) limiting** (`cost=<int | callable>` on the
  decorator). Expensive operations can consume more than one token per
  request. The cost may be a constant int or a callable `f(request) -> int`.
  Values are clamped to a minimum of 1 so `cost=0` cannot be used to bypass
  the limiter. Backends that don't natively accept a cost fall back to a
  loop of single-token increments so weighted limits still work end-to-end.
- **CIDR allow-lists and deny-lists** (`allow_list=` / `deny_list=` on the
  decorator, `ALLOW_LIST` / `DENY_LIST` in `RATELIMIT_MIDDLEWARE`). Accepts
  `IPList` instances, iterables of CIDR strings, file paths, or URLs.
  Deny always takes precedence over allow. Evaluated before any backend
  work so deny-listed clients never touch the cache.
- **DRF throttle adapter** at `django_smart_ratelimit.integrations.drf`.
  Three ready-to-use classes (`UserRateLimitThrottle`,
  `AnonRateLimitThrottle`, `ScopedRateLimitThrottle`) plus a
  `SmartRateLimitThrottle` base you can subclass.
- **pytest fixtures** at `django_smart_ratelimit.testing`, auto-registered
  via the `pytest11` entry point so your test project picks them up with
  zero configuration.
- **OpenTelemetry exporter** at `django_smart_ratelimit.observability`.
  Emits a span and metrics per rate-limit decision, covering both
  enforcement and shadow paths.
- **Shared v3 pipeline** (`django_smart_ratelimit.pipeline`) exposing
  `resolve_effective_rate`, `apply_policy_lists`, `handle_shadow_decision`,
  and the `POLICY_ALLOW` / `POLICY_DENY` / `POLICY_CONTINUE` sentinels.
  Third-party middlewares and adapters can now reuse the same evaluation
  primitives the built-in decorator uses.
- **`ratelimit` alias** for the `rate_limit` decorator to match
  `django-ratelimit` naming conventions, with the full v3 signature.
- Integration tests for shadow mode, cost limiting, CIDR lists, and key
  validation; unit tests for the pipeline module.

### Changed

- **Empty keys now raise** `KeyGenerationError` instead of silently
  collapsing every caller onto the empty-string bucket. Previously a key
  function that returned `""` or `None` would rate-limit the entire service
  as if it were a single client — a dangerous footgun. Pass
  `validate_key=False` to `resolve_effective_rate` if you need the old
  behavior in custom pipelines.
- **Generic token-bucket fallback is now serialized within-process** via a
  per-key `threading.Lock`. Backends intended for multi-process production
  use must still implement an atomic `token_bucket_check` — documented
  explicitly in the docstring. This closes the within-process race without
  pretending to solve the cross-process one.
- **Reset times for first-request-aligned windows are cached per key** so
  repeat callers within the same window see a stable `X-RateLimit-Reset`
  and `Retry-After` instead of a value that drifts forward on each call.
  Clock-aligned reset times were already stable and are unchanged.
- DRF throttle callable attributes (`rate`, `cost`, `key_func`) are now
  accessed through `type(self)` to bypass Python's method-binding so a
  plain function assigned as a class attribute receives
  `(throttle, request)` rather than an extra bound `self`.

### Fixed

- DRF throttle `wait()` now returns a non-`None` value on the block path
  (it previously only cached `_last_reset_time` on the allow path).
- DRF throttle `allow_request()` tolerates invalid rate strings and
  backend exceptions instead of blowing up — invalid rate logs a warning
  and allows the request; backend errors honor `fail_open` via
  `getattr(backend, "fail_open", True)`.
- DRF test state no longer leaks across test cases: `setUp`/`tearDown` now
  clear the backend singleton and its counters.

### Migration

- **If you relied on empty keys being a valid bucket**, pick a concrete
  placeholder (e.g. `"anonymous"`) or raise from your key function to
  skip rate limiting explicitly.
- **Nothing else is required.** All new parameters default to their
  pre-v3 behavior.

## [2.2.1] - 2026-04-08

### Fixed

- **NoScriptError Handling**: Fixed exception hierarchy bug in sync and async Redis backends where generic `RedisError` catch masked the specific `NoScriptError` handler (#62)

### Added

- **PEP 561 Support**: Added `py.typed` marker file for mypy and other type checkers (#63)

### Changed

- **CI**: Bumped `actions/checkout` from 4 to 6, `release-drafter` from 6 to 7, `actions/upload-artifact` from 6 to 7 (#59, #60, #61)
- **Documentation**: Comprehensive documentation cleanup, removed all emojis, updated to reflect v2.2.0 features (#58)

## [2.2.0] - 2026-03-26

### Added

- **Structured JSON Logging**: ELK/Datadog/Splunk-compatible structured log output with thread-local request context, builder pattern for log events, and Django settings integration (`RATELIMIT_LOGGING`). Disabled by default (opt-in).

## [2.1.0] - 2026-03-25

### Added

- **Prometheus Metrics**: Built-in `/metrics` endpoint with fallback metrics and optional `prometheus-client` integration.
- **Leaky Bucket Algorithm**: Queue-based smoothing algorithm.
- **Database Backend**: Django ORM backend for persistence.
- **Adaptive Rate Limiting**: Load-based dynamic rate adjustment with CPU, memory, latency, and custom indicators.
- **Type-Safe Enums**: `Algorithm` and `RateLimitKey` enums for configuration.
- **Custom Response Handlers**: Per-decorator response callbacks.
- **Custom Time Windows**: Flexible window configuration.

## [2.0.0] - 2026-03-24

### Breaking Changes

- Major version bump consolidating all v2.x features. See migration guide in docs.

## [1.0.3] - 2026-01-18

### Fixed

- **Public API Export**: Added `is_ratelimited` to `__all__` to ensure it is properly exported as part of the public API.

### Changed

- **CI Improvements**: Benchmark tests now skip on PRs for faster feedback; full benchmarks run on main branch only.
- **Tooling**: Added Release Drafter for automated release notes, TestPyPI publishing step, and conventional commit enforcement.
- **Logging**: Changed default backend operation log level from INFO to DEBUG to reduce console noise.

## [1.0.2] - 2026-01-15

### Added

- **Comprehensive Test Suite**: Added tox.ini for multi-version testing (Python 3.9-3.13, Django 3.2-5.1).
- **Parallel Test Runner**: Added `run_parallel_tests.py` for parallel tox/docker test execution with live status display.
- **Documentation Hosting**: Added ReadTheDocs and MkDocs configuration for hosted documentation.
- **CI Improvements**: Added GitHub Actions workflow for integration tests across backend matrix.

### Fixed

- **MongoDB Backend**: Fixed `w="majority"` write concern issue for standalone MongoDB instances.

## [1.0.1] - 2026-01-14

### Added

- **`ratelimit` Alias**: Added `ratelimit` as an alias for `rate_limit` decorator to match the naming convention of `django-ratelimit` and other rate limiting libraries. Both `@ratelimit` and `@rate_limit` are now supported.

## [1.0.0] - 2026-01-14

### Added

- **Window Alignment Configuration**: New `RATELIMIT_ALIGN_WINDOW_TO_CLOCK` setting to control whether rate limit windows align to clock boundaries (default: `True`) or start from the first request (`False`).

### Breaking Changes

This is a major re-architecture of the library. This version is not backward compatible with 0.x.

- **Removed Database Models**: `RateLimitRule` and `RateLimitEntry` models have been removed from the core package.
- **Removed Database Backend**: The `DatabaseBackend` has been moved to the `django-smart-ratelimit-pro` package.
- **Removed Django Admin Integration**: Rate limit configuration via Django Admin is no longer available in the core package.
- **Removed Management Commands**: `cleanup_ratelimit` command has been removed.

**Migration Path**:

- If you rely on database-backed rate limits, dynamic configuration, or dashboards, install [django-smart-ratelimit-pro](https://github.com/YasserShkeir/django-smart-ratelimit-pro).
- If you only use decorators (`@rate_limit`), Redis, memory, or MongoDB backends defined in code/settings, you can upgrade safely but check your settings.

## [Beta] - Pre-1.0.0

The following features were introduced during the beta development phase leading up to the 1.0.0 release.

### Fixed

- **Decorator**: Fixed `@ratelimit_batch` to correctly respect the `group` parameter in configuration dictionaries, preventing key collisions when multiple limits use the same key function.

### Architecture and Improvements

- **Dependency Injection**: Replaced direct Django settings access with a centralized `RateLimitSettings` class, improving testability and modularity.
- **Backend Factory**: Implemented a factory pattern for backend instantiation, supporting custom plugins via entry points.
- **Multi-Backend**: Improved `MultiBackend` with better thread safety (locking) and resource management.
- **Circuit Breaker**: Added distributed state support using Redis for the circuit breaker pattern.
- **Context Object**: Added `request.ratelimit` context object for accessing rate limit data directly in views.

### Performance

- **Async Support**: Full support for asynchronous views and middleware via `@aratelimit` and `AsyncRedisBackend` (using `redis.asyncio`).
- **Batch Operations**: Added `check_batch` backend method and `@ratelimit_batch` decorator for high-performance multi-key checks.
- **Memory Optimization**: Optimized `MemoryBackend` using `__slots__` and efficient structure interactions to reduce overhead.
- **Database Optimizations** (Moved to Pro): Implemented bulk deletes, atomic increments, and caching for the database backend before it was moved to the Pro package.

### Security and Reliability

- **Fail-Open Mechanism**: Implemented configurable fail-open behavior (`RATELIMIT_FAIL_OPEN=True`) to ensure backend errors do not block legitimate traffic.
- **Standardized Exceptions**: Introduced a consistent exception hierarchy (`BackendError`, `ConfigurationError`, `CircuitBreakerOpen`) for better error handling.
- **Cleanup**: Added background cleanup threads for the memory backend to prevent memory leaks.

### Fixed

- **Rate Limiting Accuracy**: Fixed issues with hardcoded periods in `get_count()` methods.
- **Concurrency**: Resolved thread-safety issues in `MultiBackend` round-robin selection.
- **Sliding Window**: Improved boundary handling for the sliding window algorithm.
- **Code Quality**: Addressed numerous linting warnings, added type hints (strict mypy), and standardized formatting.
