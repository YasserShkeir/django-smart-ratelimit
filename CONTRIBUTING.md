# Contributing to Django Smart Ratelimit

Thank you for your interest in contributing to Django Smart Ratelimit! This document provides guidelines and instructions for contributing to the project.

## 💬 Before You Start

- **Questions or Ideas?** Start a discussion in [GitHub Discussions](https://github.com/YasserShkeir/django-smart-ratelimit/discussions)
- **Bug Reports?** Open an issue in [GitHub Issues](https://github.com/YasserShkeir/django-smart-ratelimit/issues)
- **Feature Requests?** Share your ideas in [Discussions](https://github.com/YasserShkeir/django-smart-ratelimit/discussions/categories/ideas)

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for all contributors.

## AI Usage in Development

This project utilizes AI assistance to enhance development productivity while maintaining strict quality standards:

### AI-Assisted Development

- **Encouraged**: AI tools may be used for generating tests, documentation, and examples
- **Quality First**: All AI-generated content must undergo human review and validation
- **Standards Apply**: Same code quality, testing, and security standards apply regardless of origin
- **Transparency**: Consider noting significant AI assistance in pull request descriptions

### Guidelines for Contributors

- AI suggestions should be treated as drafts requiring human validation
- All code must pass our comprehensive test suite and quality checks
- Critical business logic and security-sensitive code requires extra human scrutiny
- See our [AI Usage Policy](AI_USAGE.md) for detailed information

### Quality Assurance

- 340+ tests must pass for all contributions
- Type checking with mypy is required
- Security scanning with Bandit validates all code
- Pre-commit hooks enforce consistent standards

## Development Setup

### Prerequisites

- Python 3.9 or higher
- Redis server (for testing)
- Git

### Setup Instructions

1. **Fork and clone the repository**

   ```bash
   git clone https://github.com/YasserShkeir/django-smart-ratelimit.git
   cd django-smart-ratelimit
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -e .[dev]
   ```

4. **Install pre-commit hooks**

   ```bash
   pre-commit install
   ```

5. **Run tests to verify setup**
   ```bash
   pytest
   ```

## Development Workflow

### Making Changes

1. **Create a new branch**

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**

   - Write code following the project's style guidelines
   - Add tests for new functionality
   - Update documentation as needed

3. **Run tests and linting**

   ```bash
   # Run all tests
   pytest

   # Run with coverage
   pytest --cov=django_smart_ratelimit

   # Run linting
   flake8 django_smart_ratelimit tests
   black django_smart_ratelimit tests
   mypy django_smart_ratelimit
   ```

4. **Commit your changes**

   ```bash
   git add .
   git commit -m "Add feature: description of your changes"
   ```

5. **Push and create a pull request**
   ```bash
   git push origin feature/your-feature-name
   ```

### Code Style

- **Python**: Follow PEP 8, enforced by `black` and `flake8`
- **Line length**: 88 characters (black default)
- **Imports**: Organized with `isort`
- **Type hints**: Required for all new code
- **Docstrings**: Google-style docstrings for all public functions and classes

### Testing

- **Unit tests**: Test individual functions and methods
- **Integration tests**: Test component interactions
- **Coverage**: Maintain >90% test coverage
- **Test naming**: Use descriptive test names that explain the scenario

Example test structure:

```python
def test_rate_limit_decorator_within_limit(self):
    """Test decorator when requests are within the limit."""
    # Setup
    # Test
    # Assert
```

### Documentation

- **README**: Update for new features or API changes
- **Docstrings**: Add to all new functions and classes
- **Type hints**: Include for all function parameters and return values
- **Examples**: Provide usage examples for new features

## Types of Contributions

### Bug Reports

When reporting bugs, please include:

- Clear description of the issue
- Steps to reproduce
- Expected vs actual behavior
- Environment details (Python, Django, Redis versions)
- Minimal code example

### Feature Requests

For new features:

- **Check the [Features Roadmap](FEATURES_ROADMAP.md) first** - your feature might already be planned
- Explain the use case and motivation
- Provide implementation suggestions if possible
- Consider backwards compatibility
- Discuss performance implications

### Code Contributions

We welcome:

- Bug fixes
- **New features from the [Features Roadmap](FEATURES_ROADMAP.md)**
- Performance improvements
- Documentation improvements
- Test coverage improvements

#### Working on Roadmap Features

If you want to work on a feature from our roadmap:

1. **Review the [Features Roadmap](FEATURES_ROADMAP.md)** to understand the requirements
2. **Comment on the related GitHub issue** to claim the feature
3. **Follow the specific implementation guidelines** listed for that feature
4. **Include all required tests** as specified in the roadmap
5. **Update the roadmap** with your progress and completion date

## Pull Request Process

1. **Check requirements**

   - [ ] Tests pass
   - [ ] Code coverage maintained
   - [ ] Documentation updated
   - [ ] Type hints added
   - [ ] Changelog updated (for significant changes)

2. **PR description**

   - Explain the changes and motivation
   - Link to related issues
   - Describe testing performed
   - Note any breaking changes

3. **Review process**
   - Maintainers will review your PR
   - Address feedback promptly
   - Be prepared to make changes

## Architecture Guidelines

### Adding New Backends

1. **Create backend class**

   ```python
   class NewBackend(BaseBackend):
       def incr(self, key: str, period: int) -> int:
           # Implementation
           pass
   ```

2. **Add to backend factory**

   ```python
   def get_backend(backend_name):
       if backend_name == 'new_backend':
           return NewBackend()
   ```

3. **Add tests**
   - Unit tests for backend methods
   - Integration tests with decorator and middleware

### Adding New Features

**Important**: Before implementing any new features, please check the [Features Roadmap](FEATURES_ROADMAP.md) which contains detailed implementation guidelines, testing requirements, and tracking for all planned features.

1. **Design considerations**

   - Backwards compatibility
   - Performance impact
   - Configuration options
   - Error handling
   - **Follow roadmap specifications** if the feature is listed

2. **Implementation steps**
   - **Review roadmap requirements** for the specific feature
   - Add feature code following roadmap guidelines
   - Add comprehensive tests as specified in roadmap
   - Update documentation as required
   - Add configuration options per roadmap specs
   - **Update roadmap progress** when complete

## Release Process

1. **Version bumping**

   - Follow semantic versioning
   - Update `__init__.py` version
   - Update changelog

2. **Testing**

   - Run full test suite
   - Test with multiple Python/Django versions
   - Manual testing of examples

3. **Documentation**
   - Update README if needed
   - Update API documentation
   - Update changelog

## Getting Help

- **Questions**: Open a GitHub Discussion
- **Issues**: Use the issue tracker
- **Chat**: Contact maintainers directly

## Recognition

Contributors are recognized in:

- GitHub contributors page
- Release notes
- Project documentation

Thank you for contributing to Django Smart Ratelimit!

## Advanced Configuration Examples

### Multi-Backend Configurations

#### High Availability Setup

```python
# settings.py - Production multi-backend setup
RATELIMIT_BACKENDS = [
    {
        'name': 'primary_redis',
        'backend': 'redis',
        'config': {
            'host': 'redis-primary.example.com',
            'port': 6379,
            'db': 0,
            'password': 'your-redis-password',
            'socket_timeout': 0.1,
        }
    },
    {
        'name': 'fallback_redis',
        'backend': 'redis',
        'config': {
            'host': 'redis-fallback.example.com',
            'port': 6379,
            'db': 0,
            'password': 'your-redis-password',
            'socket_timeout': 0.1,
        }
    },
    {
        'name': 'emergency_database',
        'backend': 'database',
        'config': {
            'cleanup_threshold': 1000,
        }
    }
]
RATELIMIT_MULTI_BACKEND_STRATEGY = 'first_healthy'
RATELIMIT_HEALTH_CHECK_INTERVAL = 30
RATELIMIT_HEALTH_CHECK_TIMEOUT = 5
```

#### Load Balancing Setup

```python
# settings.py - Round-robin load balancing
RATELIMIT_BACKENDS = [
    {
        'name': 'redis_1',
        'backend': 'redis',
        'config': {'host': 'redis-1.example.com'}
    },
    {
        'name': 'redis_2',
        'backend': 'redis',
        'config': {'host': 'redis-2.example.com'}
    },
    {
        'name': 'redis_3',
        'backend': 'redis',
        'config': {'host': 'redis-3.example.com'}
    }
]
RATELIMIT_MULTI_BACKEND_STRATEGY = 'round_robin'
```

### Complex Key Function Examples

#### Enterprise API Key Management

```python
# utils/ratelimit.py
def enterprise_api_key(request):
    """Complex key function for enterprise API management."""
    api_key = request.headers.get('X-API-Key')

    if api_key:
        # Look up API key in your system
        try:
            api_key_obj = APIKey.objects.select_related('organization').get(
                key=api_key,
                is_active=True
            )
            # Use organization-based limiting
            return f"org:{api_key_obj.organization.id}"
        except APIKey.DoesNotExist:
            # Invalid API key, use IP limiting
            pass

    # Fallback to user or IP
    if request.user.is_authenticated:
        return f"user:{request.user.id}"

    return f"ip:{request.META.get('REMOTE_ADDR')}"

# Apply to views
@rate_limit(key=enterprise_api_key, rate='10000/h')
def enterprise_api(request):
    return JsonResponse({'data': '...'})
```

#### JWT Token-Based Limiting

```python
# utils/ratelimit.py
import jwt
from django.conf import settings

def jwt_subject_key(request):
    """Extract rate limiting key from JWT token."""
    auth_header = request.headers.get('Authorization', '')

    if auth_header.startswith('Bearer '):
        try:
            token = auth_header.split(' ')[1]
            # Decode without verification for key extraction
            payload = jwt.decode(
                token,
                options={"verify_signature": False}
            )

            # Use JWT subject for rate limiting
            if 'sub' in payload:
                return f"jwt_sub:{payload['sub']}"

            # Or use custom claims
            if 'org_id' in payload:
                return f"org:{payload['org_id']}"

        except jwt.InvalidTokenError:
            pass

    # Fallback to IP
    return f"ip:{request.META.get('REMOTE_ADDR')}"
```

### Performance Tuning

#### Redis Optimization

```python
# settings.py - Optimized Redis configuration
RATELIMIT_REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
    'password': None,
    'socket_timeout': 0.1,          # Fast timeout
    'socket_connect_timeout': 0.1,  # Fast connection
    'socket_keepalive': True,       # Keep connections alive
    'socket_keepalive_options': {},
    'connection_pool_kwargs': {
        'max_connections': 50,      # Pool size
        'retry_on_timeout': True,
    },
    'key_prefix': 'rl:',           # Short prefix
}

# Use sliding window for accuracy
RATELIMIT_ALGORITHM = 'sliding_window'
```

#### Database Backend Tuning

```python
# settings.py - Database backend optimization
RATELIMIT_DATABASE_CLEANUP_THRESHOLD = 5000  # Clean more frequently
RATELIMIT_ALGORITHM = 'fixed_window'          # Faster for DB

# Add database indexes (in your migration)
"""
ALTER TABLE django_smart_ratelimit_ratelimitentry
ADD INDEX idx_key_window (key, window_start);

ALTER TABLE django_smart_ratelimit_ratelimitcounter
ADD INDEX idx_key_expires (key, expires_at);
"""
```

### Testing Configuration

#### Development Settings

```python
# settings/development.py
RATELIMIT_BACKEND = 'memory'
RATELIMIT_MEMORY_MAX_KEYS = 1000
RATELIMIT_ALGORITHM = 'fixed_window'

# Disable rate limiting in development
RATELIMIT_ENABLE = False  # Custom setting you can check
```

#### Testing Settings

```python
# settings/testing.py
RATELIMIT_BACKEND = 'memory'
RATELIMIT_MEMORY_MAX_KEYS = 100

# Override in tests
from django.test.utils import override_settings

@override_settings(RATELIMIT_BACKEND='memory')
class MyTestCase(TestCase):
    def test_rate_limiting(self):
        # Your test code here
        pass
```

### Monitoring and Alerting

#### Health Check Script

```python
#!/usr/bin/env python
# scripts/health_check.py
import os
import sys
import django
from django.conf import settings

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

from django_smart_ratelimit.backends import get_backend

def check_backend_health():
    """Check rate limiting backend health."""
    try:
        backend = get_backend()

        if hasattr(backend, 'get_backend_status'):
            # Multi-backend
            status = backend.get_backend_status()
            stats = backend.get_stats()

            if stats['healthy_backends'] == 0:
                print("❌ All backends are unhealthy!")
                return False
            elif stats['healthy_backends'] < stats['total_backends']:
                print(f"⚠️  {stats['healthy_backends']}/{stats['total_backends']} backends healthy")
                return True
            else:
                print("✅ All backends healthy")
                return True
        else:
            # Single backend
            backend.get_count('_health_check')
            print("✅ Backend healthy")
            return True

    except Exception as e:
        print(f"❌ Backend health check failed: {e}")
        return False

if __name__ == '__main__':
    if not check_backend_health():
        sys.exit(1)
```

#### Automated Cleanup Script

```python
#!/usr/bin/env python
# scripts/cleanup_ratelimit.py
import os
import sys
import django
from django.core.management import call_command

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

def cleanup_ratelimit_data():
    """Automated cleanup of rate limit data."""
    try:
        # Dry run first
        print("🔍 Checking what would be cleaned...")
        call_command('cleanup_ratelimit', '--dry-run', '--verbose')

        # Actual cleanup
        print("🧹 Starting cleanup...")
        call_command('cleanup_ratelimit', '--verbose', '--batch-size', '1000')

        print("✅ Cleanup completed successfully")
        return True

    except Exception as e:
        print(f"❌ Cleanup failed: {e}")
        return False

if __name__ == '__main__':
    if not cleanup_ratelimit_data():
        sys.exit(1)
```

## Development Best Practices

### Code Style Guidelines

1. **Follow PEP 8** with line length of 88 characters
2. **Use type hints** for all function parameters and return values
3. **Add docstrings** for all public functions and classes
4. **Use descriptive variable names** and avoid abbreviations
5. **Keep functions small** and focused on single responsibility

### Testing Guidelines

1. **Write comprehensive tests** for all new features
2. **Include edge cases** and error conditions
3. **Use meaningful test names** that describe the scenario
4. **Mock external dependencies** (Redis, database) when appropriate
5. **Test both success and failure paths**

### Documentation Standards

1. **Update README** for user-facing changes
2. **Add docstrings** with examples for complex functions
3. **Update CHANGELOG** for all changes
4. **Include configuration examples** for new features
5. **Add migration guides** for breaking changes
