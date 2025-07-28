# Rate Limiting Algorithms

Django Smart Ratelimit supports multiple rate limiting algorithms, each designed for different use cases and traffic patterns. All algorithms can be enhanced with the Circuit Breaker Pattern for backend protection.

## Algorithm Overview

| Algorithm        | Bursts | Smoothness | Use Case                 | Memory Usage | Circuit Breaker |
| ---------------- | ------ | ---------- | ------------------------ | ------------ | --------------- |
| `fixed_window`   | ❌     | Low        | Simple rate limiting     | Low          | ✅              |
| `sliding_window` | ❌     | High       | Smooth traffic shaping   | Medium       | ✅              |
| `token_bucket`   | ✅     | Medium     | APIs with burst patterns | Low          | ✅              |

> **Protection**: All algorithms support the [Circuit Breaker Pattern](circuit_breaker.md) for automatic backend failure detection and recovery.

## Fixed Window Algorithm

The simplest algorithm that divides time into fixed windows and counts requests within each window.

### Characteristics

- **Simple implementation**: Easy to understand and debug
- **Memory efficient**: Only stores count per window
- **Edge case**: Allows bursts at window boundaries
- **Reset behavior**: Counter resets at window boundaries

### Usage

```python
@rate_limit(
    key='ip',
    rate='100/h',
    algorithm='fixed_window'
)
def api_endpoint(request):
    return JsonResponse({'data': 'response'})
```

> **Protection**: Fixed window algorithm works seamlessly with [Circuit Breaker Pattern](circuit_breaker.md) for backend failure protection.

### When to Use

- Simple rate limiting requirements
- Memory-constrained environments
- When burst behavior at boundaries is acceptable

## Sliding Window Algorithm

A more sophisticated algorithm that maintains a sliding time window, providing smooth rate limiting without boundary effects.

### Characteristics

- **Smooth limiting**: No burst behavior at boundaries
- **Memory overhead**: Stores individual request timestamps
- **Accurate counting**: Precise request rate calculation
- **Gradual reset**: Old requests gradually expire

### Usage

```python
@rate_limit(
    key='user',
    rate='500/h',
    algorithm='sliding_window'
)
def user_dashboard(request):
    return render(request, 'dashboard.html')
```

> **Protection**: Sliding window algorithm integrates with [Circuit Breaker Pattern](circuit_breaker.md) for robust failure handling.

### When to Use

- When smooth rate limiting is important
- APIs that need precise rate control
- When memory usage is not a primary concern

## Token Bucket Algorithm

A flexible algorithm that allows burst traffic while maintaining long-term rate limits by using a "bucket" of tokens.

### How It Works

1. **Token Bucket**: A virtual bucket holds tokens (permits for requests)
2. **Refill Rate**: Tokens are added to the bucket at a steady rate
3. **Consumption**: Each request consumes one or more tokens
4. **Burst Capability**: When bucket is full, allows immediate bursts
5. **Rate Limiting**: When bucket is empty, requests are limited

### Characteristics

- **Burst friendly**: Allows temporary spikes above base rate
- **Flexible configuration**: Independent bucket size and refill rate
- **Memory efficient**: Only stores current token count and timestamp
- **Natural behavior**: Mimics real-world capacity and refill patterns

### Configuration Options

```python
@rate_limit(
    key='api_key',
    rate='60/m',  # Base rate (also default refill rate)
    algorithm='token_bucket',
    algorithm_config={
        'bucket_size': 120,      # Max tokens (allows 2x burst)
        'refill_rate': 1.5,      # Tokens per second (90/minute)
        'initial_tokens': 120,   # Start with full bucket
        'tokens_per_request': 1, # Tokens consumed per request
    }
)
```

#### Configuration Parameters

- **`bucket_size`**: Maximum number of tokens in the bucket (default: same as rate limit)
- **`refill_rate`**: Tokens added per second (default: rate/period)
- **`initial_tokens`**: Initial tokens when bucket is created (default: bucket_size)
- **`tokens_per_request`**: Tokens consumed per request (default: 1)

### Usage Examples

#### Basic Burst Handling

```python
@rate_limit(
    key='user_id',
    rate='100/m',  # 100 requests per minute baseline
    algorithm='token_bucket',
    algorithm_config={
        'bucket_size': 200,  # Allow bursts up to 200 requests
    }
)
def api_endpoint(request):
    return JsonResponse({'message': 'API response'})
```

#### Custom Refill Rate

```python
@rate_limit(
    key='premium_user',
    rate='60/m',  # Base rate
    algorithm='token_bucket',
    algorithm_config={
        'bucket_size': 180,    # 3x burst capacity
        'refill_rate': 2.0,    # Refill faster (120/minute)
    }
)
def premium_api(request):
    return JsonResponse({'premium': True})
```

> **Protection**: Token bucket algorithm integrates with [Circuit Breaker Pattern](circuit_breaker.md) for comprehensive backend protection.

#### Multi-Token Requests

```python
@rate_limit(
    key='bulk_operation',
    rate='100/m',
    algorithm='token_bucket',
    algorithm_config={
        'bucket_size': 100,
        'tokens_per_request': 5,  # Each request costs 5 tokens
    }
)
def bulk_upload(request):
    # This endpoint consumes 5 tokens per request
    return JsonResponse({'uploaded': True})
```

### HTTP Headers

Token bucket algorithm provides additional HTTP headers:

- **Standard Headers**:

  - `X-RateLimit-Limit`: Rate limit value
  - `X-RateLimit-Remaining`: Requests remaining (token count)
  - `X-RateLimit-Reset`: When bucket will be full again

- **Token Bucket Specific**:
  - `X-RateLimit-Bucket-Size`: Maximum bucket capacity
  - `X-RateLimit-Bucket-Remaining`: Current tokens in bucket
  - `X-RateLimit-Refill-Rate`: Tokens added per second

### Use Cases

#### API Endpoints with Retry Logic

Perfect for APIs where clients might retry failed requests, allowing short bursts without penalizing normal usage.

```python
@rate_limit(
    key='client_id',
    rate='1000/h',  # 1000 requests per hour
    algorithm='token_bucket',
    algorithm_config={
        'bucket_size': 1500,  # Allow 50% burst for retries
    }
)
def api_with_retries(request):
    return JsonResponse({'data': 'response'})
```

#### File Upload Services

Allow occasional large uploads while maintaining average throughput limits.

```python
@rate_limit(
    key='user',
    rate='10/m',  # 10 uploads per minute
    algorithm='token_bucket',
    algorithm_config={
        'bucket_size': 30,  # Allow burst of 30 uploads
        'tokens_per_request': 5,  # Large uploads cost more
    }
)
def file_upload(request):
    return JsonResponse({'uploaded': True})
```

#### Premium User Tiers

Provide different burst capabilities based on user tier.

```python
def get_bucket_config(user):
    if user.is_premium:
        return {'bucket_size': 1000, 'refill_rate': 10.0}
    else:
        return {'bucket_size': 100, 'refill_rate': 1.0}

@rate_limit(
    key='user',
    rate='100/m',
    algorithm='token_bucket',
    algorithm_config=lambda req: get_bucket_config(req.user)
)
def tiered_api(request):
    return JsonResponse({'tier': 'premium' if request.user.is_premium else 'basic'})
```

### Implementation Details

#### Backend Support

All backends support token bucket algorithm:

- **Redis Backend**: Uses atomic Lua scripts for race-condition-free operations
- **Memory Backend**: Thread-safe in-memory implementation
- **Database Backend**: Django ORM-based implementation (not atomic)

#### Performance Characteristics

- **Memory Usage**: Minimal (stores only token count and timestamp)
- **CPU Usage**: Low (simple arithmetic operations)
- **Network Calls**: Single Redis call per rate limit check
- **Throughput**: Handles thousands of requests per second

#### Error Handling

- **Backend Failures**: Graceful fallback to standard rate limiting
- **Invalid Configurations**: Sensible defaults and validation
- **Time Sync Issues**: Robust time handling across servers

### Testing

Comprehensive test suite covers:

- Basic token consumption and refill
- Burst behavior and limits
- Edge cases (zero bucket size, invalid configs)
- Backend integration (Redis, Memory, Database)
- Performance under high load
- Concurrent access scenarios

## Algorithm Selection Guide

### Choose Fixed Window When:

- Simple rate limiting is sufficient
- Memory usage must be minimal
- Edge case bursts are acceptable
- Implementation simplicity is priority

### Choose Sliding Window When:

- Smooth rate limiting is required
- Precise rate control is important
- Memory usage is not a concern
- Boundary effects must be avoided

### Choose Token Bucket When:

- API clients have bursty behavior
- Need to handle retry scenarios
- Want to provide burst allowances
- Building APIs with different user tiers
- Need natural capacity + refill behavior

## Migration Guide

### From Fixed/Sliding Window to Token Bucket

```python
# Before (Fixed Window)
@rate_limit(key='user', rate='100/h', algorithm='fixed_window')

# After (Token Bucket with same average rate)
@rate_limit(
    key='user',
    rate='100/h',
    algorithm='token_bucket',
    algorithm_config={'bucket_size': 150}  # 50% burst allowance
)
```

### Configuration Migration

Most existing configurations work with token bucket by adding algorithm specification:

```python
# Add algorithm and optional config
@rate_limit(
    key='existing_key',
    rate='existing_rate',
    algorithm='token_bucket',  # Add this line
    algorithm_config={         # Optional customization
        'bucket_size': rate * 1.5  # 50% burst allowance
    }
)
```

## Best Practices

### 1. Bucket Sizing

- **Start Conservative**: Begin with bucket_size = rate \* 1.2 (20% burst)
- **Monitor Usage**: Adjust based on actual traffic patterns
- **User Tiers**: Different bucket sizes for different user types

### 2. Refill Rate Tuning

- **Default is Fine**: Usually use default (rate/period)
- **Faster Refill**: For APIs with predictable burst patterns
- **Slower Refill**: For resource-intensive operations

### 3. Monitoring

```python
# Monitor token bucket effectiveness
response_headers = {
    'X-RateLimit-Bucket-Remaining': metadata['tokens_remaining'],
    'X-RateLimit-Bucket-Size': metadata['bucket_size'],
}
```

### 4. Testing

- Test burst scenarios in staging
- Monitor rate limit violations in production
- Adjust configurations based on real usage patterns
