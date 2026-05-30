# Algorithms

## Algorithm Comparison

| Algorithm          | Characteristics                  | Best For                   |
| ------------------ | -------------------------------- | -------------------------- |
| **sliding_window** | Smooth request distribution      | Consistent traffic control |
| **fixed_window**   | Simple, predictable behavior     | Basic rate limiting needs  |
| **token_bucket**   | Allows traffic bursts            | APIs with variable load    |
| **leaky_bucket**   | Constant drain rate, smooths out | Steady downstream pacing   |

`sliding_window` is the default. It is used when no `algorithm` is passed to the
decorator and `RATELIMIT_ALGORITHM` is unset.

## Selecting an Algorithm with the Algorithm Enum

You can pass the algorithm as a plain string or use the `Algorithm` enum for IDE
autocomplete and type safety. The enum is a `StrEnum`, so its members are
interchangeable with the string values everywhere an algorithm is accepted.

```python
from django_smart_ratelimit.enums import Algorithm

# These two are equivalent:
@rate_limit(key="ip", rate="10/m", algorithm="sliding_window")
@rate_limit(key="ip", rate="10/m", algorithm=Algorithm.SLIDING_WINDOW)
def my_view(request):
    ...

# Also works in settings.py:
RATELIMIT_ALGORITHM = Algorithm.TOKEN_BUCKET
```

| Enum member               | String value       |
| ------------------------- | ------------------ |
| `Algorithm.SLIDING_WINDOW` | `"sliding_window"` |
| `Algorithm.FIXED_WINDOW`   | `"fixed_window"`   |
| `Algorithm.TOKEN_BUCKET`   | `"token_bucket"`   |
| `Algorithm.LEAKY_BUCKET`   | `"leaky_bucket"`   |

## Token Bucket Algorithm

The token bucket algorithm allows for burst traffic handling:

```python
from django_smart_ratelimit.enums import Algorithm

@rate_limit(
    key='user',
    rate='100/h',  # Base rate
    algorithm=Algorithm.TOKEN_BUCKET,  # or algorithm='token_bucket'
    algorithm_config={
        'bucket_size': 200,  # Allow bursts up to 200 requests
        'refill_rate': 2.0,  # Refill tokens at 2 per second
    }
)
def api_with_bursts(request):
    return JsonResponse({'data': 'handled'})
```

**Common use cases:**

- Mobile app synchronization after offline periods
- Batch file processing
- API retry mechanisms

## Sliding Window Algorithm

The sliding window algorithm provides smooth, consistent rate limiting:

```python
@rate_limit(
    key='ip',
    rate='60/m',
    algorithm=Algorithm.SLIDING_WINDOW,  # or algorithm='sliding_window'
)
def consistent_api(request):
    return JsonResponse({'status': 'ok'})
```

**Characteristics:**

- Evaluates requests over a sliding time window
- Prevents burst traffic at window boundaries
- Uses weighted calculation for smooth transitions

## Fixed Window Algorithm

The fixed window algorithm uses discrete time periods:

```python
@rate_limit(
    key='user',
    rate='100/h',
    algorithm=Algorithm.FIXED_WINDOW,  # or algorithm='fixed_window'
)
def hourly_limited_api(request):
    return JsonResponse({'data': 'result'})
```

**Characteristics:**

- Simple counter that resets at window boundaries
- Lower memory and computational overhead
- May allow bursts at window edges (up to 2x rate if timed correctly)

## Leaky Bucket Algorithm

The leaky bucket algorithm enforces a constant drain rate, smoothing bursts into a
steady stream:

```python
from django_smart_ratelimit.enums import Algorithm

@rate_limit(
    key='user',
    rate='100/h',
    algorithm=Algorithm.LEAKY_BUCKET,  # or algorithm='leaky_bucket'
)
def steady_pace_api(request):
    return JsonResponse({'data': 'result'})
```

**Backend requirement:** when used through the decorator, `leaky_bucket` requires a
backend with native leaky-bucket support. Only the **database** backend implements
this (via `leaky_bucket_check`). On any other backend (redis, memory, mongodb,
multi) the decorator logs a warning and falls back to standard window limiting, so
you do not get true leaky-bucket semantics there.

```
Timeline (leaky bucket, constant drain):
Bucket fills with requests, drains at a fixed rate
  in:  ▓▓▓▓     ▓▓        ▓▓▓▓▓
  out: ▓ ▓ ▓ ▓ ▓ ▓ ▓ ▓ ▓ ▓ ▓ ▓   (constant rate)
Overflow (bucket full) → request rejected
```

## Async Views and Algorithm Selection

As of v3.1.0, `@rate_limit` on an `async def` view honors `token_bucket` (and
`leaky_bucket` on a backend with native support, such as the database backend) —
the algorithm check runs off the event loop. On backends without native
leaky-bucket support, `leaky_bucket` logs a warning and falls back to window
counting. The standalone `@aratelimit` decorator performs window counting only.

## Window Alignment

Both `fixed_window` and `sliding_window` algorithms are affected by the **window alignment** setting.

### Clock-Aligned Windows (Default)

When `RATELIMIT_ALIGN_WINDOW_TO_CLOCK = True` (default):

- Windows align to clock boundaries (e.g., minutes start at :00 seconds)
- All users share the same window boundaries
- Predictable `X-RateLimit-Reset` header values

```
Timeline (60s window, clock-aligned):
12:00:00 ─────────────── 12:01:00 ─────────────── 12:02:00
   └── Window 1 ──────────┘   └── Window 2 ──────────┘
User A @ 12:00:30 → 30s left in window
User B @ 12:00:45 → 15s left in window (same window)
```

### First-Request-Aligned Windows

When `RATELIMIT_ALIGN_WINDOW_TO_CLOCK = False`:

- Each user's window starts from their first request
- Users have independent window boundaries
- Ensures every user gets their full quota

```
Timeline (60s window, first-request-aligned):
User A: 12:00:30 ─────────────── 12:01:30 ─────────────── 12:02:30
           └── Window 1 ──────────┘   └── Window 2 ──────────┘

User B: 12:00:45 ─────────────── 12:01:45 ─────────────── 12:02:45
           └── Window 1 ──────────┘   └── Window 2 ──────────┘
```

See the [Configuration](configuration.md#window-alignment-configuration) page for setup details.
