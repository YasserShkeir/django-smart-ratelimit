# DRF Integration Tests

This directory contains comprehensive tests for Django REST Framework (DRF) integration with Django Smart Ratelimit.

## Files Overview

### Test Files

- **`test_drf_integration.py`** - Full DRF integration tests (requires DRF to be installed)
- **`test_drf_mock.py`** - Mock-based DRF tests (works without DRF installation)

### Configuration Files

- **`settings_drf.py`** - Django settings optimized for DRF integration testing
- **`conftest_drf.py`** - Pytest fixtures and configuration for DRF tests
- **`run_drf_tests.py`** - Standalone test runner for DRF integration tests

## Running Tests

### All DRF Integration Tests

```bash
# Run all DRF integration tests
python -m pytest tests/drf_integration/ -v

# Run only mock tests (no DRF required)
python -m pytest tests/drf_integration/test_drf_mock.py -v

# Run only full DRF integration tests
python -m pytest tests/drf_integration/test_drf_integration.py -v
```

### Using the Test Runner

```bash
# Run DRF tests with custom runner
python tests/drf_integration/run_drf_tests.py
```

## Test Coverage

### DRF Integration Tests (`test_drf_integration.py`)

- ✅ APIView rate limiting with IP and user-based keys
- ✅ ViewSet rate limiting with different HTTP methods
- ✅ Permission-based rate limiting integration
- ✅ Serializer validation with rate limiting
- ✅ Custom key functions for rate limiting
- ✅ Method-specific rate limiting (GET/POST/PUT)
- ✅ Role-based rate limiting (staff vs regular users)
- ✅ Conditional rate limiting based on request parameters
- ✅ Bulk operations rate limiting
- ✅ Error handling for rate limit exceeded scenarios
- ✅ Rate limit key generation utilities
- ✅ Dynamic rate limit calculation
- ✅ Bypass conditions for rate limiting

### Mock Tests (`test_drf_mock.py`)

- ✅ Mock DRF components without requiring full DRF setup
- ✅ Rate limiting behavior simulation
- ✅ Key function helpers and utilities
- ✅ Time-based rate limiting scenarios

## Requirements

- **For `test_drf_integration.py`**: Django REST Framework must be installed
- **For `test_drf_mock.py`**: No additional requirements beyond Django Smart Ratelimit

## Test Status

✅ **All 25 tests passing** (14 integration + 11 mock tests)
