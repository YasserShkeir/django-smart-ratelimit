#!/usr/bin/env python
"""Manual verification for the Redis Cluster backend (issue #68).

Run it against a real Redis Cluster, e.g.::

    # start a 6-node cluster for testing:
    docker run -d -p 7100-7105:7100-7105 -e IP=127.0.0.1 -e INITIAL_PORT=7100 \
        grokzen/redis-cluster:7.0.10
    python tests/test_project/scripts/verify_redis_cluster.py --host 127.0.0.1 --port 7100

Exits non-zero if any check fails. Manual tool (excluded from pytest via
``norecursedirs``); the automated coverage is in
``tests/integration/test_redis_cluster.py``.
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
            RATELIMIT_BACKEND="redis_cluster",
            RATELIMIT_ALGORITHM="sliding_window",
            RATELIMIT_KEY_PREFIX="manual:cluster:",
            RATELIMIT_REDIS={"host": host, "port": port},
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
    parser = argparse.ArgumentParser(description="Manual Redis Cluster backend check")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7100)
    args = parser.parse_args()

    _configure_django(args.host, args.port)

    from django.http import HttpResponse
    from django.test import RequestFactory

    from django_smart_ratelimit import rate_limit
    from django_smart_ratelimit.backends.redis_backend import RedisClusterBackend

    c = _Checker()
    suffix = str(time.time_ns())
    print(f"Redis Cluster backend @ {args.host}:{args.port}")

    backend = RedisClusterBackend(algorithm="fixed_window")
    c.check("client is RedisCluster", type(backend.redis).__name__ == "RedisCluster")
    c.check("health_check healthy", backend.health_check().get("status") == "healthy")

    # Counter
    k = f"counter:{suffix}"
    seq = [backend.incr(k, 60) for _ in range(5)]
    c.check("incr counts 1..5", seq == [1, 2, 3, 4, 5], str(seq))
    c.check("get_count == 5", backend.get_count(k, 60) == 5)
    backend.reset(k)
    c.check("reset clears counter", backend.get_count(k, 60) == 0)

    # Token bucket (single-key Lua across the cluster)
    tk = f"tb:{suffix}"
    flags = [backend.token_bucket_check(tk, 2, 0.0001, 2, 1)[0] for _ in range(4)]
    c.check(
        "token bucket size 2 -> T,T,F,F",
        flags == [True, True, False, False],
        str(flags),
    )

    # Decorator burst-then-block
    @rate_limit(key="ip", rate="5/m", algorithm="fixed_window")
    def view(_request):
        return HttpResponse("ok")

    def call(ip):
        req = RequestFactory().get("/")
        req.META["REMOTE_ADDR"] = ip
        return view(req).status_code

    ip = f"203.0.113.{int(suffix) % 200}"
    backend.redis.flushall()
    codes = [call(ip) for _ in range(7)]
    c.check(
        "decorator allows 5 then blocks", codes == [200] * 5 + [429, 429], str(codes)
    )

    print(f"\n=== {c.passed} passed, {c.failed} failed ===")
    return 1 if c.failed else 0


if __name__ == "__main__":
    sys.exit(main())
