"""Tests for the Redis Cluster backend (issue #68).

Unit tests use a mocked ``RedisCluster`` and always run. Integration tests run
against a real cluster when one is reachable (127.0.0.1:7100 by default, or
REDIS_CLUSTER_HOST/PORT) and skip cleanly otherwise. A 6-node cluster can be
started for local testing with::

    docker run -d -p 7100-7105:7100-7105 -e IP=127.0.0.1 -e INITIAL_PORT=7100 \
        grokzen/redis-cluster:7.0.10
"""

import os
import time
from unittest import mock

import pytest

from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from django_smart_ratelimit import rate_limit
from django_smart_ratelimit.backends.factory import BackendFactory
from django_smart_ratelimit.backends.redis_backend import RedisClusterBackend
from django_smart_ratelimit.config import reset_settings

CLUSTER_HOST = os.environ.get("REDIS_CLUSTER_HOST", "127.0.0.1")
CLUSTER_PORT = int(os.environ.get("REDIS_CLUSTER_PORT", "7100"))


def _cluster_available():
    try:
        from redis.cluster import RedisCluster

        rc = RedisCluster(
            host=CLUSTER_HOST, port=CLUSTER_PORT, socket_connect_timeout=1
        )
        return bool(rc.ping())
    except Exception:
        return False


CLUSTER_UP = _cluster_available()
skip_without_cluster = pytest.mark.skipif(
    not CLUSTER_UP, reason="live Redis Cluster unavailable"
)


# ---------------------------------------------------------------------------
# Unit (mocked RedisCluster) -- always run, including in CI
# ---------------------------------------------------------------------------


def test_get_or_create_pool_is_none_for_cluster():
    # The cluster client owns its per-node pools; no shared pool is built.
    assert RedisClusterBackend._get_or_create_pool("redis://x") is None


def test_to_cluster_node_forms():
    from redis.cluster import ClusterNode

    n1 = RedisClusterBackend._to_cluster_node({"host": "h", "port": 7000})
    n2 = RedisClusterBackend._to_cluster_node("h2:7001")
    assert isinstance(n1, ClusterNode) and (n1.host, n1.port) == ("h", 7000)
    assert isinstance(n2, ClusterNode) and (n2.host, n2.port) == ("h2", 7001)


def _mock_cluster():
    """A RedisCluster stand-in whose ping() passes the init health check."""
    client = mock.MagicMock()
    client.ping.return_value = True
    return client


@override_settings(RATELIMIT_REDIS={"host": "10.0.0.1", "port": 7000})
def test_init_client_builds_rediscluster_from_seed():
    reset_settings()
    with mock.patch("redis.cluster.RedisCluster") as RC:
        RC.return_value = _mock_cluster()
        backend = RedisClusterBackend()
        # Built from a seed host/port; db is dropped (cluster has no DBs).
        _, kwargs = RC.call_args
        assert kwargs.get("host") == "10.0.0.1" and kwargs.get("port") == 7000
        assert "db" not in kwargs
        assert backend._pool is None
    reset_settings()


@override_settings(
    RATELIMIT_REDIS={
        "startup_nodes": [{"host": "10.0.0.1", "port": 7000}, "10.0.0.2:7000"]
    }
)
def test_init_client_builds_from_startup_nodes():
    reset_settings()
    with mock.patch("redis.cluster.RedisCluster") as RC:
        RC.return_value = _mock_cluster()
        RedisClusterBackend()
        _, kwargs = RC.call_args
        nodes = kwargs.get("startup_nodes")
        assert nodes is not None and len(nodes) == 2
    reset_settings()


@override_settings(RATELIMIT_REDIS={"url": "redis://10.0.0.1:7000/0"})
def test_init_client_builds_from_url():
    reset_settings()
    with mock.patch("redis.cluster.RedisCluster") as RC:
        RC.from_url.return_value = _mock_cluster()
        RedisClusterBackend()
        RC.from_url.assert_called_once()
    reset_settings()


def test_init_client_is_an_overridable_seam():
    # Demonstrates the extension point (the point of PR #92): a subclass can
    # supply any client by overriding only init_client.
    sentinel = _mock_cluster()

    class CustomClusterBackend(RedisClusterBackend):
        def init_client(self) -> None:
            self.redis = sentinel

    with override_settings(RATELIMIT_REDIS={"host": "x", "port": 1}):
        reset_settings()
        backend = CustomClusterBackend()
        assert backend.redis is sentinel
        reset_settings()


# ---------------------------------------------------------------------------
# Integration (real cluster) -- skipped when no cluster is reachable
# ---------------------------------------------------------------------------


@pytest.fixture
def cluster_backend():
    with override_settings(
        RATELIMIT_REDIS={"host": CLUSTER_HOST, "port": CLUSTER_PORT}
    ):
        reset_settings()
        yield RedisClusterBackend
        reset_settings()


@skip_without_cluster
def test_cluster_incr_count_reset(cluster_backend):
    backend = cluster_backend(algorithm="fixed_window")
    key = "cluster:it:%d" % time.time_ns()
    assert [backend.incr(key, 60) for _ in range(4)] == [1, 2, 3, 4]
    assert backend.get_count(key, 60) == 4
    backend.reset(key)
    assert backend.get_count(key, 60) == 0


@skip_without_cluster
def test_cluster_token_bucket(cluster_backend):
    backend = cluster_backend()
    key = "cluster:tb:%d" % time.time_ns()
    flags = [backend.token_bucket_check(key, 2, 0.0001, 2, 1)[0] for _ in range(4)]
    assert flags == [True, True, False, False]


@skip_without_cluster
def test_cluster_factory_and_decorator():
    with override_settings(
        RATELIMIT_BACKEND="redis_cluster",
        RATELIMIT_REDIS={"host": CLUSTER_HOST, "port": CLUSTER_PORT},
    ):
        reset_settings()
        from django_smart_ratelimit.backends import clear_backend_cache

        clear_backend_cache()
        backend = BackendFactory.create_backend("redis_cluster")
        assert backend.name == "redis_cluster"
        # Clean slate across the cluster so leftover fixed-window counts from a
        # prior run in the same minute don't skew the assertion.
        backend.redis.flushall()

        @rate_limit(
            key="ip", rate="3/m", algorithm="fixed_window", backend="redis_cluster"
        )
        def view(_request):
            return HttpResponse("ok")

        def call(ip):
            req = RequestFactory().get("/")
            req.META["REMOTE_ADDR"] = ip
            return view(req).status_code

        ip = "203.0.113.%d" % (time.time_ns() % 200)
        codes = [call(ip) for _ in range(5)]
        assert codes.count(200) == 3 and codes[-1] == 429
        clear_backend_cache()
        reset_settings()
