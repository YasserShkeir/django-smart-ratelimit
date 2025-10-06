.PHONY: help install test lint format clean build upload docs current-version check-versions release release-patch release-minor release-major ci-check

# Python environment
PYTHON := ./run_with_venv.sh python
PIP := ./run_with_venv.sh pip
PYTEST := ./run_with_venv.sh pytest
MYPY := ./run_with_venv.sh mypy
PRECOMMIT := ./run_with_venv.sh pre-commit
BANDIT := ./run_with_venv.sh bandit

help:
	@echo "Available commands:"
	@echo "  install         Install package and development dependencies"
	@echo "  test            Run tests with coverage"
	@echo "  test-quick      Run tests without HTML coverage report"
	@echo "  lint            Run linting checks (pre-commit hooks)"
	@echo "  format          Format code with black and isort"
	@echo "  ci-check        Run all CI checks locally (tests, lint, type-check, security)"
	@echo "  clean           Remove build artifacts"
	@echo "  build           Build package"
	@echo "  upload          Upload package to PyPI"
	@echo "  docs            Build documentation"
	@echo "  dev             Setup development environment"
	@echo "  current-version Show current version"
	@echo "  check-versions  Check all version references across files"
	@echo "  release         Release new version (Usage: make release VERSION=0.7.4)"

install:
	$(PIP) install -e ".[dev]"

test:
	$(PYTEST) --cov=django_smart_ratelimit --cov-report=html --cov-report=term-missing

test-quick:
	$(PYTEST) --cov=django_smart_ratelimit --cov-report=term-missing

lint:
	$(PRECOMMIT) run --all-files

format:
	$(PYTHON) -m black django_smart_ratelimit tests examples
	$(PYTHON) -m isort django_smart_ratelimit tests examples

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	python -m build

upload: build
	twine upload dist/*

upload-test: build
	twine upload --repository testpypi dist/*

docs:
	@echo "Documentation is in docs/ directory"
	@echo "README.md contains the main documentation"

dev: install
	pre-commit install
	@echo "Development environment setup complete!"
	@echo "Run 'make test' to run tests"
	@echo "Run 'make lint' to check code quality"

# Check if Redis is running
redis-check:
	@redis-cli ping > /dev/null 2>&1 && echo "Redis is running" || echo "Redis is not running"

# Run tests with different Django versions
test-django-32:
	pip install "Django>=3.2,<3.3"
	pytest

test-django-42:
	pip install "Django>=4.2,<4.3"
	pytest

test-django-50:
	pip install "Django>=5.0,<5.1"
	pytest

# Security checks
security:
	safety check
	bandit -r django_smart_ratelimit/

# Pre-commit hooks
pre-commit:
	pre-commit run --all-files

# Run all CI checks locally (matches GitHub Actions CI)
ci-check:
	@echo "=========================================="
	@echo "Running all CI checks locally..."
	@echo "=========================================="
	@echo ""
	@echo "1️⃣  Running pre-commit hooks (lint)..."
	@echo "------------------------------------------"
	$(PRECOMMIT) run --all-files
	@echo ""
	@echo "2️⃣  Running type checks (mypy)..."
	@echo "------------------------------------------"
	$(MYPY) django_smart_ratelimit
	@echo ""
	@echo "3️⃣  Running security checks (bandit)..."
	@echo "------------------------------------------"
	$(BANDIT) -r django_smart_ratelimit/
	@echo ""
	@echo "4️⃣  Running tests with coverage..."
	@echo "------------------------------------------"
	$(PYTEST) --cov=django_smart_ratelimit --cov-report=term-missing -q
	@echo ""
	@echo "=========================================="
	@echo "✅ All CI checks passed!"
	@echo "=========================================="

# Get current version
current-version:
	@$(PYTHON) -c "import django_smart_ratelimit; print(f'Current version: {django_smart_ratelimit.__version__}')"

# Check all version references in the project
check-versions:
	@echo "Checking version references across all files:"
	@echo "django_smart_ratelimit/__init__.py:"
	@grep "__version__" django_smart_ratelimit/__init__.py
	@echo "examples/integrations/drf_integration/__init__.py:"
	@grep "__version__" examples/integrations/drf_integration/__init__.py
	@echo "pyproject.toml:"
	@grep "current_version" pyproject.toml
	@echo "CHANGELOG.md (latest):"
	@head -15 CHANGELOG.md | grep -E "^\## \[" | head -2

# Release workflow - Automated version bump and tag creation
# Usage: make release VERSION=0.8.9
# Prerequisites:
#   1. Update CHANGELOG.md manually before running
#   2. Ensure working tree is clean
#   3. Ensure you're on main branch
# This will:
#   1. Update version in all files
#   2. Commit the version bump
#   3. Push commit to origin/main
#   4. Create and push tag (triggers PyPI publish via GitHub Actions)
release:
	@if [ -z "$(VERSION)" ]; then \
		echo "❌ Error: VERSION not specified."; \
		echo "Usage: make release VERSION=0.8.9"; \
		exit 1; \
	fi
	@echo "🔍 Pre-flight checks..."
	@if [ "$$(git branch --show-current)" != "main" ]; then \
		echo "❌ Error: Not on main branch. Switch to main first."; \
		exit 1; \
	fi
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "❌ Error: Working tree is not clean. Commit or stash changes first."; \
		git status --short; \
		exit 1; \
	fi
	@echo "✅ On main branch and working tree is clean"
	@echo ""
	@echo "📝 Updating version to $(VERSION)..."
	@sed -i '' 's/__version__ = ".*"/__version__ = "$(VERSION)"/' django_smart_ratelimit/__init__.py
	@sed -i '' 's/__version__ = ".*"/__version__ = "$(VERSION)"/' examples/integrations/drf_integration/__init__.py
	@sed -i '' 's/current_version = ".*"/current_version = "$(VERSION)"/' pyproject.toml
	@echo "✅ Version updated in all files"
	@echo ""
	@echo "📦 Committing version bump..."
	@git add django_smart_ratelimit/__init__.py examples/integrations/drf_integration/__init__.py pyproject.toml
	@git commit -m "bump: version $(VERSION)"
	@echo "✅ Version bump committed"
	@echo ""
	@echo "⬆️  Pushing commit to origin/main..."
	@git push origin main
	@echo "✅ Commit pushed"
	@echo ""
	@echo "🏷️  Creating and pushing tag v$(VERSION)..."
	@git tag -a v$(VERSION) -m "Release v$(VERSION)"
	@git push origin v$(VERSION)
	@echo "✅ Tag v$(VERSION) pushed"
	@echo ""
	@echo "=========================================="
	@echo "🎉 Release $(VERSION) completed successfully!"
	@echo "=========================================="
	@echo ""
	@echo "📋 Next steps:"
	@echo "  1. Monitor GitHub Actions: https://github.com/YasserShkeir/django-smart-ratelimit/actions"
	@echo "  2. The tag push will trigger automatic PyPI publication"
	@echo "  3. Verify on PyPI: https://pypi.org/project/django-smart-ratelimit/"
	@echo "  4. (Optional) Create GitHub Release: https://github.com/YasserShkeir/django-smart-ratelimit/releases/new?tag=v$(VERSION)"
