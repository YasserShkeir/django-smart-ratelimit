# Django Smart Ratelimit Documentation

## Core Documentation

- **[Installation](installation.md)**: Setup and basic configuration
- **[Design Philosophy](design.md)**: Why we built this and how it compares
- **[Algorithms](algorithms.md)**: Deep dive into Token Buckets and Windows
- **[Configuration](configuration.md)**: Backends, Circuit Breakers, and Settings
- **[Error Handling](error_handling.md)**: Strategies for failure scenarios
- **[Deployment](deployment.md)**: Running in production
- **[Migration Guide](migration.md)**: moving from `django-ratelimit`

## API Reference

- **[Decorator](decorator.md)**: All arguments for `@rate_limit`
- **[Backends](backends.md)**: Implementation details
- **[Utilities](utilities.md)**: Helper functions

## Flagship Features

- **Shadow Mode**: Set `shadow=True` to evaluate and log rate-limit decisions
  (including OpenTelemetry events) without enforcing them. Use it to observe what
  *would* be blocked before turning on enforcement. See the
  [Decorator API](decorator.md).
- **Cost-Based (Weighted) Limiting**: The `cost` argument charges expensive
  requests more of the budget. It accepts an `int` or a callable
  `(request) -> int`, so a single export endpoint can cost more than a cheap
  read. See the [Decorator API](decorator.md).
- **CIDR Allow/Deny Lists**: The `allow_list` and `deny_list` arguments (and the
  `IPList`, `FileBackedIPList`, and `URLBackedIPList` helpers) match clients
  against IPv4/IPv6 CIDRs sourced from inline values, files, or URL feeds. See
  [Configuration](configuration.md) and [Deployment](deployment.md).
- **DRF Throttle Adapter**: Drop-in `BaseThrottle` subclasses
  (`UserRateLimitThrottle`, `AnonRateLimitThrottle`, and the configurable
  `SmartRateLimitThrottle`) bridge Django REST Framework's throttling interface
  to this library. Install with `pip install django-smart-ratelimit[drf]`. See
  [Installation](installation.md).
- **Observability**: Built-in Prometheus `/metrics`, OpenTelemetry spans and
  metrics via `instrument_rate_limit()`, and structured JSON logging for
  ELK/Datadog/Splunk. Install the `prometheus` and `opentelemetry` extras as
  needed. See [Installation](installation.md).
- **Type-Safe Enums**: The optional `Algorithm` and `RateLimitKey` enums give you
  autocomplete and a typo-proof contract; they interoperate with plain strings
  everywhere. See the [Decorator API](decorator.md).
- **Configurable Proxy Trust** (new in v3.1): `RATELIMIT_TRUSTED_PROXIES` and
  `RATELIMIT_TRUST_FORWARDED_HEADERS` make client IP extraction spoof-resistant
  behind load balancers and CDNs. See [Configuration](configuration.md) and
  [Deployment](deployment.md).
- **Database Backend**: An optional Django ORM backend persists rate-limit state
  in your SQL database (PostgreSQL, MySQL, SQLite) without requiring Redis. See
  [Backends](backends.md).
