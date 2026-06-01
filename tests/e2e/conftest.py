"""Shared harness for real-backend end-to-end tests.

These tests exercise the public API against REAL storage (a live Redis, a live
MongoDB, and the real Django test database) — no backend mocking. Each backend
is skipped gracefully when its service is unavailable, so the suite is runnable
anywhere while running in full in CI (where Redis/Mongo service containers and
the test DB are present).

Helpers:
    - ``real_backend`` fixture: parametrizes a test over every AVAILABLE
      non-database backend (memory, redis, async_redis, mongodb), applying the
      backend setting, clearing the cache, and flushing the real store before
      and after each test. Yields the backend's short name.
    - ``use_backend(name)``: a context manager for explicit/per-scenario backend
      selection (use this for the database backend together with
      ``@pytest.mark.django_db``).
    - ``make_request(...)`` / ``AuthedUser`` / ``AnonUser``: build realistic
      Django requests.
    - ``exhaust(view, n, ...)``: drive a view/callable n times and collect codes.
"""

import os
from contextlib import contextmanager
from urllib.parse import urlparse

import pytest

from django.test import RequestFactory, override_settings

from django_smart_ratelimit.backends import clear_backend_cache, get_backend

MEMORY = "django_smart_ratelimit.backends.memory.MemoryBackend"
REDIS = "django_smart_ratelimit.backends.redis_backend.RedisBackend"
ASYNC_REDIS = "django_smart_ratelimit.backends.redis_backend.AsyncRedisBackend"
MONGODB = "django_smart_ratelimit.backends.mongodb.MongoDBBackend"
DATABASE = "django_smart_ratelimit.backends.database.DatabaseBackend"


def _host_port(env_var, default_host, default_port):
    """Derive (host, port) from a service URL env var, falling back to defaults.

    CI exports REDIS_URL / MONGODB_URL; honoring them lets the e2e suite target a
    non-localhost service instead of silently skipping it. Parsing failures fall
    back to the localhost defaults so a malformed URL never breaks collection.
    """
    raw = os.environ.get(env_var)
    if not raw:
        return default_host, default_port
    try:
        parsed = urlparse(raw)
        return (parsed.hostname or default_host, parsed.port or default_port)
    except Exception:
        return default_host, default_port


REDIS_HOST, REDIS_PORT = _host_port("REDIS_URL", "localhost", 6379)
MONGO_HOST, MONGO_PORT = _host_port("MONGODB_URL", "localhost", 27017)


def redis_available():
    try:
        import redis as _redis

        _redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0).ping()
        return True
    except Exception:
        return False


def mongo_available():
    try:
        from pymongo import MongoClient

        MongoClient(
            host=MONGO_HOST, port=MONGO_PORT, serverSelectionTimeoutMS=800
        ).admin.command("ping")
        return True
    except Exception:
        return False


REDIS_UP = redis_available()
MONGO_UP = mongo_available()

# CI safety valve: a green run that silently skipped every Redis/Mongo scenario
# looks identical to a run that exercised them. Set RATELIMIT_E2E_REQUIRE_SERVICES=1
# (in CI, where the service containers must be present) to turn those skips into a
# hard collection error instead. Default unset -> skip gracefully, as before.
if os.environ.get("RATELIMIT_E2E_REQUIRE_SERVICES", "").lower() in ("1", "true", "yes"):
    _missing = [n for n, up in (("Redis", REDIS_UP), ("MongoDB", MONGO_UP)) if not up]
    if _missing:
        raise RuntimeError(
            "RATELIMIT_E2E_REQUIRE_SERVICES is set but these services are "
            f"unavailable: {', '.join(_missing)}. The e2e suite would otherwise "
            "silently skip their scenarios."
        )

# Mark factories so tests/files can build their own parametrizations.
skip_without_redis = pytest.mark.skipif(not REDIS_UP, reason="live Redis unavailable")
skip_without_mongo = pytest.mark.skipif(not MONGO_UP, reason="live MongoDB unavailable")


@pytest.fixture(autouse=True)
def _clear_backend_cache_between_tests():
    """Safety net: drop any cached backend after every e2e test.

    Tests that go through ``use_backend`` / the ``*_real_backend`` fixtures
    already clear the cache, but this guards a future test that grabs
    ``get_backend()`` directly from leaking a stale cached instance into the next
    test on the shared live stores.
    """
    yield
    clear_backend_cache()


def flush_store(name):
    """Wipe the real store for a backend so each test starts clean."""
    try:
        if name in ("redis", "async_redis"):
            import redis as _redis

            _redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0).flushdb()
        elif name == "mongodb":
            from pymongo import MongoClient

            MongoClient(host=MONGO_HOST, port=MONGO_PORT).drop_database("ratelimit")
        elif name == "memory":
            backend = get_backend()
            if hasattr(backend, "clear_all"):
                backend.clear_all()
    except Exception:
        pass


# (short name, dotted path, settings overrides) wrapped as pytest params.
_REDIS_CFG = {"RATELIMIT_REDIS": {"host": REDIS_HOST, "port": REDIS_PORT, "db": 0}}
_MONGO_CFG = {
    "RATELIMIT_MONGODB": {
        "host": MONGO_HOST,
        "port": MONGO_PORT,
        "database": "ratelimit",
    }
}

_P_MEMORY = pytest.param(("memory", MEMORY, {}), id="memory")
_P_REDIS = pytest.param(
    ("redis", REDIS, _REDIS_CFG), id="redis", marks=skip_without_redis
)
_P_ASYNC_REDIS = pytest.param(
    ("async_redis", ASYNC_REDIS, _REDIS_CFG), id="async_redis", marks=skip_without_redis
)
_P_MONGO = pytest.param(
    ("mongodb", MONGODB, _MONGO_CFG), id="mongodb", marks=skip_without_mongo
)

# Backends usable through the SYNCHRONOUS API. AsyncRedisBackend is async-only
# (its sync incr/get_count raise NotImplementedError, directing callers to the
# a* methods), so it is excluded here and covered by ``async_real_backend``.
_SYNC_BACKENDS = [_P_MEMORY, _P_REDIS, _P_MONGO]
# All backends including the async-only redis backend, for async-path tests.
_ASYNC_BACKENDS = [_P_MEMORY, _P_REDIS, _P_ASYNC_REDIS, _P_MONGO]
# Backends with a NATIVE token/leaky-bucket implementation. MongoDB has none
# (it raises NotImplementedError and the decorator falls back to window
# counting), so bucket-semantics assertions must not run against it.
_NATIVE_BUCKET_BACKENDS = [_P_MEMORY, _P_REDIS]


@contextmanager
def use_backend(name):
    """Select a backend by short name for the duration of the block.

    Applies RATELIMIT_BACKEND (+ store config) via override_settings, clears the
    backend cache, flushes the real store on entry and exit.
    """
    paths = {
        "memory": (MEMORY, {}),
        "redis": (
            REDIS,
            {"RATELIMIT_REDIS": {"host": REDIS_HOST, "port": REDIS_PORT, "db": 0}},
        ),
        "async_redis": (
            ASYNC_REDIS,
            {"RATELIMIT_REDIS": {"host": REDIS_HOST, "port": REDIS_PORT, "db": 0}},
        ),
        "mongodb": (
            MONGODB,
            {
                "RATELIMIT_MONGODB": {
                    "host": MONGO_HOST,
                    "port": MONGO_PORT,
                    "database": "ratelimit",
                }
            },
        ),
        "database": (DATABASE, {}),
    }
    path, extra = paths[name]
    ov = override_settings(RATELIMIT_BACKEND=path, **extra)
    ov.enable()
    clear_backend_cache()
    flush_store(name)
    try:
        yield name
    finally:
        clear_backend_cache()
        flush_store(name)
        ov.disable()


@pytest.fixture(params=_SYNC_BACKENDS)
def real_backend(request):
    """Parametrize over every available sync-capable backend (memory/redis/mongodb)."""
    name, path, extra = request.param
    with use_backend(name):
        yield name


@pytest.fixture(params=_ASYNC_BACKENDS)
def async_real_backend(request):
    """Parametrize over backends for async-path tests (adds async_redis)."""
    name, path, extra = request.param
    with use_backend(name):
        yield name


@pytest.fixture(params=_NATIVE_BUCKET_BACKENDS)
def native_bucket_backend(request):
    """Parametrize over backends with native token/leaky-bucket support."""
    name, path, extra = request.param
    with use_backend(name):
        yield name


class AnonUser:
    is_authenticated = False
    is_staff = False
    is_superuser = False
    id = None


class AuthedUser:
    is_authenticated = True
    is_staff = False
    is_superuser = False

    def __init__(self, uid=1):
        self.id = uid
        self.pk = uid


def make_request(
    ip="203.0.113.10", method="get", user=None, headers=None, params=None, path="/"
):
    """Build a realistic Django request with a client IP and (optional) user."""
    rf = RequestFactory()
    query = (
        "?" + "&".join(f"{k}={v}" for k, v in (params or {}).items()) if params else ""
    )
    req = getattr(rf, method.lower())(path + query)
    req.META["REMOTE_ADDR"] = ip
    for hk, hv in (headers or {}).items():
        req.META["HTTP_" + hk.upper().replace("-", "_")] = hv
    req.user = user if user is not None else AnonUser()
    return req


def exhaust(callable_view, n, ip="203.0.113.10", **kwargs):
    """Call a view n times (each a fresh request from the same IP); return codes."""
    codes = []
    for _ in range(n):
        resp = callable_view(make_request(ip=ip, **kwargs))
        codes.append(getattr(resp, "status_code", resp))
    return codes


def pytest_collection_modifyitems(config, items):
    """Auto-mark everything under tests/e2e/ with the ``e2e`` marker."""
    for item in items:
        if "/tests/e2e/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)
