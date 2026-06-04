# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.7.0] - 2026-06-04

Polish release: discoverability and async parity. Additive; no breaking changes.

### Added

- **Top-level re-exports for the v4.x feature APIs.** The dynamic-rules, user-tier,
  group, API-key, analytics, geographic, multi-tenant, GraphQL, and StatsD helpers
  are now importable directly from `django_smart_ratelimit` (and listed in
  `__all__`) for autocomplete, e.g. `from django_smart_ratelimit import geo_key,
  tier_key, get_traffic_summary`. The submodule imports
  (`from django_smart_ratelimit import geo`) still work. Django **model** classes
  remain importable from `django_smart_ratelimit.models` (re-exporting them at the
  top level would touch the app registry too early).
- **Async-native Redis leaky bucket.** `AsyncRedisBackend` gains
  `aleaky_bucket_check` / `aleaky_bucket_info` (same atomic Lua as the sync
  backend), so the dedicated async backend has true atomic leaky-bucket semantics.

### Changed

- Raised the CI coverage floor (`--cov-fail-under`) from 65% to 68%, reflecting
  the measured coverage.

Completes the original v2.0 feature roadmap: the handful of items that were
planned but never built. Everything here is additive and opt-in; no existing
behavior changes.

### Added

- **Decorator honors user tiers/overrides** (roadmap 3.3.2) — with
  `RATELIMIT_USE_USER_TIERS = True`, `@rate_limit` now resolves an authenticated
  request to its effective rate (override -> tier -> base) and limits it in a
  per-user bucket, matching the middleware. No-op when the setting is off or the
  decorator uses `adaptive=`.
- **`tiers.tier_key`** (roadmap 3.1.4) — a key function bucketing requests by the
  user's tier (`tier:<name>` / `tier:anonymous` / `tier:default`).
- **`tiers.create_user_override`** (roadmap 3.3.4) — a programmatic helper to
  grant a temporary per-user rate override (validates the rate, defaults to a
  one-hour window).
- **Offender detail + alerting** (roadmap 4.3.2 / 4.3.4) —
  `analytics.get_offender_detail()` (per-key totals, per-path breakdown, recent
  events), a staff-only JSON `offender-detail` view (`dashboard/offender/?key=`),
  `analytics.find_alertable_offenders()` / `send_offender_alerts()` (email +
  webhook, opt-in), and a `ratelimit_alerts` management command for cron.
- **StatsD exporter** (roadmap 5.1.3) — `statsd.StatsDClient` (dependency-free
  UDP) and `statsd.StatsDMetrics` mirroring the Prometheus exporter API,
  configured via `RATELIMIT_STATSD`.
- **Native atomic Redis leaky bucket** (roadmap 5.2.3) — `RedisBackend` now
  implements `leaky_bucket_check` / `leaky_bucket_info` via Lua, so the
  `leaky_bucket` algorithm is atomic on Redis (previously a non-atomic fallback).
- **`adaptive.TimeOfDayIndicator`** (roadmap 5.3.1) — a load indicator that
  reports high load during configured peak hours so adaptive limits tighten on a
  schedule.

### Settings

- `RATELIMIT_STATSD` (StatsD host/port/prefix/enabled).
- `RATELIMIT_ALERT_THRESHOLD`, `RATELIMIT_ALERT_EMAILS`, `RATELIMIT_ALERT_WEBHOOK`
  (offender alerting; alerting is disabled until a threshold is set).

## [4.5.1] - 2026-06-03

Test/packaging update: officially support the latest Python and Django. No
runtime code changes.

### Added

- **Python 3.14** support (classifier + CI matrix + tox).
- **Django 6.0** support (classifier + CI matrix + tox). Django 6.0 requires
  Python 3.12+.
- **Django 5.2** is now actually exercised in CI and tox (it was already
  advertised in the classifiers but never tested).

Verified locally against the latest stack: the full suite (1885 passed, 9
skipped) passes on Python 3.14 with both Django 6.0 and Django 5.2.

### Changed

- CI pins each matrix cell to the latest patch of its Django minor series
  (`Django==X.Y.*`) instead of the `.0` release, so Python 3.14 cells resolve
  Django 5.2.8+ (where 3.14 support landed) and every cell tests current
  security patches.
- `psycopg2-binary` is now installed only on the PostgreSQL coverage cell (other
  cells run on SQLite), avoiding a source build on Pythons without a published
  wheel.

## [4.5.0] - 2026-06-03

Roadmap Phase 5.4-5.6: **geographic**, **multi-tenant**, and **GraphQL** rate
limiting. All three are opt-in and self-contained; external providers
(`geoip2`, `graphene`/`strawberry-graphql`) are optional and imported lazily, so
nothing here changes existing behavior or adds a hard dependency.

### Added

- **Geographic limiting** (`django_smart_ratelimit.geo`) — `geo_key(request)`
  buckets by country (`geo:<CC>` / `geo:unknown`); `get_rate_for_country()`
  resolves a per-country rate from a `{ "CN": "10/h", "*": "50/h" }` mapping
  (with a `"*"` wildcard and a default fallback). Pluggable `GeoProvider`
  interface with a `MaxMindProvider` (GeoLite2/GeoIP2 `.mmdb` via the optional
  `geoip2` package), a `NullGeoProvider`, and `set_geo_provider()` for tests.
- **Multi-tenant limiting** (`django_smart_ratelimit.tenants`) —
  `extract_tenant(request)` resolves a tenant from `request.tenant`
  (django-tenants), an `X-Tenant-ID` header, the authenticated user's
  `tenant_id`, or the Host subdomain; `tenant_key()` buckets by it; the new
  `TenantQuota` model (migration `0007`) supplies a per-tenant rate that
  `resolve_tenant_rate()` applies over the default.
- **GraphQL limiting** (`django_smart_ratelimit.graphql`) — a
  `GrapheneRateLimitMiddleware` that limits only top-level operations (nested
  resolvers are never double-counted) with optional complexity weighting, a
  `make_strawberry_extension()` factory (lazy Strawberry import), and a
  dependency-free `estimate_query_complexity()` heuristic for cost-weighted
  limits.
- Django admin for `TenantQuota`.

### Settings

- `RATELIMIT_GEOIP_PATH` — path to a GeoLite2/GeoIP2 `.mmdb` database (enables
  the MaxMind geo provider; default `None`).

### Packaging

- New optional extras: `geoip` (`geoip2`) and `graphql` (`graphene`).

## [4.4.0] - 2026-06-03

Roadmap Phase 4: **analytics & monitoring** — event logging, aggregations, an
offender report, and a staff dashboard. Opt-in via `RATELIMIT_LOG_EVENTS`; fully
backward compatible.

### Added

- **`RateLimitEvent` model** (migration `0006`) — one row per middleware decision
  (timestamp, key, rule_name, path, method, allowed, count, limit, ip, user_id),
  indexed for time-range / per-key / allowed-vs-blocked reporting. Recorded only
  when `RATELIMIT_LOG_EVENTS = True` (best-effort; logging never breaks a request).
  `RateLimitEvent.cleanup_old(older_than_days=...)` prunes history.
- **Aggregations** (`django_smart_ratelimit.analytics`): `get_traffic_summary()`
  (total / allowed / blocked / block-rate), `get_top_offenders()` (most-blocked
  keys), `get_rule_hit_counts()` (per-rule hits + blocks), and `offenders_csv()`.
- **Dashboard** — a staff-only `RateLimitDashboardView` (dependency-free HTML
  template, date-range filter) and a CSV export view, wired via
  `path("ratelimit/", include("django_smart_ratelimit.urls"))`.
- Read-only Django admin for `RateLimitEvent`.

### Settings

- `RATELIMIT_LOG_EVENTS` (default `False`).

## [4.3.0] - 2026-06-03

Roadmap Phase 3: **user-aware rate limiting** — tiers, Django-group mapping,
per-user overrides, and API keys. Opt-in via `RATELIMIT_USE_USER_TIERS`; fully
backward compatible.

### Added

- **Tiers** — `UserTier` (a `rate_multiplier` and/or per-scope `explicit_limits`)
  and `UserTierAssignment` (assign a user to a tier, with an optional expiry).
  `django_smart_ratelimit.tiers.get_user_tier()` / `apply_tier_to_rate()` /
  `resolve_effective_user_rate()`.
- **Django groups** — `GroupRateLimit` maps an `auth.Group` to a tier;
  `groups.get_tier_from_groups()` resolves a user's tier from their groups (used
  as the fallback when there's no explicit assignment) and `groups.group_key()` is
  a group-based key function.
- **Per-user overrides** — `UserRateLimitOverride`, a time-bounded
  (`starts_at`/`expires_at`) per-user rate that takes precedence over tiers; a
  scope-specific (`rule_name`) override beats a blanket one.
- **API keys** — an optional `APIKey` model (key → user/tier), plus
  `api_keys.extract_api_key()` (header / query / Bearer), `get_api_key_record()`
  (with `last_used_at` touch), `api_key_key()` key function, and
  `get_api_key_tier()`.
- **Middleware integration** — with `RATELIMIT_USE_USER_TIERS = True`, an
  authenticated request is resolved at its effective rate (override → tier → base)
  **and limited in its own per-user bucket**, so users at different tiers sharing
  an IP don't interfere. Anonymous requests are unaffected.
- Django admin for all five models. Migration `0005`.

### Settings

- `RATELIMIT_USE_USER_TIERS` (default `False`).

## [4.2.0] - 2026-06-03

Roadmap Phase 2: **dynamic, database-backed rate-limit rules** — define and change
limits at runtime (Django admin or ORM) without a redeploy. Opt-in and fully
backward compatible.

### Added

- **`RateLimitRule` model** — a rule targets requests by `path_pattern` (regex) and
  `method`, and carries a `rate`, `key`, `algorithm`, `block`, `is_active` and
  `priority`. The `rate` string and `path_pattern` regex are validated on save.
  Migration `0004`.
- **`RuleEngine`** (`django_smart_ratelimit.rules`) — matches a request to the
  highest-priority active rule, with a short cache (bounded by
  `RATELIMIT_RULE_CACHE_TIMEOUT`, default 60s) that is invalidated automatically on
  rule save/delete, so edits take effect immediately.
- **Django admin** — `RateLimitRuleAdmin` (create/edit rules, bulk enable/disable
  actions) and a read-only `RateLimitCounterAdmin` for monitoring live counters.
- **Middleware integration** — set `RATELIMIT_USE_DYNAMIC_RULES = True`; a matching
  `RateLimitRule` then overrides the static `RATE_LIMITS` / `DEFAULT_RATE` for that
  request (honoring the rule's rate, key, and `block`). When no rule matches, the
  static configuration applies as before.
- **`ratelimit_reload_rules`** management command to force a rule-cache reload.

### Settings

- `RATELIMIT_USE_DYNAMIC_RULES` (default `False`) and `RATELIMIT_RULE_CACHE_TIMEOUT`
  (default `60`).

## [4.1.0] - 2026-06-03

Closes the design-level backlog carried since v4.0.2: correct Prometheus
auto-instrumentation, atomic database rate limiting under concurrency, and a
batch of correctness hardening. No breaking API changes; new regression tests in
`tests/e2e/test_v4_1_0_regressions_e2e.py`.

### Fixed

- **Prometheus auto-instrumentation now records denials.** `PrometheusMetricsMiddleware`
  read a non-existent `request.ratelimit.limited` / `backend`, so every request —
  including 429s — was recorded as `result="allowed", backend="unknown"`. It now
  reads the context's `allowed` / `backend_name`, and uses the rate-limit
  `check_duration` for the duration metric instead of the whole-request time. The
  decorator also attaches `request.ratelimit` on the token-bucket, leaky-bucket and
  async paths (previously only the sync window path), so auto-instrumentation works
  uniformly. (Removes the strict `xfail` shipped in v4.0.2.)
- **Database `sliding_window` is now atomic under concurrency.** The
  create-then-count increment took no per-key lock, so under READ COMMITTED
  (PostgreSQL / MySQL default) simultaneous requests each missed the other's
  uncommitted insert and all admitted — letting the limit be exceeded by the number
  of in-flight requests (an exploitable bypass for e.g. login throttling). It now
  takes a per-key advisory lock (`pg_advisory_xact_lock` on PostgreSQL, `GET_LOCK`
  on MySQL); SQLite serializes writers already. Verified against real PostgreSQL
  (30 concurrent @ limit 10: was 30 admitted, now exactly 10). CI now runs the suite
  against a PostgreSQL service so this is exercised continuously.
- **Token/leaky bucket no longer mis-limit on a wall-clock step backward.** Elapsed
  time is clamped at zero, so an NTP correction (etc.) can no longer drain a token
  bucket or fill a leaky bucket and spuriously reject traffic.
- **Async middleware header merge.** `RateLimitMiddleware.__acall__` now applies the
  same "more restrictive wins" header merge as the sync path, and both tolerate a
  response that sets `X-RateLimit-Limit` without `-Remaining` (was
  `int(float("inf"))` → `OverflowError`).
- **`AdaptiveRateLimiter.add_indicator` / `remove_indicator`** now mutate the
  indicator list under the same lock the load calculation iterates under (was a
  "list changed size during iteration" risk on the request path).

### Changed

- **Leaky-bucket config is validated.** A negative `leak_rate` (or non-positive
  `bucket_capacity`) now raises `ImproperlyConfigured`, matching token-bucket
  validation.
- **Counter/bucket integer fields widened to `BigInteger`** (`count`, `bucket_size`,
  `bucket_capacity`) so a very large limit no longer overflows on PostgreSQL/MySQL.
  Includes migration `0003`.

### Added

- New end-to-end coverage: exact-admission concurrency on PostgreSQL, unicode /
  very-long key values, MultiBackend `round_robin` distribution, and failover to a
  second LIVE store (Redis-primary → MongoDB-fallback).

### Notes

- **MultiBackend failover accuracy** is now documented rather than code-changed:
  with independent backends, counters are not synchronized, so a failover may
  briefly over- or under-count. The clean fix (shared/replicated state) is a larger
  redesign; until then, use backends that share storage for strict accuracy.
- A few low-impact items remain intentionally deferred (the unused `timed`
  performance decorator, an opt-in `PerformanceMonitor` lock, a dead async
  event-loop guard, and the `_aincr_with_cost` capability probe).

## [4.0.4] - 2026-06-02

A third review pass focused on the paths the first two didn't deeply cover (async,
under-reviewed modules, observability internals, ops, input validation, docs). The
core sync path was confirmed clean; this fixes the real issues found elsewhere. Each
fix ships with a regression test (`tests/e2e/test_review3_regressions_e2e.py`).

### Fixed

- **Async Redis backend diverged from the sync backend.** `AsyncRedisBackend` defaulted
  `key_prefix` to `"rl:"` and `algorithm` to `"sliding_window"` and never read settings,
  while the sync `RedisBackend` reads `RATELIMIT_KEY_PREFIX` / `RATELIMIT_ALGORITHM`. So a
  client alternating between a sync `@rate_limit` endpoint and an async `@aratelimit`
  endpoint for the same key got two independent counters (~2x the intended limit), a
  custom `RATELIMIT_KEY_PREFIX` was silently dropped on the async path, and the two paths
  could run different algorithms. The async backend now reads the same settings and applies
  the fixed-window clock-alignment key suffix, so sync and async share one keyspace.
- **`RateLimitConfigManager` mutated the shared settings config dict.** For a config loaded
  from `RATELIMIT_CONFIG_*`, a per-call override (`get_config(name, rate=...)`) updated the
  cached settings dict in place, leaking that override into every subsequent lookup of the
  same config. It now copies before applying overrides.
- **`MetricsCollector` could grow without bound.** With `RATELIMIT_COLLECT_METRICS=True`,
  per-key history was kept in a dict with no cap on the number of keys, so per-IP limiting
  on a public endpoint leaked memory proportional to unique clients. Keys are now
  LRU-bounded (aggregate counters remain exact).
- **`MultiBackend` leaked its background health-check thread.** The daemon thread had no
  stop hook, so it ran until interpreter exit and could write to stderr during teardown
  (an intermittent process abort, `_enter_buffered_busy`). `MultiBackend` now has a
  `shutdown()` method, and both it and `MemoryBackend` register for `atexit` cleanup, so
  their daemon threads are stopped before interpreter teardown.

### Changed

- **`parse_rate` rejects a negative limit** (e.g. `"-5/m"`) with a clear
  `ImproperlyConfigured` instead of silently becoming a deny-everything limiter with a
  negative `X-RateLimit-Limit` header.
- **`RateLimitMiddleware` validates `DEFAULT_RATE` and `RATE_LIMITS` at startup.** A
  malformed rate string now raises at construction (fail fast) rather than returning a 500
  on every matching request.
- **The MongoDB backend honors a full connection `uri`.** A configured `uri` was previously
  ignored and the backend connected to `host`/`port` (defaulting to localhost); it now
  takes precedence. Docs updated; the middleware `SKIP_PATHS` / `RATELIMIT_ENABLE`
  documentation was corrected (the old docs named non-existent `excluded_paths` / `enabled`
  middleware keys).
- **`ratelimit_cleanup --batch-size`** now rejects a non-positive value with a clear error
  instead of crashing (negative) or silently deleting nothing (zero).

### Notes

- Still deferred (design-level, tracked): database `sliding_window` atomicity under
  Postgres/MySQL concurrency, `MultiBackend` failover double-count, the `PrometheusMetrics`
  auto-instrument `xfail`, and assorted LOW items (async middleware header merge, clock-step
  bucket clamp, etc.).

## [4.0.3] - 2026-06-02

A correctness and security patch fixing real bugs surfaced by a deep, adversarially
verified review of the library source. Every fix ships with a regression test
(`tests/e2e/test_deep_review_regressions_e2e.py`). No public API changed.

### Security

- **`get_tenant_key` no longer trusts a client-supplied tenant over the
  authenticated user.** It read `?tenant_id=` (and a request header) *before* the
  authenticated user's tenant, so an authenticated user could rate-limit as — and
  exhaust the bucket of — any tenant they named, or sidestep their own limit by
  varying the value. The authenticated user's tenant is now authoritative; the
  query parameter/header is consulted only when the request carries no
  authenticated tenant.
- **A malformed inline CIDR in `ALLOW_LIST` / `DENY_LIST` now fails fast.**
  Previously a single bad entry (e.g. `10.0.0.0/33`) made `apply_policy_lists`
  swallow the parse error and drop the whole list, silently failing **open** on
  every request even under fail-closed expectations. The middleware and DRF
  throttle now parse their policy lists **once at construction**, so a malformed
  entry raises immediately and a URL/file-backed feed is no longer re-fetched on
  every request (the decorator already parsed once).
- **IPv4-mapped IPv6 addresses now match IPv4 list entries.** A deny entry
  `1.2.3.4` was bypassed when the client address arrived as `::ffff:1.2.3.4`;
  `IPList.contains` now normalizes the mapped form before matching.

### Fixed

- **MongoDB `fixed_window` enforced nothing when `RATELIMIT_ALIGN_WINDOW_TO_CLOCK`
  was `False`.** The counter document was keyed on a per-request microsecond
  timestamp, so every request inserted a fresh `count=1` document (and grew the
  collection unbounded). The fixed-window counter is now always clock-aligned, as
  the database backend already is.
- **The DRF throttle ignored its declared `algorithm`.** `SmartRateLimitThrottle`
  always window-counted via `backend.incr`, so `algorithm="token_bucket"` /
  `"leaky_bucket"` silently behaved as a sliding window. The throttle now
  dispatches to the same token/leaky-bucket logic the decorator uses (honoring an
  optional `algorithm_config`).
- **`CircuitBreakerError` was two unrelated classes.** The package exported
  `exceptions.CircuitBreakerError` while the breaker raised
  `circuit_breaker.CircuitBreakerError`, so `except CircuitBreakerError` on the
  public export never caught an open circuit. The raised class is now a subclass
  of the exported one (all context fields preserved).
- **Sync token-bucket / leaky-bucket 429s carried no rate-limit headers.** The
  blocking path returned a bare 429 with no `Retry-After` / `X-RateLimit-*`,
  unlike the window algorithms and the async path. Headers are now emitted on
  these 429s too.
- **Redis `fixed_window` 429s carried no `Retry-After` / `X-RateLimit-Reset`.**
  `get_reset_time` read the bare key while the clock-aligned counter lives under a
  time-bucketed key, so it returned `None`; the decorator now computes the
  deterministic window reset (and resolves the backend algorithm regardless of
  whether the backend names it `algorithm` or `_algorithm`).

### Notes

- The deep review also confirmed two design-level issues left for a future
  release: the database `sliding_window` increment is non-atomic under concurrency
  on Postgres/MySQL (over-admission; SQLite serializes writes so it is unaffected),
  and `MultiBackend` can double-count an `incr` across a failover. A separate
  finding — that `PrometheusMetricsMiddleware` records denials as allowed — remains
  documented as a strict `xfail` from v4.0.2.

## [4.0.2] - 2026-05-31

### Fixed

- **MongoDB `get_reset_time()` returned a wrong epoch on non-UTC hosts.** PyMongo
  reads stored datetimes back as naive (UTC) values; calling `.timestamp()` on a
  naive datetime makes Python assume the host's *local* timezone, skewing the
  result by the host's UTC offset. The `X-RateLimit-Reset` header and the DRF
  throttle `Retry-After` were therefore off by hours whenever the server's clock
  was not set to UTC. The value is now made UTC-aware before conversion. (The
  existing window-expiry comparison already used the UTC-aware helper, so only
  the returned timestamp was affected.)
- **Redis `reset()` did not clear fixed-window or token-bucket keys.** Clock-
  aligned fixed-window counters are stored at `<key>:<bucket>` and token buckets
  at `<key>:token_bucket`, but `reset()` deleted only the bare key, so a reset
  left those counters in place. It now also scans and deletes the suffixed key
  family. (Sliding-window keys, stored under the bare key, were already cleared.)

Both bugs were surfaced by the new real-backend end-to-end suite (`tests/e2e/`),
which exercises every public-usage API against live Redis, MongoDB, and the test
database — no backend mocking — across all four algorithms. Mock-based unit tests
could not have caught either, since neither the timezone round-trip nor the real
key layout is exercised against a mock.

## [4.0.1] - 2026-05-30

### Fixed

- **Redis token bucket with `refill_rate=0`.** The native Redis Lua script
  computed the key TTL as `bucket_size / refill_rate`, which is infinite when
  `refill_rate=0` (a never-refilling bucket — a valid config the memory and
  database backends already handle). Redis then raised "value is not an integer
  or out of range" on `EXPIRE`, and the decorator silently fell back to window
  counting. The script now uses a fixed TTL and avoids the divide-by-zero. Found
  via a manual cross-backend sweep of the token-bucket feature.

## [4.0.0] - 2026-05-30

A consolidation release that pays down accumulated debt surfaced by a full-repo
audit: dead code removed, evaluation paths brought to feature parity, the hot
path made faster, proxy-trust hardened, and the type/CI/security tooling tightened.
Existing `@rate_limit`, `RateLimitMiddleware`, and the DRF throttles keep working;
the breaking changes are packaging-metadata and security-default tightening, all
listed below. See `MIGRATION.md` for upgrade notes.

### Added

- **DRF throttle parity with the decorator.** `SmartRateLimitThrottle` (and its
  subclasses) now support `allow_list` / `deny_list` CIDR policy lists and
  `shadow` mode as class attributes, so a deny-list or a shadow rollout works the
  same way under DRF throttling as it does under `@rate_limit`.
- **`RATELIMIT_POLICY_FAIL_CLOSED`** setting (default `False`): when `True`, a
  deny-list whose backing file/URL fails its initial load denies requests instead
  of failing open.
- **Time-based expiry for in-memory token buckets** so idle buckets are reclaimed
  proactively rather than only under LRU pressure.
- New documentation pages for the **DRF integration** and **observability**
  (OpenTelemetry + Prometheus), a runnable **`examples/`** tree, and a `[docs]`
  install extra.

### Changed

- **Performance:** `get_settings()` is now cached (and invalidated on the Django
  `setting_changed` signal), removing a per-request rebuild that scanned the
  settings module; CIDR allow/deny lists are parsed once at decoration time
  instead of on every request. Together these roughly halve the decorator's
  per-request overhead.
- The standalone async `@aratelimit` decorator is documented as window-counting
  only; use `@rate_limit` on an `async def` view for token/leaky bucket semantics.
- The `[dev]` extra is now self-sufficient (installs the optional backends/observability
  deps needed to run the full test suite); `mypy` and `django-stubs` are pinned to
  compatible ranges; `bump2version` was dropped in favor of commitizen.

### Security

- **Invalid `RATELIMIT_TRUSTED_PROXIES` now fails secure.** A misconfigured
  (unparseable) trusted-proxy list keeps the request in trusted-proxy mode and
  uses `REMOTE_ADDR`, rather than silently reverting to trusting client-supplied
  forwarded headers.
- Client-IP reads in `logging` and `auth_utils` (`is_internal_request`,
  `extract_user_identifier`) now route through `policy.get_client_ip`, so logged
  and bypass-decision IPs honor `RATELIMIT_TRUSTED_PROXIES`.
- `URLBackedIPList` hardening: a warning on non-TLS (`http://`) feeds and a
  bounded response read.
- `get_jwt_key` / `extract_jwt_claim` docstrings now state loudly that the token
  is not signature-verified and the claim is attacker-controllable.

### Removed

- **EOL `Framework :: Django :: 4.0` and `:: 4.1` classifiers** (the test matrix
  no longer covers them); added `:: 5.2`.
- The stale root `requirements.txt` (its roles moved to package extras / the
  readthedocs config) and a dead `.bandit` config file.
- Dead, zero-reference infrastructure in `backends/utils.py` (an unused backend
  registry, connection-pool/metrics-collector/health-monitor/operation-timer
  helpers, and `merge_rate_limit_data`).

### Fixed

- The ~12 latent type errors in `prometheus.py` / `observability/otel.py` that
  only appear when the optional `prometheus-client` / `opentelemetry` packages
  are installed; the CI `mypy` job now type-checks with those extras present.

### CI / tooling

- `mypy` runs with the optional integrations installed (so the observability
  modules are actually type-checked) and is pinned; the deprecated `safety check`
  is replaced by `pip-audit`; publish-workflow actions are pinned to commit SHAs;
  coverage is gated with `--cov-fail-under`.

## [3.1.0] - 2026-05-30

### Added

- **Configurable proxy trust for client IP extraction.** New settings
  `RATELIMIT_TRUSTED_PROXIES` (a list of IP/CIDR strings) and
  `RATELIMIT_TRUST_FORWARDED_HEADERS` (bool). When `RATELIMIT_TRUSTED_PROXIES`
  is set, the forwarded headers (`X-Forwarded-For`, `CF-Connecting-IP`,
  `X-Real-IP`) are honored only for requests that arrive from a trusted proxy,
  and the real client is taken as the right-most non-trusted entry of the
  `X-Forwarded-For` chain. The default behavior is unchanged and backward
  compatible (forwarded headers are trusted) until you opt in. A new public
  helper, `django_smart_ratelimit.policy.get_client_ip`, centralizes the logic;
  `get_ip_key` and the CIDR allow/deny lists now share it so the rate-limit key
  and policy lists always agree on the client IP.
- **Async support for the token-bucket and leaky-bucket algorithms.**
  `@rate_limit(..., algorithm="token_bucket")` (and `leaky_bucket` on backends
  with native support, e.g. the database backend) are now honored on async
  views — the algorithm check runs off the event loop via `sync_to_async`.
  Previously async views silently fell back to window counting. Async views on
  a backend without native leaky-bucket support still warn and use window
  limiting.

### Security

- IP-based limits and CIDR allow/deny lists can no longer be bypassed by a
  spoofed `X-Forwarded-For` (or `CF-Connecting-IP` / `X-Real-IP`) header once
  `RATELIMIT_TRUSTED_PROXIES` is configured. A direct (non-proxied) client's
  forwarded headers are ignored, and a client cannot move the result by
  prepending fake entries to the chain. See the deployment docs for setup.

## [3.0.0] - 2026-05-30

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
- **`drf` install extra** (`pip install django-smart-ratelimit[drf]`) that
  pulls in Django REST Framework for the throttle adapter. It is also part of
  the `all` extra.
- **`leaky_bucket` is now a first-class decorator algorithm.**
  `algorithm="leaky_bucket"` (or `Algorithm.LEAKY_BUCKET`) is dispatched to the
  leaky-bucket implementation on backends with native support (the database
  backend); other backends log a warning and fall back to window limiting.
  `Algorithm.LEAKY_BUCKET` was added to the enum and accepted by config
  validation.
- **Enum documentation.** The `Algorithm` and `RateLimitKey` enums are now
  documented across the README and docs, including that `RateLimitKey.HEADER`
  and `RateLimitKey.PARAM` are prefixes (e.g. `f"{RateLimitKey.HEADER}:X-Api-Key"`).
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
- **CI**: the test matrix now pins Django in the same install command as the
  package so the new `djangorestframework` extra cannot pull Django forward off
  the matrix version; bumped `codecov/codecov-action` 5 to 6,
  `softprops/action-gh-release` 2 to 3, and `mkdocs-material` to `>=9.7.6`.

### Fixed

- DRF throttle `wait()` now returns a non-`None` value on the block path
  (it previously only cached `_last_reset_time` on the allow path).
- DRF throttle `allow_request()` tolerates invalid rate strings and
  backend exceptions instead of blowing up — invalid rate logs a warning
  and allows the request; backend errors honor `fail_open` via
  `getattr(backend, "fail_open", True)`.
- DRF test state no longer leaks across test cases: `setUp`/`tearDown` now
  clear the backend singleton and its counters.

The following were found and fixed during the pre-release review pass:

- **Out-of-the-box failure**: when `RATELIMIT_BACKEND` was unset, the default
  backend path was unimportable and `get_backend()` raised
  `ImproperlyConfigured`. The default now correctly resolves to the in-memory
  backend.
- **Redis fail-open could 500 instead of allowing**: when retries were
  exhausted the backend returned `None`, which then crashed callers doing a
  numeric comparison. It now raises so each method's `fail_open` path runs (and
  the circuit breaker can see the failure).
- **Redis fixed-window reads/clears used the wrong key**: in clock-aligned
  `fixed_window` mode, `incr()` wrote to a time-bucketed key while `get_count()`
  and `reset()` used the bare key. They now target the same key.
- **MultiBackend fail-open crash**: `increment()` returned `None` (not a tuple)
  when every backend was down with `fail_open=True`, crashing the caller on
  unpack. It now returns a valid allow tuple; `cleanup_expired()` returns `0`.
- **Circuit breaker**: the `OPEN -> HALF_OPEN` probe is now counted against
  `half_open_max_calls` (it previously admitted one extra probe), and the
  decision/transition paths are guarded by the breaker lock. Redis-backed
  state now expires the `failures`/`last_failure` keys with the state key.
- **Async decorator**: non-blocking mode (`block=False`) now sets
  `request.rate_limit_exceeded` like the sync path; `aratelimit()` honors
  `fail_open` instead of always failing open; and selecting a `token_bucket`/
  `leaky_bucket` algorithm on an async view logs a warning (window counting is
  used — async algorithm dispatch is a known limitation).
- **Key resolution**: `key="user_or_ip"` (and `RateLimitKey.USER_OR_IP`) now
  resolve to the user-or-IP key instead of collapsing every request onto one
  global bucket; `param:` is accepted as an alias of `get:`.
- **Algorithm edge cases**: token-bucket/leaky-bucket now honor an explicit
  `0` for `initial_tokens`/`bucket_size`/`refill_rate`/`leak_rate` rather than
  treating it as "unset".
- **Prometheus**: the high-cardinality rate-limit `key` was removed from metric
  labels (it allowed unbounded series growth / memory exhaustion), the
  no-`prometheus_client` fallback no longer stores unbounded per-observation
  lists, and metric initialization is lock-protected.
- **Divide-by-zero guards**: `ConnectionCountIndicator` (`max_connections=0`)
  and `RateLimitTokenBucket.time_until_tokens` (`refill_rate=0`).
- **OpenTelemetry**: `record_check()` reuses a cached meter/tracer instead of
  constructing new instruments on every call.
- **MongoDB**: the fixed-window upsert retries on a concurrent-first-hit
  `DuplicateKeyError` instead of surfacing it.
- **Health check** reports a backend as unhealthy when its store is unreachable
  even if `fail_open=True` (the fail-open value previously masked the outage).
- The in-memory backend's cleanup thread is now stopped when the backend cache
  is cleared (no leaked daemon threads), and `time_aware_key` uses UTC so the
  window is consistent across servers.
- The DRF integration module now imports cleanly without Django REST Framework
  installed (instantiating a throttle without it raises a helpful `ImportError`).

### Removed

- Dead, unused `conf.py` module (its defaults contradicted the real `config.py`).

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
