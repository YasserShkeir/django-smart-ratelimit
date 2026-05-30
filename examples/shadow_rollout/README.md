# Shadow rollout

Roll out a new rate limit safely. With `shadow=True`, the decorator evaluates
the limit and logs what *would* be blocked, but never actually denies a request.
Watch the logs for a day, confirm the limit is not too aggressive, then remove
`shadow=True` to start enforcing.

Requires: core package only (no extras).

- `views.py` — a view decorated with `shadow=True`.
- `settings.py` — logging config that surfaces the shadow log line.

## Reading the logs

Each request that *would* have been blocked emits an `INFO` log on the
`django_smart_ratelimit.pipeline` logger:

```
SHADOW_RATE_LIMIT_BLOCK  event=ratelimit.shadow.block key=... limit=... remaining=... path=... method=...
```

The structured fields live in the log record's `extra` (`event`, `key`,
`limit`, `remaining`, `algorithm`, `backend`, `cost`, `path`, `method`). Grep or
query your log aggregator for `event=ratelimit.shadow.block` to count how many
requests the limit would have rejected. If that volume is acceptable, drop
`shadow=True` to enforce.

If you have the OpenTelemetry integration enabled, the same decisions are also
recorded as metrics with a `shadow="True"` attribute — see
[`docs/observability.md`](../../docs/observability.md).
