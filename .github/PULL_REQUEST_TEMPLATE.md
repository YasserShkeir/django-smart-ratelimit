## Description
Brief description of the changes in this pull request.

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Code refactoring
- [ ] Other (please describe):

## Testing
- [ ] I have added tests for my changes
- [ ] All existing tests pass
- [ ] I have tested the changes manually
- [ ] I have tested with multiple Django versions (if applicable)
- [ ] I have tested with multiple Python versions (if applicable)

## Documentation
- [ ] I have updated the README.md (if needed)
- [ ] I have updated the documentation (if needed)
- [ ] I have added docstrings to new functions/classes
- [ ] I have updated type hints

## Code Quality
- [ ] I have run `black` to format the code
- [ ] I have run `flake8` and fixed any linting issues
- [ ] I have run `mypy` and fixed any type checking issues
- [ ] I have run the pre-commit hooks
- [ ] My code follows the project's style guidelines

## Backwards Compatibility
- [ ] This change is backwards compatible
- [ ] This change requires a migration or configuration update
- [ ] This change breaks existing functionality (requires major version bump)

## Related Issues
Fixes #(issue number)
Closes #(issue number)
Related to #(issue number)

## Screenshots/Examples
If applicable, add screenshots or code examples to help explain your changes.

```python
# Example usage
@rate_limit(key='user', rate='10/m')
def my_view(request):
    pass
```

## Checklist
- [ ] I have read the contributing guidelines
- [ ] I have signed off my commits (if required)
- [ ] I have squashed my commits into logical units
- [ ] I have written clear commit messages
- [ ] I have tested my changes thoroughly
- [ ] I have documented any new functionality

## Additional Notes
Add any other notes about the pull request here.
