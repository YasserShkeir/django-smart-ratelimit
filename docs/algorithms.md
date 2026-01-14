# Algorithms

## Algorithm Comparison

| Algorithm          | Characteristics              | Best For                   |
| ------------------ | ---------------------------- | -------------------------- |
| **token_bucket**   | Allows traffic bursts        | APIs with variable load    |
| **sliding_window** | Smooth request distribution  | Consistent traffic control |
| **fixed_window**   | Simple, predictable behavior | Basic rate limiting needs  |

## Token Bucket Algorithm

The token bucket algorithm allows for burst traffic handling:

```python
@rate_limit(
    key='user',
    rate='100/h',  # Base rate
    algorithm='token_bucket',
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
    algorithm='sliding_window',
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
    algorithm='fixed_window',
)
def hourly_limited_api(request):
    return JsonResponse({'data': 'result'})
```

**Characteristics:**

- Simple counter that resets at window boundaries
- Lower memory and computational overhead
- May allow bursts at window edges (up to 2x rate if timed correctly)

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
