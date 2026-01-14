# Contributing to Django Smart Ratelimit (Core)

Thank you for your interest in contributing to **Django Smart Ratelimit**! This core library allows us to provide a high-performance, stateless rate-limiting solution for the Django ecosystem.

> **Note on Architecture**: This repository contains the **Core** library (`django-ratelimit/`). Database-backed features (Models, Admin, DB Backend) are part of the **Pro** package (`django-smart-ratelimit-pro`). This guide focuses on contributing to the Core.

## 🤝 Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for all contributors.

## 🚀 Development Setup

### Prerequisites

- **Python**: 3.9 or higher
- **Redis**: Required for running the full test suite (install via Docker or local package manager)
- **Git**

### Initial Setup

1. **Clone the repository**:

   ```bash
   git clone https://github.com/YasserShkeir/django-smart-ratelimit.git
   cd django-smart-ratelimit/django-ratelimit
   ```

2. **Create Environment**:
   We provide a `Makefile` to simplify common tasks.

   ```bash
   # Create venv and install dependencies
   make dev
   ```

   _Alternatively, manually:_

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -e ".[dev]"
   pre-commit install
   ```

3. **Verify Installation**:
   ```bash
   make test-quick
   ```

## 🛠 Command Reference

We use a `Makefile` to standardize development commands. Always use these to ensure you're running with the correct settings.

| Command           | Description                                           |
| ----------------- | ----------------------------------------------------- |
| `make dev`        | Setup development environment (install deps & hooks)  |
| `make test`       | Run full test suite with HTML coverage report         |
| `make test-quick` | Run tests without HTML report (faster)                |
| `make lint`       | Run **pre-commit** hooks (Black, Isort, Flake8, etc.) |
| `make format`     | Auto-format code using Black and Isort                |
| `make ci-check`   | Run all CI checks locally (Lint + Test + Security)    |
| `make clean`      | Clean up build artifacts and cache                    |

## 🧪 Testing

Our test suite is comprehensive (340+ tests). All contributions **must** pass tests.

### Test Structure

- `tests/core/`: Decorators, Middleware, Utilities.
- `tests/backends/`: Redis, Memory, MongoDB, MultiBackend implementations.
- `tests/algorithms/`: Token Bucket, Sliding Window logic.
- `tests/integration/`: Django integration tests.
- `tests/performance/`: Benchmarks.

### Running Tests

```bash
# Run all tests
make test

# Run a specific test file
./run_with_venv.sh pytest tests/core/test_decorator.py
```

## 📝 Coding Standards

### Style & Formatting

We strictly enforce **PEP 8** + opinionated formatting via **Black** and **Isort**.

- **Run `make format`** before committing to auto-fix style issues.
- **Run `make lint`** to catch issues that auto-formatting can't fix.

### Type Safety

We use **mypy** for static type checking.

- All new functions must have type hints.
- Do not use `Any` unless absolutely necessary.

### AI Usage Policy

- **Authorized**: You may use AI to generate tests, docstrings, or boilerplate.
- **Review Required**: ALL AI-generated code must be reviewed by you. Use `make lint` and `make test` to validate it.
- **Transparency**: Mention if a significant portion of a PR was AI-generated.

## 📦 Pull Request Process

1. **Branching**: Create a branch off `main`.
   - Format: `type/description` (e.g., `feat/add-new-backend`, `fix/concurrency-bug`)
2. **Commit Messages**: We follow [Conventional Commits](https://www.conventionalcommits.org/).
   - `feat: ...` for new features
   - `fix: ...` for bug fixes
   - `docs: ...` for documentation
   - `refactor: ...` for code restructuring
3. **Changes**:
   - Write tests for your changes.
   - Update documentation if needed.
   - Ensure `make ci-check` passes locally.
4. **Submit**: Open a PR against `main`.

## ⚠️ Breaking Changes (v1.0.0+)

Since v1.0.0, the Core library is **Stateless**.

- **Do not** introduce Django Models or database migrations in this package.
- **Do not** add dependencies that are not strictly necessary for a lightweight core.
- If you need to store state (e.g., for a new backend), ensure it implements the standard `BaseBackend` interface.

Thank you for contributing! 💙
