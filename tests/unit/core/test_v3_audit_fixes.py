"""Regression tests for v3.0.0 audit fixes.

Covers the correctness fixes applied during the v3.0.0 review:
- the out-of-the-box default backend path resolves (was unimportable),
- ``generate_key`` resolves ``user_or_ip`` and the ``param:`` alias,
- the ``Algorithm`` enum / validation accept ``leaky_bucket``,
- the ``leaky_bucket`` algorithm is honored by the decorator.
"""

import pytest

from django.test import RequestFactory, override_settings

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends import clear_backend_cache, get_backend
from django_smart_ratelimit.backends.factory import BackendFactory
from django_smart_ratelimit.config import RateLimitSettings, reset_settings
from django_smart_ratelimit.enums import Algorithm
from django_smart_ratelimit.key_functions import generate_key


class TestDefaultBackendOutOfBox:
    """The default backend must resolve when RATELIMIT_BACKEND is unset."""

    def test_dataclass_and_settings_defaults_agree(self):
        # The dataclass default and the from_django_settings fallback must use
        # the same (importable) dotted path.
        assert (
            RateLimitSettings().backend_class
            == "django_smart_ratelimit.backends.memory.MemoryBackend"
        )

    def test_default_path_is_importable(self):
        cls = BackendFactory.get_backend_class(
            "django_smart_ratelimit.backends.memory.MemoryBackend"
        )
        assert cls.__name__ == "MemoryBackend"

    def test_get_backend_without_setting(self, settings):
        # Simulate a project that never set RATELIMIT_BACKEND.
        if hasattr(settings, "RATELIMIT_BACKEND"):
            del settings.RATELIMIT_BACKEND
        reset_settings()
        clear_backend_cache()
        try:
            backend = get_backend()
            assert type(backend).__name__ == "MemoryBackend"
        finally:
            reset_settings()
            clear_backend_cache()


class TestGenerateKeyResolution:
    """``user_or_ip`` and ``param:`` must resolve, not collapse to a global key."""

    def setup_method(self):
        self.factory = RequestFactory()

    def test_user_or_ip_anonymous_uses_ip(self):
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "203.0.113.7"
        # Anonymous request: no user attribute -> falls back to IP.
        key = generate_key("user_or_ip", request)
        assert key != "user_or_ip"  # not the literal global bucket
        assert "203.0.113.7" in key

    def test_param_alias_matches_get(self):
        request = self.factory.get("/?tenant=acme")
        get_key = generate_key("get:tenant", request)
        param_key = generate_key("param:tenant", request)
        assert "acme" in get_key
        assert "acme" in param_key

    def test_unknown_static_key_returned_as_is(self):
        request = self.factory.get("/")
        assert generate_key("my_global_limit", request) == "my_global_limit"


class TestLeakyBucketAlgorithmWiring:
    """leaky_bucket must be a recognized algorithm end to end."""

    def test_enum_has_leaky_bucket(self):
        assert Algorithm.LEAKY_BUCKET == "leaky_bucket"
        assert "leaky_bucket" in {a.value for a in Algorithm}

    def test_validate_rate_config_accepts_leaky_bucket(self):
        from django_smart_ratelimit.utils import validate_rate_config

        # Should not raise.
        validate_rate_config("10/m", algorithm="leaky_bucket")

    @override_settings(
        RATELIMIT_BACKEND="django_smart_ratelimit.backends.memory.MemoryBackend"
    )
    def test_decorator_accepts_leaky_bucket_and_still_enforces(self):
        # On a backend without native leaky-bucket support (memory) the
        # decorator warns and falls back to standard window limiting rather
        # than crashing or silently mis-counting. The limit is still enforced.
        clear_backend_cache()
        try:

            @rate_limit(key="ip", rate="2/m", algorithm="leaky_bucket", block=True)
            def view(request):
                from django.http import HttpResponse

                return HttpResponse("ok")

            factory = RequestFactory()

            def make():
                req = factory.get("/")
                req.META["REMOTE_ADDR"] = "198.51.100.42"
                return view(req)

            assert make().status_code == 200
            assert make().status_code == 200
            assert make().status_code == 429
        finally:
            clear_backend_cache()


@pytest.mark.django_db
def test_leaky_bucket_decorator_smoke_with_db_backend():
    """leaky_bucket via the decorator works against the atomic DB backend."""
    with override_settings(
        RATELIMIT_BACKEND="django_smart_ratelimit.backends.database.DatabaseBackend"
    ):
        clear_backend_cache()
        try:

            @rate_limit(key="ip", rate="2/m", algorithm="leaky_bucket", block=True)
            def view(request):
                from django.http import HttpResponse

                return HttpResponse("ok")

            factory = RequestFactory()
            req = factory.get("/")
            req.META["REMOTE_ADDR"] = "198.51.100.99"
            # First request should be allowed without error.
            assert view(req).status_code == 200
        finally:
            clear_backend_cache()
