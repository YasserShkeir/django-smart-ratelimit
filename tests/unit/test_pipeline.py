"""
Unit tests for django_smart_ratelimit.pipeline module.

Covers the v3 shared evaluation pipeline: resolve_effective_rate,
apply_policy_lists, and handle_shadow_decision.
"""

import logging
import unittest
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from django_smart_ratelimit.exceptions import KeyGenerationError
from django_smart_ratelimit.pipeline import (
    POLICY_ALLOW,
    POLICY_CONTINUE,
    POLICY_DENY,
    ResolvedLimit,
    apply_policy_lists,
    handle_shadow_decision,
    resolve_effective_rate,
)


class ResolveEffectiveRateTests(SimpleTestCase):
    """Coverage for resolve_effective_rate — the pipeline entry point."""

    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")

    def test_string_key_and_rate_resolves_cleanly(self):
        """Simple path: literal key + literal rate should produce a ResolvedLimit."""
        resolved = resolve_effective_rate(
            key="user:42",
            rate="10/m",
            request=self.request,
        )
        self.assertIsInstance(resolved, ResolvedLimit)
        self.assertEqual(resolved.key, "user:42")
        self.assertEqual(resolved.limit, 10)
        self.assertEqual(resolved.period, 60)
        self.assertEqual(resolved.cost, 1)
        self.assertEqual(resolved.rate_string, "10/m")

    def test_callable_rate_receives_request(self):
        """A callable rate should be invoked and its return parsed."""
        calls = []

        def dynamic_rate(request):
            calls.append(request)
            return "50/h"

        resolved = resolve_effective_rate(
            key="k",
            rate=dynamic_rate,
            request=self.request,
        )
        self.assertEqual(resolved.limit, 50)
        self.assertEqual(resolved.period, 3600)
        self.assertEqual(len(calls), 1)

    def test_callable_rate_django_ratelimit_compat(self):
        """Callables with (self, request) signature should work too."""

        def compat_rate(_self, request):  # django-ratelimit style
            return "7/s"

        resolved = resolve_effective_rate(
            key="k", rate=compat_rate, request=self.request
        )
        self.assertEqual(resolved.limit, 7)
        self.assertEqual(resolved.period, 1)

    def test_callable_rate_zero_args(self):
        """Callables with no args should also be accepted."""
        resolved = resolve_effective_rate(
            key="k", rate=lambda: "3/m", request=self.request
        )
        self.assertEqual(resolved.limit, 3)

    def test_invalid_rate_type_raises(self):
        """Non-str non-callable rates should raise TypeError."""
        with self.assertRaises(TypeError):
            resolve_effective_rate(
                key="k", rate=12345, request=self.request  # type: ignore[arg-type]
            )

    def test_empty_key_raises_key_generation_error(self):
        """Empty keys are a footgun — must raise instead of silently collapsing."""

        def bad_key(_request):
            return ""

        with self.assertRaises(KeyGenerationError):
            resolve_effective_rate(
                key=bad_key,
                rate="10/m",
                request=self.request,
            )

    def test_none_key_raises_key_generation_error(self):
        """None keys should also raise."""

        def bad_key(_request):
            return None

        with self.assertRaises(KeyGenerationError):
            resolve_effective_rate(
                key=bad_key,
                rate="10/m",
                request=self.request,
            )

    def test_empty_key_passes_when_validate_disabled(self):
        """validate_key=False preserves the old silent behavior for edge callers."""
        resolved = resolve_effective_rate(
            key=lambda _r: "",
            rate="10/m",
            request=self.request,
            validate_key=False,
        )
        self.assertEqual(resolved.key, "")

    def test_cost_int_is_applied(self):
        resolved = resolve_effective_rate(
            key="k", rate="10/m", request=self.request, cost=3
        )
        self.assertEqual(resolved.cost, 3)

    def test_cost_callable_is_applied(self):
        resolved = resolve_effective_rate(
            key="k",
            rate="10/m",
            request=self.request,
            cost=lambda _r: 5,
        )
        self.assertEqual(resolved.cost, 5)

    def test_cost_is_clamped_to_minimum_one(self):
        """cost=0 would let callers bypass limits; must clamp to 1."""
        resolved = resolve_effective_rate(
            key="k", rate="10/m", request=self.request, cost=0
        )
        self.assertEqual(resolved.cost, 1)

        resolved = resolve_effective_rate(
            key="k", rate="10/m", request=self.request, cost=-5
        )
        self.assertEqual(resolved.cost, 1)

    def test_cost_callable_exception_falls_back_to_one(self):
        """A misbehaving cost callable should not break the limiter."""

        def raises(_r):
            raise RuntimeError("boom")

        resolved = resolve_effective_rate(
            key="k", rate="10/m", request=self.request, cost=raises
        )
        self.assertEqual(resolved.cost, 1)

    def test_cost_callable_non_int_falls_back_to_one(self):
        resolved = resolve_effective_rate(
            key="k", rate="10/m", request=self.request, cost=lambda _r: "not-int"
        )
        self.assertEqual(resolved.cost, 1)

    def test_adaptive_limiter_string_applied(self):
        """String adaptive names are resolved via registry."""
        fake = MagicMock()
        fake.get_effective_limit.return_value = 42
        # get_adaptive_limiter is imported lazily inside pipeline; patch at
        # its source module.
        with patch(
            "django_smart_ratelimit.adaptive.get_adaptive_limiter",
            return_value=fake,
        ):
            resolved = resolve_effective_rate(
                key="k",
                rate="100/m",
                request=self.request,
                adaptive="my_limiter",
            )
        self.assertEqual(resolved.limit, 42)

    def test_adaptive_missing_registry_entry_uses_base(self):
        with patch(
            "django_smart_ratelimit.adaptive.get_adaptive_limiter",
            return_value=None,
        ):
            resolved = resolve_effective_rate(
                key="k",
                rate="100/m",
                request=self.request,
                adaptive="missing",
            )
        self.assertEqual(resolved.limit, 100)


class ApplyPolicyListsTests(SimpleTestCase):
    """Coverage for apply_policy_lists — the allow/deny pre-check."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_neither_list_returns_continue(self):
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(apply_policy_lists(request), POLICY_CONTINUE)

    def test_allow_list_hit_returns_allow(self):
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.5")
        result = apply_policy_lists(request, allow_list=["10.0.0.0/8"])
        self.assertEqual(result, POLICY_ALLOW)

    def test_deny_list_hit_returns_deny(self):
        request = self.factory.get("/", REMOTE_ADDR="1.2.3.4")
        result = apply_policy_lists(request, deny_list=["1.2.3.0/24"])
        self.assertEqual(result, POLICY_DENY)

    def test_deny_wins_over_allow(self):
        """Deny is the explicit block — always wins over allow-list membership."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.5")
        result = apply_policy_lists(
            request,
            allow_list=["10.0.0.0/8"],
            deny_list=["10.0.0.5"],
        )
        self.assertEqual(result, POLICY_DENY)

    def test_no_list_hit_returns_continue(self):
        request = self.factory.get("/", REMOTE_ADDR="192.168.1.1")
        result = apply_policy_lists(
            request,
            allow_list=["10.0.0.0/8"],
            deny_list=["1.2.3.0/24"],
        )
        self.assertEqual(result, POLICY_CONTINUE)

    def test_malformed_allow_list_is_skipped(self):
        """A bad allow-list shouldn't take down rate limiting."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.5")
        # An invalid CIDR inside parse_ip_list will raise; we expect the
        # function to log and continue.
        result = apply_policy_lists(request, allow_list=["not-a-cidr!!!"])
        self.assertEqual(result, POLICY_CONTINUE)


class HandleShadowDecisionTests(SimpleTestCase):
    """Coverage for handle_shadow_decision."""

    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/some/path")

    def _call(self, **overrides):
        defaults = dict(
            allowed=False,
            shadow=False,
            request=self.request,
            key="test:key",
            limit=10,
            remaining=0,
            algorithm="sliding_window",
            backend="MemoryBackend",
        )
        defaults.update(overrides)
        return handle_shadow_decision(**defaults)

    def test_allowed_passes_through(self):
        decision = self._call(allowed=True)
        self.assertTrue(decision.allow)
        self.assertFalse(decision.shadowed)

    def test_block_without_shadow(self):
        decision = self._call(allowed=False, shadow=False)
        self.assertFalse(decision.allow)
        self.assertFalse(decision.shadowed)

    def test_block_with_shadow_becomes_allow(self):
        """shadow=True converts a block into an allow with logging."""
        with self.assertLogs(
            "django_smart_ratelimit.pipeline", level=logging.INFO
        ) as log:
            decision = self._call(allowed=False, shadow=True)
        self.assertTrue(decision.allow)
        self.assertTrue(decision.shadowed)
        self.assertTrue(
            any("SHADOW_RATE_LIMIT_BLOCK" in m for m in log.output),
            f"Expected shadow log line; got {log.output!r}",
        )

    def test_observability_always_called(self):
        """record_check must be invoked on every call (allowed or blocked)."""
        with patch("django_smart_ratelimit.pipeline.record_check") as rec:
            self._call(allowed=True)
            self._call(allowed=False, shadow=False)
            self._call(allowed=False, shadow=True)
        self.assertEqual(rec.call_count, 3)

    def test_observability_failure_is_swallowed(self):
        """record_check blowing up must never break the limiter."""
        with patch(
            "django_smart_ratelimit.pipeline.record_check",
            side_effect=RuntimeError("telemetry down"),
        ):
            # Should not raise.
            decision = self._call(allowed=False, shadow=False)
        self.assertFalse(decision.allow)


if __name__ == "__main__":
    unittest.main()
