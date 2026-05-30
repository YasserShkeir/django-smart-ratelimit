# Contributing to Django Smart Ratelimit

Thank you for your interest in contributing to Django Smart Ratelimit. This library provides a high-performance rate limiting solution for the Django ecosystem.

> **Note on Architecture**: This repository contains the open-source core library. It works with cache/memory backends out of the box and also ships an optional Django ORM (database) backend, with the supporting models and migrations, for deployments that prefer SQL persistence over Redis.

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

The test suite includes 1200+ tests. All contributions must pass tests.

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

## Backend Contributions

- Keep the core lightweight: do not add dependencies that are not strictly necessary, and gate optional integrations (Redis, MongoDB, DRF, Prometheus, OpenTelemetry) behind optional extras.
- New storage backends must implement the standard `BaseBackend` interface so they are interchangeable with the existing Redis, memory, MongoDB, and database backends.
- The database backend ships its own Django models and migrations; if you change them, include a migration and keep PostgreSQL, MySQL, and SQLite working.

Thank you for contributing.
