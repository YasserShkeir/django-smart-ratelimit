# Release Guide for Django Smart Ratelimit

## Quick Release Checklist

### 1. Pre-Release Preparation
- [ ] Run tests: `python3 -m pytest`
- [ ] Update version in `django_smart_ratelimit/__init__.py`
- [ ] Update `CHANGELOG.md` with new version
- [ ] Update `README.md` if needed
- [ ] Commit all changes

### 2. Create GitHub Release
- [ ] Go to GitHub repository
- [ ] Click "Releases" → "Create a new release"
- [ ] Tag version: `v0.1.1` (for example)
- [ ] Release title: `v0.1.1`
- [ ] Description: Copy from CHANGELOG.md
- [ ] Click "Publish release"

### 3. Automated Publishing
Once you create a GitHub release, the GitHub Action will automatically:
- Build the package
- Run tests
- Publish to PyPI

### 4. Manual Publishing (if needed)
If you need to publish manually:

```bash
# Clean previous builds
rm -rf dist/ build/

# Build package
python3 -m build

# Check package
python3 -m twine check dist/*

# Upload to PyPI
python3 -m twine upload dist/*
```

## Version Management

### Update Version
Edit `django_smart_ratelimit/__init__.py`:
```python
__version__ = "0.1.1"  # Update this
```

### Update Changelog
Edit `CHANGELOG.md`:
```markdown
## [0.1.1] - 2025-07-05

### Added
- New feature X

### Fixed
- Bug fix Y

### Changed
- Improvement Z
```

## PyPI Links

- **Package**: https://pypi.org/project/django-smart-ratelimit/
- **Test Package**: https://test.pypi.org/project/django-smart-ratelimit/

## GitHub Secrets Required

Make sure these secrets are set in your GitHub repository:

1. **PYPI_API_TOKEN**: Your PyPI API token
   - Go to: Repository → Settings → Secrets and variables → Actions
   - Add secret: `PYPI_API_TOKEN`
   - Value: Your PyPI API token (starts with `pypi-`)

## Installation Commands for Users

### Basic Installation
```bash
pip install django-smart-ratelimit
```

### With Development Dependencies
```bash
pip install django-smart-ratelimit[dev]
```

### Latest Version
```bash
pip install --upgrade django-smart-ratelimit
```

## Post-Release Tasks

After each release:
- [ ] Verify package appears on PyPI
- [ ] Test installation: `pip install django-smart-ratelimit`
- [ ] Update any documentation that references version numbers
- [ ] Announce on social media / forums if major release
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
