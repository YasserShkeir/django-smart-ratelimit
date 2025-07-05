# Contributing to Django Smart Ratelimit

Thank you for your interest in contributing to Django Smart Ratelimit! This document provides guidelines and instructions for contributing to the project.

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for all contributors.

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
