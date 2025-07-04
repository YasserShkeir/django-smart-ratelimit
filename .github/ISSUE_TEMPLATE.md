---
name: Bug Report
about: Create a report to help us improve
title: '[BUG] '
labels: bug
assignees: ''

---

## Bug Description
A clear and concise description of what the bug is.

## Steps to Reproduce
1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

## Expected Behavior
A clear and concise description of what you expected to happen.

## Actual Behavior
A clear and concise description of what actually happened.

## Error Messages
If applicable, paste any error messages or stack traces here.

```
Paste error messages here
```

## Environment
- **Python version**: (e.g., 3.9.0)
- **Django version**: (e.g., 4.2.0)
- **django-smart-ratelimit version**: (e.g., 0.1.0)
- **Redis version**: (e.g., 6.2.0)
- **Operating System**: (e.g., Ubuntu 20.04)

## Configuration
Please share your rate limiting configuration:

```python
# settings.py
RATELIMIT_MIDDLEWARE = {
    # Your configuration here
}

# Or decorator usage
@rate_limit(key='...', rate='...', block=...)
```

## Additional Context
Add any other context about the problem here. Screenshots, logs, or other relevant information.

## Possible Solution
If you have ideas about how to fix the bug, please share them here.

## Checklist
- [ ] I have searched for existing issues before creating this one
- [ ] I have provided all the requested information
- [ ] I have tested this with the latest version of the library
