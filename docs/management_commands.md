# Management Commands

Django Smart Ratelimit provides several management commands to help maintain and monitor your rate limiting infrastructure.

## cleanup_ratelimit

Cleans up expired rate limit entries from the database backend to prevent storage bloat and maintain performance.

### Usage

```bash
python manage.py cleanup_ratelimit [options]
```

### Options

- `--dry-run`: Show what would be deleted without actually deleting (safe preview mode)
- `--batch-size N`: Number of records to delete in each batch (default: 1000). Use smaller values for large databases to avoid locks
- `--older-than N`: Delete entries older than N hours (default: 0 = expired only). Use positive values to clean old but not yet expired entries
- `--key-pattern PATTERN`: Only clean entries matching this key pattern (supports SQL LIKE wildcards)
- `--verbose`: Enable verbose output with detailed progress information

### Examples

```bash
# Clean up all expired entries
python manage.py cleanup_ratelimit

# Dry run to see what would be deleted
python manage.py cleanup_ratelimit --dry-run

# Clean entries older than 24 hours
python manage.py cleanup_ratelimit --older-than 24

# Clean specific key patterns
python manage.py cleanup_ratelimit --key-pattern "api:*"

# Use smaller batch sizes for large databases
python manage.py cleanup_ratelimit --batch-size 500

# Verbose output with dry run
python manage.py cleanup_ratelimit --dry-run --verbose
```

### Key Pattern Examples

- `api:*` - Clean all keys starting with "api:"
- `user:123:*` - Clean all keys for user 123
- `*login*` - Clean all keys containing "login"
- `temp:*` - Clean all temporary keys

### Best Practices

1. **Always test with --dry-run first** to see what would be deleted
2. **Use smaller batch sizes** (e.g., 500) for large databases to avoid locking issues
3. **Run during low traffic periods** to minimize impact
4. **Monitor database performance** during cleanup operations
5. **Consider setting up automated cleanup** via cron jobs

### Automation Example

```bash
# Add to crontab for daily cleanup at 2 AM
0 2 * * * /path/to/venv/bin/python /path/to/manage.py cleanup_ratelimit --older-than 24 --batch-size 500
```

## ratelimit_health

Checks the health of configured rate limiting backends and provides status information for monitoring purposes.

### Usage

```bash
python manage.py ratelimit_health [options]
```

### Options

- `--verbose`: Show detailed backend information including last check times and configurations
- `--json`: Output results in JSON format (useful for monitoring scripts and automation)

### Examples

```bash
# Basic health check
python manage.py ratelimit_health

# Detailed health check with verbose output
python manage.py ratelimit_health --verbose

# JSON output for monitoring scripts
python manage.py ratelimit_health --json

# Combined verbose and JSON output
python manage.py ratelimit_health --verbose --json
```

### Output Examples

#### Single Backend (Normal Output)

```
Backend: RedisBackend
✓ Backend is healthy
```

#### Single Backend (Verbose Output)

```
Backend: RedisBackend
✓ Backend is healthy
  Type: RedisBackend
```

#### Single Backend (JSON Output)

```json
{
  "type": "single-backend",
  "backend_class": "RedisBackend",
  "healthy": true,
  "error": null
}
```

#### Multi-Backend (Normal Output)

```
Total backends: 3
Healthy backends: 2
Fallback strategy: first_healthy

✓ primary_redis
✗ fallback_redis
✓ emergency_database
```

#### Multi-Backend (JSON Output)

```json
{
  "type": "multi-backend",
  "stats": {
    "total_backends": 3,
    "healthy_backends": 2,
    "fallback_strategy": "first_healthy",
    "backends": {
      "primary_redis": {
        "healthy": true,
        "backend_class": "RedisBackend",
        "last_check": 1672531200
      },
      "fallback_redis": {
        "healthy": false,
        "backend_class": "RedisBackend",
        "last_check": 1672531200
      },
      "emergency_database": {
        "healthy": true,
        "backend_class": "DatabaseBackend",
        "last_check": 1672531200
      }
    }
  },
  "backends": {
    "primary_redis": {
      "healthy": true,
      "backend_class": "RedisBackend",
      "last_check": 1672531200
    },
    "fallback_redis": {
      "healthy": false,
      "backend_class": "RedisBackend",
      "last_check": 1672531200
    },
    "emergency_database": {
      "healthy": true,
      "backend_class": "DatabaseBackend",
      "last_check": 1672531200
    }
  },
  "healthy": true
}
```

### Monitoring Integration

The health check command is designed to integrate with monitoring systems:

#### Shell Script Example

```bash
#!/bin/bash
# health_check.sh
result=$(python manage.py ratelimit_health --json 2>&1)
if [ $? -eq 0 ]; then
    echo "Rate limiting backends are healthy"
    echo "$result" | jq .
else
    echo "Rate limiting backends are unhealthy"
    echo "$result"
    exit 1
fi
```

#### Python Monitoring Script

```python
import subprocess
import json
import sys

def check_ratelimit_health():
    try:
        result = subprocess.run(
            ['python', 'manage.py', 'ratelimit_health', '--json'],
            capture_output=True,
            text=True,
            check=True
        )

        health_data = json.loads(result.stdout)

        if health_data.get('healthy', False):
            print("✓ Rate limiting backends are healthy")
            return True
        else:
            print("✗ Rate limiting backends are unhealthy")
            print(json.dumps(health_data, indent=2))
            return False

    except subprocess.CalledProcessError as e:
        print(f"✗ Health check failed: {e}")
        return False
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON response: {e}")
        return False

if __name__ == "__main__":
    if not check_ratelimit_health():
        sys.exit(1)
```

### Automated Monitoring

#### Cron Job Example

```bash
# Check health every 5 minutes and log results
*/5 * * * * /path/to/health_check.sh >> /var/log/ratelimit_health.log 2>&1
```

#### Systemd Timer Example

```ini
# /etc/systemd/system/ratelimit-health.service
[Unit]
Description=Rate Limit Health Check
After=network.target

[Service]
Type=oneshot
ExecStart=/path/to/health_check.sh
User=www-data
WorkingDirectory=/path/to/django/project

# /etc/systemd/system/ratelimit-health.timer
[Unit]
Description=Run rate limit health check every 5 minutes
Requires=ratelimit-health.service

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

## Best Practices

1. **Regular Cleanup**: Set up automated cleanup to prevent database bloat
2. **Health Monitoring**: Implement automated health checks for production systems
3. **Logging**: Keep logs of cleanup and health check operations
4. **Alerting**: Set up alerts for backend health failures
5. **Testing**: Always test management commands in staging before production
6. **Documentation**: Document your specific cleanup and monitoring procedures

## Getting Help

- **Command Usage Questions**: [GitHub Discussions - Q&A](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/q-a)
- **Issues with Commands**: [GitHub Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues)
- **Automation Ideas**: [Discussions - Ideas](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/ideas)
- **Examples**: Check the [examples/monitoring_examples.py](../examples/monitoring_examples.py)
