# Release Guide for Django Smart Ratelimit

This project uses [Commitizen](https://commitizen-tools.github.io/commitizen/)
for version bumping and tagging, and GitHub Actions for publishing. Pushing a
version tag (`vX.Y.Z`) is the single source of truth that triggers a release.

## Version sources

Commitizen is configured in `pyproject.toml` (`[tool.commitizen]`) and keeps the
version in sync across:

- `django_smart_ratelimit/__init__.py` (`__version__`)
- `pyproject.toml` (`version`)

Tags use the format `v$version` (e.g. `v4.0.0`).

## Quick Release Checklist

### 1. Pre-Release Preparation

- [ ] Ensure you are on the `main` branch with a clean working tree
- [ ] Pull the latest changes: `git pull origin main`
- [ ] Run the local checks: `make ci-check`
- [ ] Make sure your commits follow Conventional Commits (Commitizen derives the
      next version and the changelog from them)

### 2. Bump the version with Commitizen (Recommended)

```bash
# Auto-detect the next version from the commit history and update the
# version files, the CHANGELOG, create the bump commit and the vX.Y.Z tag:
cz bump --changelog

# Then push the commit and the tag:
git push origin main --follow-tags
```

To force a specific bump level instead of auto-detection:

```bash
cz bump --increment MAJOR --changelog   # or MINOR / PATCH
```

`cz bump` will:

1. Determine the new version (from commit history, or the `--increment` you pass)
2. Update the version in `django_smart_ratelimit/__init__.py` and `pyproject.toml`
3. Update `CHANGELOG.md`
4. Create the bump commit and the `vX.Y.Z` tag

Pushing the tag triggers the publish workflow (see below).

### 3. Makefile shortcut (alternative)

`make release VERSION=X.Y.Z` performs an equivalent bump-and-tag flow with an
explicit version. It checks you are on `main` with a clean tree, updates the
version in `django_smart_ratelimit/__init__.py` and `pyproject.toml`, commits,
pushes `main`, and creates and pushes the `vX.Y.Z` tag.

> Prefer `cz bump` for normal releases so the version and changelog are derived
> from the commit history. Use `make release` only when you need to pin an exact
> version manually.

### 4. What Happens Automatically

Once the `vX.Y.Z` tag is pushed, the `Publish to PyPI` workflow
(`.github/workflows/publish.yml`) will:

1. Build the package and run `twine check`
2. Publish to TestPyPI (advisory; failures do not block the release)
3. Publish to PyPI using `PYPI_API_TOKEN` (uses `skip-existing`, so re-running
   for an already-published version is a no-op)
4. Create the GitHub Release with auto-generated release notes

No manual PyPI interaction is needed.

### 5. Manual Publishing (Emergency Only)

If automation fails and you need to publish manually:

```bash
rm -rf dist/ build/
python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*
```

## Manual Version Update (If Needed)

If you cannot use Commitizen, update both version sources and keep them in sync:

`django_smart_ratelimit/__init__.py`:

```python
__version__ = "X.Y.Z"
```

`pyproject.toml`:

```toml
version = "X.Y.Z"
```

Then add a matching entry to `CHANGELOG.md`:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added

- New feature description

### Changed

- Improvement description

### Fixed

- Bug fix description
```

Finally, create and push the tag to trigger the release:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin main --follow-tags
```

## PyPI Links

- **Package**: https://pypi.org/project/django-smart-ratelimit/
- **Test Package**: https://test.pypi.org/project/django-smart-ratelimit/

## GitHub Secrets Required

Make sure these secrets are set in your GitHub repository
(Settings > Secrets and variables > Actions):

1. **PYPI_API_TOKEN** — PyPI API token (starts with `pypi-`), used to publish to
   PyPI.
2. **TEST_PYPI_API_TOKEN** — TestPyPI API token, used for the advisory TestPyPI
   upload (optional; the step continues on error if it is missing).
3. **CODECOV_TOKEN** — used by CI to upload coverage (optional).

> The publish workflow also relies on the automatically provided
> `GITHUB_TOKEN` to create the GitHub Release.

## Installation Commands for Users

```bash
# Basic
pip install django-smart-ratelimit

# With Redis support
pip install django-smart-ratelimit[redis]

# With all optional backends/integrations
pip install django-smart-ratelimit[all]

# With development dependencies
pip install django-smart-ratelimit[dev]

# Upgrade to latest
pip install --upgrade django-smart-ratelimit
```

## Post-Release Tasks

After each release:

- [ ] Verify the package appears on PyPI
- [ ] Test installation: `pip install django-smart-ratelimit`
- [ ] Verify the GitHub Release was created with correct notes
- [ ] Update any documentation that references version numbers

## Troubleshooting

### Common Issues

1. **Upload Failed**: Check the `PYPI_API_TOKEN` secret is correct.
2. **Version Conflict**: Ensure the version number is unique. The publish job
   uses `skip-existing`, so an already-published version is silently skipped.
3. **Build Failed**: Check `pyproject.toml` syntax.
4. **Wrong/Missing Changelog**: Ensure your commits follow Conventional Commits
   so `cz bump` can generate the changelog.

### Getting Help

- Check the GitHub Actions logs for build/publish errors.
- Review the PyPI upload logs.
- Verify all required files are included in the build (`twine check dist/*`).
