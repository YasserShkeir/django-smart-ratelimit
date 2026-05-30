# Manual QA scripts

These scripts are **manual-only**. They are *not* part of the automated pytest
suite and are intentionally excluded from collection (see
`norecursedirs = ["tests/test_project/scripts"]` in `pyproject.toml`).

They exist for ad-hoc, exploratory QA against the bundled `test_project` Django
app — driving real requests, exercising specific backends, simulating
concurrency/load, and running scenario verifications by hand. Many of them
expect a running server, a live backend (Redis / a real database), or seeded
test data, so they are unsuitable for CI.

## Running

Run an individual script from the repository root with the project's
virtualenv, e.g.:

```bash
python tests/test_project/scripts/<script>.py
```

Some scripts assume the `test_project` server is up and/or that QA data has been
created first (for example via `create_qa_users.py` / `run_verification.py`).
Read the top of each script for its specific prerequisites before running it.

The automated, CI-safe tests live under `tests/` (e.g. `tests/unit/`,
`tests/integration/`, `tests/algorithms/`); use `pytest` for those.
