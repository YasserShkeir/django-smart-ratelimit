"""
End-to-end integration tests for v3 decorator features.

Covers the interactions between the decorator, the pipeline, and the memory
backend — the paths a real application would exercise.
"""

import logging
import unittest

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import clear_backend_cache, get_backend
from django_smart_ratelimit.exceptions import KeyGenerationError


def _fresh_backend():
    """Clear backend singleton + its stored state between tests.

    The backend module caches a single MemoryBackend instance; tests that
    exercise the decorator must both drop the cached instance (so fresh
    config is picked up) AND reset any leftover counters on the previous
    instance.
    """
    try:
        backend = get_backend()
        if hasattr(backend, "clear_all"):
            backend.clear_all()
    except Exception:
        pass
    clear_backend_cache()


# All v3 integration tests run against the in-process MemoryBackend. The repo's
# default test settings point at Redis, which isn't available in CI; forcing
# memory here keeps these tests hermetic.
_MEMORY_BACKEND_SETTINGS = dict(
    RATELIMIT_BACKEND="memory",
    RATELIMIT_MIDDLEWARE={
        "DEFAULT_RATE": "100/m",
        "BACKEND": "memory",
        "BLOCK": True,
        "SKIP_PATHS": ["/admin/", "/health/"],
    },
)


@override_settings(**_MEMORY_BACKEND_SETTINGS)
class ShadowModeTests(SimpleTestCase):
    """A decorator with shadow=True should log but never block."""

    def setUp(self):
        _fresh_backend()
        self.factory = RequestFactory()

    def tearDown(self):
        _fresh_backend()

    def test_shadow_mode_does_not_block(self):
        @rate_limit(key="ip", rate="2/m", shadow=True)
        def view(request):
            return HttpResponse("ok")

        # Exceed the limit many times over — shadow=True means every call
        # should succeed.
        responses = []
        with self.assertLogs(
            "django_smart_ratelimit.pipeline", level=logging.INFO
        ) as log:
            for _ in range(10):
                resp = view(self.factory.get("/", REMOTE_ADDR="10.0.0.1"))
                responses.append(resp.status_code)

        self.assertEqual(responses, [200] * 10, "shadow mode must never return 429")
        # At least one shadow block event must have been logged.
        self.assertTrue(
            any("SHADOW_RATE_LIMIT_BLOCK" in m for m in log.output),
            "shadow mode should emit a SHADOW_RATE_LIMIT_BLOCK log line",
        )

    def test_shadow_mode_off_still_blocks(self):
        @rate_limit(key="ip", rate="2/m", shadow=False)
        def view(request):
            return HttpResponse("ok")

        statuses = [
            view(self.factory.get("/", REMOTE_ADDR="10.0.0.2")).status_code
            for _ in range(5)
        ]
        # First 2 should pass, the rest should be blocked.
        self.assertEqual(statuses.count(200), 2)
        self.assertEqual(statuses.count(429), 3)


@override_settings(**_MEMORY_BACKEND_SETTINGS)
class CostBasedLimitingTests(SimpleTestCase):
    """cost > 1 should consume proportionally more of the limit."""

    def setUp(self):
        _fresh_backend()
        self.factory = RequestFactory()

    def tearDown(self):
        _fresh_backend()

    def test_integer_cost_consumes_budget(self):
        @rate_limit(key="ip", rate="6/m", cost=2)
        def view(request):
            return HttpResponse("ok")

        # Each call consumes 2 of 6 → 3 calls succeed, 4th blocks.
        statuses = [
            view(self.factory.get("/", REMOTE_ADDR="10.0.0.3")).status_code
            for _ in range(4)
        ]
        self.assertEqual(statuses[:3], [200, 200, 200])
        self.assertEqual(statuses[3], 429)

    def test_callable_cost_gets_request(self):
        """Callable cost should receive the request and be used per-call."""
        seen = []

        def dynamic_cost(request):
            seen.append(request.path)
            # POST requests are more expensive.
            return 3 if request.method == "POST" else 1

        @rate_limit(key="ip", rate="5/m", cost=dynamic_cost)
        def view(request):
            return HttpResponse("ok")

        get_resp = view(self.factory.get("/a", REMOTE_ADDR="10.0.0.4"))
        post_resp = view(self.factory.post("/b", REMOTE_ADDR="10.0.0.4"))
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(post_resp.status_code, 200)
        # Next GET should fit (1 + 3 + 1 = 5 ≤ 5).
        third = view(self.factory.get("/c", REMOTE_ADDR="10.0.0.4"))
        self.assertEqual(third.status_code, 200)
        # Next request exceeds budget.
        fourth = view(self.factory.get("/d", REMOTE_ADDR="10.0.0.4"))
        self.assertEqual(fourth.status_code, 429)
        # Callable was invoked each time.
        self.assertEqual(len(seen), 4)


@override_settings(**_MEMORY_BACKEND_SETTINGS)
class AllowDenyListTests(SimpleTestCase):
    """Decorator-level CIDR lists — deny returns 429, allow bypasses limit."""

    def setUp(self):
        _fresh_backend()
        self.factory = RequestFactory()

    def tearDown(self):
        _fresh_backend()

    def test_deny_list_blocks_with_429(self):
        @rate_limit(key="ip", rate="1000/m", deny_list=["1.2.3.0/24"])
        def view(request):
            return HttpResponse("ok")

        resp = view(self.factory.get("/", REMOTE_ADDR="1.2.3.50"))
        self.assertEqual(resp.status_code, 429)

    def test_deny_list_honors_shadow_mode(self):
        """Shadow mode must also suppress explicit deny-list blocks."""

        @rate_limit(
            key="ip",
            rate="1000/m",
            deny_list=["1.2.3.0/24"],
            shadow=True,
        )
        def view(request):
            return HttpResponse("ok")

        resp = view(self.factory.get("/", REMOTE_ADDR="1.2.3.50"))
        self.assertEqual(resp.status_code, 200)

    def test_allow_list_bypasses_limit(self):
        """Allow-list hits skip counting entirely."""

        @rate_limit(
            key="ip",
            rate="1/m",
            allow_list=["10.0.0.0/8"],
        )
        def view(request):
            return HttpResponse("ok")

        # 10 requests from an allow-listed IP should all succeed.
        for _ in range(10):
            resp = view(self.factory.get("/", REMOTE_ADDR="10.1.1.1"))
            self.assertEqual(resp.status_code, 200)

    def test_deny_wins_over_allow(self):
        @rate_limit(
            key="ip",
            rate="1000/m",
            allow_list=["10.0.0.0/8"],
            deny_list=["10.0.0.99"],
        )
        def view(request):
            return HttpResponse("ok")

        # Allow-listed range, but explicit deny — deny wins.
        resp = view(self.factory.get("/", REMOTE_ADDR="10.0.0.99"))
        self.assertEqual(resp.status_code, 429)


@override_settings(**_MEMORY_BACKEND_SETTINGS)
class KeyValidationTests(SimpleTestCase):
    """Empty keys should blow up loudly — they're a rate-limit-bypass bug."""

    def setUp(self):
        _fresh_backend()
        self.factory = RequestFactory()

    def tearDown(self):
        _fresh_backend()

    def test_empty_string_key_raises(self):
        @rate_limit(key=lambda _req, *a, **kw: "", rate="10/m")
        def view(request):
            return HttpResponse("ok")

        with self.assertRaises(KeyGenerationError):
            view(self.factory.get("/"))

    def test_none_key_raises(self):
        @rate_limit(key=lambda _req, *a, **kw: None, rate="10/m")
        def view(request):
            return HttpResponse("ok")

        with self.assertRaises(KeyGenerationError):
            view(self.factory.get("/"))


if __name__ == "__main__":
    unittest.main()
