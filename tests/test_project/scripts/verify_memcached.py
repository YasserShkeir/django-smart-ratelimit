#!/usr/bin/env python
"""Manual verification for the Memcached backend.

Run it against a real Memcached to sanity-check the backend by hand, e.g.::

    # start one: docker run -d -p 11211:11211 memcached:alpine
    python tests/test_project/scripts/verify_memcached.py --host 127.0.0.1 --port 11211

Exits non-zero if any check fails. This is a manual tool (excluded from the
pytest run via ``norecursedirs``); the automated coverage lives in
``tests/unit/backends/test_memcached_backend.py`` and
``tests/e2e/test_memcached_e2e.py``.
"""

import argparse
import sys
import time


def _configure_django(host, port):
    import django
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            DEBUG=True,
            DATABASES={},
            INSTALLED_APPS=["django_smart_ratelimit"],
            RATELIMIT_BACKEND="memcached",
            RATELIMIT_ALGORITHM="fixed_window",
            RATELIMIT_KEY_PREFIX="manual:memcached:",
            RATELIMIT_MEMCACHED={"HOST": host, "PORT": port},
            DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        )
    django.setup()


class _Checker:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, name, condition, detail=""):
        if condition:
            print(f"  [PASS] {name}")
            self.passed += 1
        else:
            print(f"  [FAIL] {name} {detail}")
            self.failed += 1


def main():
    parser = argparse.ArgumentParser(description="Manual Memcached backend check")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11211)
    args = parser.parse_args()

    _configure_django(args.host, args.port)

    from django.http import HttpResponse

    from django_smart_ratelimit import rate_limit
    from django_smart_ratelimit.backends.memcached import MemcachedBackend

    try:
        from django.test import RequestFactory
    except Exception:  # pragma: no cover
        RequestFactory = None

    c = _Checker()
    backend = MemcachedBackend(algorithm="fixed_window")
    suffix = str(time.time_ns())

    print(f"Memcached backend @ {args.host}:{args.port}")

    # 1. Health
    health = backend.health_check()
    c.check("health_check reports healthy", health.get("healthy") is True, str(health))

    # 2. Counter increments
    k = f"counter:{suffix}"
    seq = [backend.incr(k, 60) for _ in range(5)]
    c.check("incr counts 1..5 within window", seq == [1, 2, 3, 4, 5], str(seq))
    c.check("get_count reflects the counter", backend.get_count(k, 60) == 5)

    # 3. Reset
    backend.reset(k)
    c.check("reset clears the counter", backend.get_count(k, 60) == 0)

    # 4. Key isolation
    k1, k2 = f"iso1:{suffix}", f"iso2:{suffix}"
    backend.incr(k1, 60)
    backend.incr(k1, 60)
    backend.incr(k2, 60)
    c.check(
        "distinct keys are isolated",
        backend.get_count(k1, 60) == 2 and backend.get_count(k2, 60) == 1,
    )

    # 5. Window rollover
    wk = f"win:{suffix}"
    backend.incr(wk, 1)
    backend.incr(wk, 1)
    before = backend.get_count(wk, 1)
    time.sleep(1.2)
    after = backend.incr(wk, 1)
    c.check(
        "window rolls over (count resets)",
        before == 2 and after == 1,
        f"before={before} after={after}",
    )

    # 6. Decorator burst-then-block
    if RequestFactory is not None:

        @rate_limit(key="ip", rate="5/m", algorithm="fixed_window")
        def view(_request):
            return HttpResponse("ok")

        def call(ip):
            req = RequestFactory().get("/")
            req.META["REMOTE_ADDR"] = ip
            return view(req).status_code

        ip = f"203.0.113.{int(suffix) % 200}"
        codes = [call(ip) for _ in range(7)]
        c.check(
            "decorator allows 5 then blocks",
            codes == [200] * 5 + [429, 429],
            str(codes),
        )

    print(f"\n=== {c.passed} passed, {c.failed} failed ===")
    return 1 if c.failed else 0


if __name__ == "__main__":
    sys.exit(main())
