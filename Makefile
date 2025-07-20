.PHONY: help install test lint format clean build upload docs current-version check-versions release release-patch release-minor release-major

# Python environment
PYTHON := ./run_with_venv.sh python
PIP := ./run_with_venv.sh pip
PYTEST := ./run_with_venv.sh pytest
MYPY := ./run_with_venv.sh mypy
PRECOMMIT := ./run_with_venv.sh pre-commit

help:
	@echo "Available commands:"
	@echo "  install         Install package and development dependencies"
	@echo "  test            Run tests with coverage"
	@echo "  lint            Run linting checks"
	@echo "  format          Format code with black and isort"
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
	@echo "docs/index.md:"
	@grep "__version__" docs/index.md
	@echo "pyproject.toml:"
	@grep "current_version" pyproject.toml
	@echo "CHANGELOG.md (latest):"
	@head -15 CHANGELOG.md | grep -E "^\## \[" | head -2

# Release workflow - manual version specification
# Usage: make release VERSION=0.*.*
release:
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION not specified. Usage: make release VERSION=0.7.4"; \
		exit 1; \
	fi
	@echo "Updating version to $(VERSION)..."
	@sed -i '' 's/__version__ = ".*"/__version__ = "$(VERSION)"/' django_smart_ratelimit/__init__.py
	@sed -i '' 's/__version__ = ".*"/__version__ = "$(VERSION)"/' examples/integrations/drf_integration/__init__.py
	@sed -i '' "s/__version__ = '.*'/__version__ = '$(VERSION)'/" docs/index.md
	@sed -i '' 's/current_version = ".*"/current_version = "$(VERSION)"/' pyproject.toml
	@sed -i '' 's/## \[Unreleased\]/## [Unreleased]\n\n## [$(VERSION)] - $(shell date +%Y-%m-%d)/' CHANGELOG.md
	git add .
	git commit -m "bump: version $(VERSION)"
	git tag -a v$(VERSION) -m "Release v$(VERSION)"
	git push origin main v$(VERSION)
	@echo "Released version $(VERSION) successfully!"

# Quick release shortcuts
release-patch:
	@echo "Please use: make release VERSION=x.x.x"
	@echo "Current version:"
	@$(PYTHON) -c "import django_smart_ratelimit; print(django_smart_ratelimit.__version__)"

release-minor:
	@echo "Please use: make release VERSION=x.x.x"
	@echo "Current version:"
	@$(PYTHON) -c "import django_smart_ratelimit; print(django_smart_ratelimit.__version__)"

release-major:
	@echo "Please use: make release VERSION=x.x.x"
	@echo "Current version:"
	@$(PYTHON) -c "import django_smart_ratelimit; print(django_smart_ratelimit.__version__)"
