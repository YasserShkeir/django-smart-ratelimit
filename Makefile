.PHONY: help install test lint format clean build upload docs

# Python environment
PYTHON := ./run_with_venv.sh python
PIP := ./run_with_venv.sh pip
PYTEST := ./run_with_venv.sh pytest
MYPY := ./run_with_venv.sh mypy
PRECOMMIT := ./run_with_venv.sh pre-commit

help:
	@echo "Available commands:"
	@echo "  install    Install package and development dependencies"
	@echo "  test       Run tests with coverage"
	@echo "  lint       Run linting checks"
	@echo "  format     Format code with black and isort"
	@echo "  clean      Remove build artifacts"
	@echo "  build      Build package"
	@echo "  upload     Upload package to PyPI"
	@echo "  docs       Build documentation"
	@echo "  dev        Setup development environment"

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

# Release workflow
release-patch:
	bumpversion patch
	git push
	git push --tags

release-minor:
	bumpversion minor
	git push
	git push --tags

release-major:
	bumpversion major
	git push
	git push --tags
