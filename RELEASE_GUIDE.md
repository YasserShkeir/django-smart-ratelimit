# Release Guide for Django Smart Ratelimit

## Quick Release Checklist

### 1. Pre-Release Preparation

- [ ] Run all tests: `make ci-check`
- [ ] Update `CHANGELOG.md` with new version entry
- [ ] Update `README.md` if needed
- [ ] Commit changelog changes: `git commit -am "docs: Update CHANGELOG for vX.Y.Z"`
- [ ] Push to GitHub: `git push origin main`
- [ ] Ensure working tree is clean and you are on the `main` branch

### 2. Automated Release (Recommended)

Use the Makefile for a fully automated release:

```bash
make release VERSION=X.Y.Z
```

The `make release` command will:

1. Verify you are on main branch with clean working tree
2. Update version in `__init__.py`, `pyproject.toml`, etc.
3. Commit the version bump
4. Push commit to `origin/main`
5. Create and push tag `vX.Y.Z`
6. GitHub Actions automatically publishes to PyPI (triggered by tag)

### 3. What Happens Automatically

Once the tag is pushed, GitHub Actions will build the package, check package integrity, and publish to PyPI using `PYPI_API_TOKEN`. No manual PyPI interaction needed.

### 4. Manual Publishing (Emergency Only)

If automation fails and you need to publish manually:

```bash
rm -rf dist/ build/
python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*
```

## Version Management

### Automated Version Update (Recommended)

The `make release VERSION=X.Y.Z` command automatically updates version in:

- `django_smart_ratelimit/__init__.py`
- `examples/integrations/drf_integration/__init__.py`
- `pyproject.toml`

You only need to manually update `CHANGELOG.md` before running the release command.

### Manual Version Update (If Needed)

Edit `django_smart_ratelimit/__init__.py`:

```python
__version__ = "X.Y.Z"
```

Edit `examples/integrations/drf_integration/__init__.py`:

```python
__version__ = "X.Y.Z"  # Keep in sync
```

Edit `pyproject.toml`:

```toml
current_version = "X.Y.Z"  # Keep in sync
```

### Update Changelog (Always Manual)

Edit `CHANGELOG.md` and add a new version entry:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Fixed

- Bug fix description

### Added

- New feature description

### Changed

- Improvement description
```

## PyPI Links

- **Package**: https://pypi.org/project/django-smart-ratelimit/
- **Test Package**: https://test.pypi.org/project/django-smart-ratelimit/

## GitHub Secrets Required

Make sure these secrets are set in your GitHub repository:

1. **PYPI_API_TOKEN**: Your PyPI API token
   - Go to: Repository > Settings > Secrets and variables > Actions
   - Add secret: `PYPI_API_TOKEN`
   - Value: Your PyPI API token (starts with `pypi-`)

## Installation Commands for Users

```bash
# Basic
pip install django-smart-ratelimit

# With Redis support
pip install django-smart-ratelimit[redis]

# With development dependencies
pip install django-smart-ratelimit[dev]

# Upgrade to latest
pip install --upgrade django-smart-ratelimit
```

## Post-Release Tasks

After each release:

- [ ] Verify package appears on PyPI
- [ ] Test installation: `pip install django-smart-ratelimit`
- [ ] Update any documentation that references version numbers
- [ ] Announce on social media if major release
- [ ] Update project dependencies if needed

## Troubleshooting

### Common Issues

1. **Upload Failed**: Check API token is correct
2. **Version Conflict**: Ensure version number is unique
3. **Build Failed**: Check `pyproject.toml` syntax
4. **Tests Failed**: Fix tests before releasing

### Getting Help

- Check GitHub Actions logs for build errors
- Review PyPI upload logs
- Verify all required files are included in the build
