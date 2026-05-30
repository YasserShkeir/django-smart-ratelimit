# Examples

Small, self-contained examples that show how to use `django-smart-ratelimit`.
Each example is a snippet you copy into your own Django project, not a runnable
project on its own. The code is written against the real public API.

| Directory                            | Shows                                                              |
| ------------------------------------ | ----------------------------------------------------------------- |
| [`drf_api/`](drf_api/)               | Throttling a DRF view with `throttle_classes` + settings.         |
| [`multi_backend/`](multi_backend/)   | A `RATELIMIT_BACKENDS` failover configuration.                    |
| [`shadow_rollout/`](shadow_rollout/) | Rolling out a new limit with `shadow=True` and reading the logs.  |

## Prerequisites

Install the package with the extras each example needs:

```bash
# DRF example
pip install "django-smart-ratelimit[drf]"

# Multi-backend failover (Redis primary)
pip install "django-smart-ratelimit[redis]"
```

The `shadow_rollout` example uses only the core package — no extras required.

## How to Use

1. Pick the directory that matches what you want to do.
2. Copy the relevant `settings.py` snippet into your project's settings.
3. Copy the `views.py` / `urls.py` snippet into your app.

See the full guides under [`docs/`](../docs/) for details:
[DRF](../docs/drf.md), [Backends](../docs/backends.md),
[Configuration](../docs/configuration.md),
[Decorator](../docs/decorator.md), and
[Observability](../docs/observability.md).
