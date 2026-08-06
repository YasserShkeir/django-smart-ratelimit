"""Numeric contract for the token-bucket rate-limit response headers.

``add_token_bucket_headers`` emits two time-valued headers that answer
*different* questions, and both have been wrong at some point:

* ``X-RateLimit-Reset`` is period-aligned. It must stay put across successive
  requests -- that stability is exactly what issue #14 ("Time window changing
  after each request") asked for, and it must not be re-derived from the
  bucket's refill state.
* ``Retry-After`` is the real wait before the *rejected* request would be
  served. Deriving it from the period grid meant a true 6 second wait was
  advertised as anywhere from 5 to 120 seconds depending on where the wall
  clock happened to sit, and it was skipped entirely whenever tokens remained
  but not enough of them (the multi-token-cost path).

These tests pin the exact numbers rather than ``> 0``, so that a regression in
either computation fails loudly.
"""

import time
from typing import Any, Dict
from unittest.mock import patch

import pytest

from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.algorithms.token_bucket import TokenBucketAlgorithm
from django_smart_ratelimit.backends import clear_backend_cache
from django_smart_ratelimit.backends.memory import MemoryBackend
from django_smart_ratelimit.utils import add_token_bucket_headers

MEMORY_BACKEND = "django_smart_ratelimit.backends.memory.MemoryBackend"

# The full set of headers a token-bucket response is expected to carry.
BUCKET_HEADERS = (
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
    "X-RateLimit-Bucket-Size",
    "X-RateLimit-Bucket-Remaining",
    "X-RateLimit-Refill-Rate",
)

# A clock position deliberately *not* aligned to a 60s boundary, and far enough
# from the next boundary that the "advance if within 5s" rule does not kick in.
FIXED_NOW = 1_700_000_000.0
PERIOD = 60
# 1_700_000_000 // 60 * 60 == 1_699_999_980, so the aligned reset is:
EXPECTED_RESET = 1_700_000_040


def _bucket_metadata(
    bucket_size: int, refill_rate: float, initial_tokens: int, cost: int
) -> Dict[str, Any]:
    """Drive the real algorithm and return the metadata a backend would emit.

    Using the production code path (rather than a hand-written dict) keeps the
    expected ``Retry-After`` values honest: they are derived from the same
    ``tokens_needed / refill_rate`` arithmetic the backends perform.
    """
    algorithm = TokenBucketAlgorithm(
        {
            "bucket_size": bucket_size,
            "refill_rate": refill_rate,
            "initial_tokens": initial_tokens,
        }
    )
    key = (
        f"tb-headers-{bucket_size}-{refill_rate}-{initial_tokens}-{cost}-{time.time()}"
    )
    _allowed, metadata = algorithm.is_allowed(
        MemoryBackend(), key, bucket_size, PERIOD, tokens_requested=cost
    )
    return metadata


def _blocked_response() -> HttpResponse:
    """Return a 429 response with an empty header set."""
    return HttpResponse("blocked", status=429)


# ---------------------------------------------------------------------------
# Retry-After tracks the real refill wait
# ---------------------------------------------------------------------------


def test_retry_after_equals_refill_wait_for_empty_bucket():
    """An empty bucket advertises the arithmetic refill wait, not the period.

    bucket refills at 0.5 tokens/s and the request costs 3 tokens, so the wait
    is 3 / 0.5 = 6 seconds. The 60 second period must not leak into this value.
    """
    metadata = _bucket_metadata(
        bucket_size=5, refill_rate=0.5, initial_tokens=0, cost=3
    )
    assert metadata["tokens_remaining"] == pytest.approx(0.0, abs=0.05)
    assert metadata["time_to_refill"] == pytest.approx(6.0, abs=0.05)

    response = _blocked_response()
    add_token_bucket_headers(response, metadata, limit=5, period=PERIOD)

    assert response.headers["Retry-After"] == "6"


def test_retry_after_rounds_up_to_the_next_whole_second():
    """A fractional wait rounds up: waiting 2s for a 2.5s refill just 429s."""
    response = _blocked_response()
    add_token_bucket_headers(
        response,
        {
            "tokens_remaining": 0,
            "bucket_size": 5,
            "refill_rate": 0.4,
            "time_to_refill": 2.5,
        },
        limit=5,
        period=PERIOD,
    )
    assert response.headers["Retry-After"] == "3"


def test_retry_after_present_and_correct_on_multi_token_cost_path():
    """Tokens remaining but not enough of them still gets a Retry-After.

    3 tokens are in the bucket and the request costs 5, so 2 more tokens are
    needed at 0.5 tokens/s: a 4 second wait. This path used to emit no
    ``Retry-After`` at all because the header was gated on
    ``tokens_remaining <= 0``.
    """
    metadata = _bucket_metadata(
        bucket_size=10, refill_rate=0.5, initial_tokens=3, cost=5
    )
    assert metadata["tokens_remaining"] == pytest.approx(3.0, abs=0.05)
    assert metadata["time_to_refill"] == pytest.approx(4.0, abs=0.05)

    response = _blocked_response()
    add_token_bucket_headers(response, metadata, limit=10, period=PERIOD)

    # Tokens really do remain -- this is the case the old guard skipped.
    assert response.headers["X-RateLimit-Bucket-Remaining"] == "3"
    assert response.headers["Retry-After"] == "4"


def test_retry_after_does_not_depend_on_clock_position():
    """The same 6 second wait is advertised wherever the wall clock sits.

    The period-derived implementation returned anything from 5 to 120 for this
    exact input depending on the moment the request arrived.
    """
    metadata = {
        "tokens_remaining": 0,
        "bucket_size": 5,
        "refill_rate": 0.5,
        "time_to_refill": 6.0,
    }
    for offset in (0, 1, 7, 29, 55, 58, 59.5, 61, 119):
        response = _blocked_response()
        with patch(
            "django_smart_ratelimit.utils.time.time",
            return_value=FIXED_NOW + offset,
        ):
            add_token_bucket_headers(response, metadata, limit=5, period=PERIOD)
        assert response.headers["Retry-After"] == "6", f"offset={offset}"


def test_no_retry_after_on_allowed_response():
    """A served request is not told to back off."""
    response = HttpResponse("ok")
    add_token_bucket_headers(
        response,
        {
            "tokens_remaining": 4,
            "bucket_size": 5,
            "refill_rate": 0.5,
            "time_to_refill": 2.0,
        },
        limit=5,
        period=PERIOD,
    )
    assert "Retry-After" not in response.headers


# ---------------------------------------------------------------------------
# X-RateLimit-Reset stays period-aligned and stable (issue #14)
# ---------------------------------------------------------------------------


def test_reset_is_period_aligned():
    """The reset time lands on a period boundary, not on ``now + wait``."""
    response = HttpResponse("ok")
    with patch("django_smart_ratelimit.utils.time.time", return_value=FIXED_NOW):
        add_token_bucket_headers(
            response,
            {
                "tokens_remaining": 2,
                "bucket_size": 5,
                "refill_rate": 0.5,
                "time_to_refill": 6.0,
            },
            limit=5,
            period=PERIOD,
        )
    reset = int(response.headers["X-RateLimit-Reset"])
    assert reset == EXPECTED_RESET
    assert reset % PERIOD == 0


def test_reset_is_stable_across_successive_requests():
    """Successive requests inside one period report the *same* reset time.

    This is the guarantee issue #14 asked for. The bucket drains and the refill
    estimate changes on every call; the reset time must not move with it.
    """
    seen = set()
    for offset, tokens_left, refill_wait in (
        (0.0, 5, 0.0),
        (3.0, 4, 2.0),
        (11.5, 3, 4.0),
        (24.0, 2, 6.0),
        (30.0, 0, 10.0),
    ):
        response = HttpResponse("ok")
        with patch(
            "django_smart_ratelimit.utils.time.time",
            return_value=FIXED_NOW + offset,
        ):
            add_token_bucket_headers(
                response,
                {
                    "tokens_remaining": tokens_left,
                    "bucket_size": 5,
                    "refill_rate": 0.5,
                    "time_to_refill": refill_wait,
                },
                limit=5,
                period=PERIOD,
            )
        seen.add(response.headers["X-RateLimit-Reset"])

    assert seen == {str(EXPECTED_RESET)}


def test_reset_advances_to_next_period_near_the_boundary():
    """Within 5s of the boundary the reset advances rather than expiring."""
    response = HttpResponse("ok")
    # 1_700_000_038 is 2s before the 1_700_000_040 boundary.
    with patch("django_smart_ratelimit.utils.time.time", return_value=FIXED_NOW + 38):
        add_token_bucket_headers(
            response,
            {"tokens_remaining": 1, "bucket_size": 5, "refill_rate": 0.5},
            limit=5,
            period=PERIOD,
        )
    assert int(response.headers["X-RateLimit-Reset"]) == EXPECTED_RESET + PERIOD


# ---------------------------------------------------------------------------
# refill_rate == 0: fall back to the period, never to a bare 1
# ---------------------------------------------------------------------------


def test_refill_rate_zero_reported_as_inf_falls_back_to_period():
    """``backends.utils`` spells "never refills" as ``inf``."""
    metadata = _bucket_metadata(bucket_size=5, refill_rate=0, initial_tokens=0, cost=1)
    assert metadata["time_to_refill"] == float("inf")

    response = _blocked_response()
    add_token_bucket_headers(response, metadata, limit=5, period=PERIOD)

    assert response.headers["Retry-After"] == str(PERIOD)


def test_refill_rate_zero_reported_as_zero_falls_back_to_period():
    """``algorithms.token_bucket`` spells the same case as ``0``.

    That producer guards its division, so there is no ZeroDivisionError -- the
    value simply arrives as 0 and used to be emitted as a meaningless
    ``Retry-After: 1``.
    """
    response = _blocked_response()
    add_token_bucket_headers(
        response,
        {
            "tokens_remaining": 0,
            "bucket_size": 5,
            "refill_rate": 0,
            "time_to_refill": 0,
        },
        limit=5,
        period=PERIOD,
    )
    assert response.headers["Retry-After"] == str(PERIOD)


def test_missing_time_to_refill_falls_back_to_period():
    """A backend that omits the field entirely still gets a usable wait."""
    response = _blocked_response()
    add_token_bucket_headers(
        response,
        {"tokens_remaining": 0, "bucket_size": 5, "refill_rate": 1.0},
        limit=5,
        period=PERIOD,
    )
    assert response.headers["Retry-After"] == str(PERIOD)


def test_nan_time_to_refill_falls_back_to_period():
    """A not-a-number wait is not a wait either."""
    response = _blocked_response()
    add_token_bucket_headers(
        response,
        {
            "tokens_remaining": 0,
            "bucket_size": 5,
            "refill_rate": 1.0,
            "time_to_refill": float("nan"),
        },
        limit=5,
        period=PERIOD,
    )
    assert response.headers["Retry-After"] == str(PERIOD)


# ---------------------------------------------------------------------------
# Malformed optional metadata degrades gracefully
# ---------------------------------------------------------------------------


def test_bucket_size_none_does_not_raise_and_keeps_every_header():
    """``bucket_size=None`` must not raise.

    ``dict.get("bucket_size", limit)`` returns the *present* ``None``, so the
    default never applies. Raising here is not a cosmetic problem: the sync
    decorator wraps the view call and the header call in one ``try``, so the
    fallback path re-runs the view body a second time, and the async decorator
    has no ``try`` at all and surfaces a TypeError after the view already ran.
    """
    response = HttpResponse("ok")
    add_token_bucket_headers(
        response,
        {"tokens_remaining": 2, "bucket_size": None, "refill_rate": 1.0},
        limit=10,
        period=PERIOD,
    )
    for header in BUCKET_HEADERS:
        assert header in response.headers, header
    assert response.headers["X-RateLimit-Bucket-Size"] == "10"


def test_bucket_size_missing_falls_back_to_limit():
    """An absent bucket_size falls back to the configured limit."""
    response = HttpResponse("ok")
    add_token_bucket_headers(
        response,
        {"tokens_remaining": 2, "refill_rate": 1.0},
        limit=10,
        period=PERIOD,
    )
    for header in BUCKET_HEADERS:
        assert header in response.headers, header
    assert response.headers["X-RateLimit-Bucket-Size"] == "10"


def test_bucket_size_garbage_falls_back_without_losing_headers():
    """A non-numeric bucket_size degrades only itself."""
    response = HttpResponse("ok")
    add_token_bucket_headers(
        response,
        {"tokens_remaining": 2, "bucket_size": "not-a-number", "refill_rate": 1.0},
        limit=10,
        period=PERIOD,
    )
    for header in BUCKET_HEADERS:
        assert header in response.headers, header
    assert response.headers["X-RateLimit-Bucket-Size"] == "10"


def test_float_bucket_size_is_not_truncated():
    """A fractional bucket_size keeps its fraction.

    ``format_token_bucket_metadata`` types ``bucket_size`` as
    ``Optional[float]`` and the Redis fail-open path passes a float, so
    ``int()``-coercing the value would silently under-report capacity.
    """
    response = HttpResponse("ok")
    add_token_bucket_headers(
        response,
        {"tokens_remaining": 2, "bucket_size": 10.5, "refill_rate": 1.0},
        limit=10,
        period=PERIOD,
    )
    assert response.headers["X-RateLimit-Bucket-Size"] == "10.5"


def test_whole_float_bucket_size_renders_without_decimal_point():
    """``20.0`` is still advertised as ``20``, not ``20.0``."""
    response = HttpResponse("ok")
    add_token_bucket_headers(
        response,
        {"tokens_remaining": 2, "bucket_size": 20.0, "refill_rate": 1.0},
        limit=20,
        period=PERIOD,
    )
    assert response.headers["X-RateLimit-Bucket-Size"] == "20"


def test_none_tokens_remaining_does_not_raise():
    """``tokens_remaining=None`` degrades to 0 instead of raising."""
    response = HttpResponse("ok")
    add_token_bucket_headers(
        response,
        {"tokens_remaining": None, "bucket_size": 5, "refill_rate": 1.0},
        limit=5,
        period=PERIOD,
    )
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert response.headers["X-RateLimit-Bucket-Remaining"] == "0"


def test_garbage_refill_rate_drops_only_the_refill_rate_header():
    """A bad refill_rate costs us that one header and nothing else."""
    response = HttpResponse("ok")
    add_token_bucket_headers(
        response,
        {"tokens_remaining": 2, "bucket_size": 5, "refill_rate": None},
        limit=5,
        period=PERIOD,
    )
    for header in BUCKET_HEADERS:
        if header == "X-RateLimit-Refill-Rate":
            continue
        assert header in response.headers, header
    assert "X-RateLimit-Refill-Rate" not in response.headers


def test_empty_metadata_still_emits_the_computable_headers():
    """Nothing at all from the backend must not blow up the response."""
    response = _blocked_response()
    add_token_bucket_headers(response, {}, limit=7, period=PERIOD)
    assert response.headers["X-RateLimit-Limit"] == "7"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert response.headers["X-RateLimit-Bucket-Size"] == "7"
    assert response.headers["X-RateLimit-Bucket-Remaining"] == "0"
    assert int(response.headers["X-RateLimit-Reset"]) % PERIOD == 0
    assert response.headers["Retry-After"] == str(PERIOD)


# ---------------------------------------------------------------------------
# The concrete damage a raising header helper does through the decorator
# ---------------------------------------------------------------------------


def _null_bucket_size_check(*_args, **_kwargs):
    """Stand in for a backend that reports ``bucket_size`` as ``None``."""
    return True, {"tokens_remaining": 4, "bucket_size": None, "refill_rate": 1.0}


@override_settings(RATELIMIT_BACKEND=MEMORY_BACKEND)
def test_sync_view_body_runs_once_when_bucket_size_is_none():
    """A raising header helper made the *sync* decorator run the view twice.

    ``_handle_token_bucket_rate_limiting`` wraps the ``func()`` call and the
    ``add_token_bucket_headers`` call in a single ``try``; its ``except`` falls
    back to ``_handle_standard_rate_limiting``, which calls ``func()`` again.
    Any exception from header formatting therefore double-executes the view --
    duplicated writes, duplicated emails, duplicated charges.
    """
    clear_backend_cache()
    calls = []

    @rate_limit(key="ip", rate="10/m", algorithm="token_bucket", block=True)
    def view(_request):
        calls.append(1)
        return HttpResponse("ok")

    request = RequestFactory().get("/")
    request.META["REMOTE_ADDR"] = "203.0.113.7"

    with patch.object(TokenBucketAlgorithm, "is_allowed", _null_bucket_size_check):
        response = view(request)

    assert len(calls) == 1
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Bucket-Size"] == "10"


@override_settings(RATELIMIT_BACKEND=MEMORY_BACKEND)
async def test_async_view_does_not_raise_when_bucket_size_is_none():
    """The *async* decorator has no ``try`` around the header call.

    A raising header helper there surfaces a TypeError to the caller after the
    view body has already run, turning a served request into a 500.
    """
    clear_backend_cache()
    calls = []

    @rate_limit(key="ip", rate="10/m", algorithm="token_bucket", block=True)
    async def view(_request):
        calls.append(1)
        return HttpResponse("ok")

    request = RequestFactory().get("/")
    request.META["REMOTE_ADDR"] = "203.0.113.8"

    with patch(
        "django_smart_ratelimit.decorator._run_bucket_check",
        return_value=(
            True,
            {"tokens_remaining": 4, "bucket_size": None, "refill_rate": 1.0},
            4,
        ),
    ):
        response = await view(request)

    assert len(calls) == 1
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Bucket-Size"] == "10"
