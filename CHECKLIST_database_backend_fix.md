# Database Backend Issue Checklist

## Investigation

- [x] Review existing automated tests covering the database backend (e.g. `tests/backends/test_database_backend.py`).
- [x] Inspect the database backend implementation in `django_smart_ratelimit/backends/database.py` for suspicious logic around the reported issue.
- [x] Set up and run the baseline backend-specific tests locally to confirm the current failure state.
- [x] Execute the reproducible scenario inside `/Users/yassershkeir/Documents/GitHub/django-ratelimit-base/django-test-project` to observe the problem end-to-end before modifying code.
- [x] Capture failing behaviour, stack traces, or inconsistent state for reference.

## Fix

- [x] Design a fix that resolves the identified root cause without regressing other functionality.
- [x] Add or update automated tests (unit/integration) that expose the bug and verify the fix.
- [x] Implement the code changes in `django_smart_ratelimit/backends/database.py` (or related modules) guided by the failing scenario.

## Verification

- [x] Re-run the relevant automated tests in `django-ratelimit` after applying the fix to ensure they pass.
- [x] Re-run the scenario/tests in `/Users/yassershkeir/Documents/GitHub/django-test-project` to confirm the issue is resolved.
- [x] Perform targeted sanity checks for other backends or shared utilities if impacted.

## Wrap-up

- [x] Update documentation or changelog entries if the user-facing behaviour changes.
- [x] Ensure formatting, linting, and CI checks (`make ci-check`) pass.
- [x] Mark the checklist items above as complete before submitting the fix.
