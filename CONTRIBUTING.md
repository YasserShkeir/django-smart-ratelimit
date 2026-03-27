# Contributing to Django Smart Ratelimit

Thank you for your interest in contributing to Django Smart Ratelimit. This core library provides a high-performance, stateless rate limiting solution for the Django ecosystem.

> **Note on Architecture**: This repository contains the core library. Database-backed features (models, admin, DB backend) are part of the Pro package (`django-smart-ratelimit-pro`). This guide focuses on contributing to the core.

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for all contributors.

## Development Setup

### Prerequisites

- Python 3.9 or higher
- Redis (required for running the full test suite)
- Git

### Initial Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/YasserShkeir/django-smart-ratelimit.git
   cd django-smart-ratelimit
   ```

2. Create environment (using the provided Makefile):

   ```bash
   make dev
   ```

   Or manually:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -e ".[dev]"
   pre-commit install
   pre-commit install --hook-type commit-msg
   ```

3. Verify installation:

   ```bash
   make test-quick
   ```

## Command Reference

| Command | Description |
| --- | --- |
| `make dev` | Set up development environment (install deps and hooks) |
| `make test` | Run full test suite with HTML coverage report |
| `make test-quick` | Run tests without HTML report (faster) |
| `make lint` | Run pre-commit hooks (Black, Isort, Flake8, etc.) |
| `make format` | Auto-format code using Black and Isort |
| `make ci-check` | Run all CI checks locally (lint + test + security) |
| `make clean` | Clean up build artifacts and cache |

## Testing

The test suite includes 760+ tests. All contributions must pass tests.

### Test Structure

- `tests/core/` -- Decorators, middleware, utilities
- `tests/backends/` -- Redis, memory, MongoDB, multi-backend implementations
- `tests/algorithms/` -- Token bucket, sliding window logic
- `tests/integration/` -- Django integration tests
- `tests/performance/` -- Benchmarks

### Running Tests

```bash
# Fast feedback (unit tests only, ~30 seconds)
pytest -m unit

# Standard suite (skip slow benchmarks, ~3 minutes)
make test-fast

# Full regression (everything, ~10 minutes)
make test
```

### Test Markers

- `unit` -- Fast, isolated tests mocking external dependencies
- `integration` -- Tests requiring real Redis/DB services
- `slow` -- Long-running tests
- `benchmark` -- Performance tests (excluded from CI by default)

## Coding Standards

### Style and Formatting

We enforce PEP 8 with Black and Isort. Run `make format` before committing to auto-fix style issues, and `make lint` to catch issues that auto-formatting cannot fix.

### Type Safety

We use mypy for static type checking. All new functions must have type hints. Do not use `Any` unless absolutely necessary.

## Pull Request Process

1. **Branching**: Create a branch off `main` using the format `type/description` (e.g., `feat/add-new-backend`, `fix/concurrency-bug`).

2. **Commit Messages**: Follow [Conventional Commits](https://www.conventionalcommits.org/) -- `feat:` for new features, `fix:` for bug fixes, `docs:` for documentation, `refactor:` for code restructuring.

3. **Changes**: Write tests for your changes, update documentation if needed, and ensure `make ci-check` passes locally.

4. **Submit**: Open a PR against `main`.

## Breaking Changes (v1.0.0+)

Since v1.0.0, the core library is stateless.

- Do not introduce Django models or database migrations in this package.
- Do not add dependencies that are not strictly necessary for a lightweight core.
- If you need to store state (e.g., for a new backend), ensure it implements the standard `BaseBackend` interface.

Thank you for contributing.
