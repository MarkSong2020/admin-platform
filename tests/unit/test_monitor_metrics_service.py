"""服务/缓存监控 service + collector 单测（P4，DB-free）。

测真实行为（反 mock 原则）：``collect_server`` 跑真 psutil（无需 DB / Redis）；``collect_cache``
的解析逻辑用「镜像 redis-py info() 返回结构」的 fake 喂；service 的降级策略用会抛错的
fake collector 驱动各 except 分支。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pytest_mock import MockerFixture
from redis.asyncio import Redis
from redis.exceptions import RedisError

from admin_platform.domains.monitor.collector import (
    SystemMetricsCollector,
    _as_float,
    _as_int,
    _as_str,
    _hit_rate,
    _parse_command_stats,
)
from admin_platform.domains.monitor.schemas import (
    CacheMetrics,
    ServerCpu,
    ServerMemory,
    ServerMetrics,
    ServerProcess,
    ServerSwap,
    ServerSys,
)
from admin_platform.domains.monitor.service import SystemMonitorService

pytestmark = pytest.mark.anyio


# ---- collector：真实 psutil 服务采集 -----------------------------------------


async def test_collect_server_returns_real_metrics() -> None:
    metrics = await SystemMetricsCollector().collect_server()
    assert metrics.memory.total > 0
    assert metrics.memory.percent >= 0
    assert metrics.process.pid > 0
    assert isinstance(metrics.disks, list)
    assert metrics.sys.python_version
    # per_cpu 长度应与逻辑核心数一致（cores 为 None 时跳过断言）。
    if metrics.cpu.cores is not None:
        assert len(metrics.cpu.per_cpu) == metrics.cpu.cores


# ---- collector：缓存解析（fake redis，镜像 redis-py info() 解析后结构）-----------


class _FakeRedis:
    """镜像 redis-py ``info()`` 行为：返回已解析的 dict（str 键、数值已转 int/float）。"""

    def __init__(self, info_map: dict[str, Any], cmdstats: dict[str, Any], dbsize: int) -> None:
        self._info = info_map
        self._cmd = cmdstats
        self._db = dbsize

    async def info(self, section: str | None = None) -> dict[str, Any]:
        return self._cmd if section == "commandstats" else self._info

    async def dbsize(self) -> int:
        return self._db


async def test_collect_cache_parses_info_and_hit_rate() -> None:
    fake = _FakeRedis(
        info_map={
            "redis_version": "7.4.0",
            "redis_mode": "standalone",
            "uptime_in_seconds": 3600,
            "connected_clients": 5,
            "used_memory": 1048576,
            "used_memory_human": "1.00M",
            "maxmemory": 0,
            "mem_fragmentation_ratio": 1.23,
            "keyspace_hits": 30,
            "keyspace_misses": 10,
            "total_commands_processed": 999,
        },
        cmdstats={"cmdstat_get": {"calls": 100, "usec": 200, "usec_per_call": 2.0}},
        dbsize=42,
    )
    metrics = await SystemMetricsCollector().collect_cache(cast(Redis, fake))
    assert metrics.available is True
    assert metrics.db_size == 42
    assert metrics.info is not None
    assert metrics.info.version == "7.4.0"
    assert metrics.info.hit_rate == 0.75  # 30 / (30 + 10)
    assert metrics.command_stats[0].name == "get"
    assert metrics.command_stats[0].calls == 100


async def test_collect_cache_handles_bytes_values() -> None:
    """decode_responses=False 偶发 bytes 值时不应崩（_as_str 兜底解码）。"""
    fake = _FakeRedis(
        info_map={"redis_version": b"7.4.0", "used_memory_human": b"2.00M"},
        cmdstats={},
        dbsize=0,
    )
    metrics = await SystemMetricsCollector().collect_cache(cast(Redis, fake))
    assert metrics.info is not None
    assert metrics.info.version == "7.4.0"
    assert metrics.info.used_memory_human == "2.00M"


# ---- collector：纯函数 ------------------------------------------------------


def test_hit_rate_edges() -> None:
    assert _hit_rate(0, 0) == 0.0  # 无样本
    assert _hit_rate(3, 1) == 0.75
    assert _hit_rate(None, 5) is None  # 字段缺失


def test_coercion_helpers() -> None:
    assert _as_int("12") == 12
    assert _as_int(None) is None
    assert _as_int("nan") is None
    assert _as_float("1.5") == 1.5
    assert _as_float("x") is None
    assert _as_str(b"abc") == "abc"
    assert _as_str(None) is None


def test_parse_command_stats_skips_non_dict() -> None:
    raw: dict[str, Any] = {
        "cmdstat_set": {"calls": 5, "usec": 10, "usec_per_call": 2.0},
        "garbage": "not-a-dict",
    }
    stats = _parse_command_stats(raw)
    assert len(stats) == 1
    assert stats[0].name == "set"


# ---- service：缓存降级策略 --------------------------------------------------


def _canned_cache() -> CacheMetrics:
    return CacheMetrics(
        available=True, db_size=1, info=None, command_stats=[], collected_at=datetime.now(UTC)
    )


class _OkCollector(SystemMetricsCollector):
    async def collect_cache(self, redis: Redis) -> CacheMetrics:
        return _canned_cache()


class _RaisingCollector(SystemMetricsCollector):
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def collect_cache(self, redis: Redis) -> CacheMetrics:
        raise self._exc


async def test_cache_unavailable_when_redis_none() -> None:
    svc = SystemMonitorService(SystemMetricsCollector(), redis=None)
    metrics = await svc.get_cache_metrics()
    assert metrics.available is False
    assert metrics.info is None
    assert metrics.command_stats == []


@pytest.mark.parametrize(
    "exc",
    [TimeoutError(), RedisError("boom"), OSError("conn refused")],
)
async def test_cache_degrades_on_collector_error(exc: Exception) -> None:
    svc = SystemMonitorService(_RaisingCollector(exc), redis=cast(Redis, object()))
    metrics = await svc.get_cache_metrics()
    assert metrics.available is False


async def test_cache_passthrough_when_ok() -> None:
    svc = SystemMonitorService(_OkCollector(), redis=cast(Redis, object()))
    metrics = await svc.get_cache_metrics()
    assert metrics.available is True
    assert metrics.db_size == 1


async def test_cache_real_wait_for_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """真正走 asyncio.wait_for 计时超时（非 collector 同步抛 TimeoutError）→ 降级。

    把超时阈值 monkeypatch 成极小值，collector sleep 超过它，验证 wait_for 真的兜住慢 Redis。
    """
    monkeypatch.setattr("admin_platform.domains.monitor.service._CACHE_TIMEOUT_S", 0.01)

    class _SlowCollector(SystemMetricsCollector):
        async def collect_cache(self, redis: Redis) -> CacheMetrics:
            await asyncio.sleep(1)
            return _canned_cache()

    svc = SystemMonitorService(_SlowCollector(), redis=cast(Redis, object()))
    metrics = await svc.get_cache_metrics()
    assert metrics.available is False


# ---- service：服务监控编排（get_server_metrics 透传）---------------------------


def _canned_server() -> ServerMetrics:
    now = datetime.now(UTC)
    return ServerMetrics(
        cpu=ServerCpu(cores=2, percent=1.0, per_cpu=[1.0, 1.0], load_avg=None),
        memory=ServerMemory(total=8, available=4, used=4, percent=50.0),
        swap=ServerSwap(total=0, used=0, free=0, percent=0.0),
        disks=[],
        sys=ServerSys(
            hostname="h",
            os_name="Linux",
            os_release="6",
            arch="x86_64",
            python_version="3.14.0",
            boot_time=now,
        ),
        process=ServerProcess(
            pid=1, cpu_percent=0.0, memory_percent=0.0, memory_rss=1, num_threads=1, create_time=now
        ),
        collected_at=now,
    )


class _ServerCollector(SystemMetricsCollector):
    def __init__(self, metrics: ServerMetrics) -> None:
        self._metrics = metrics

    async def collect_server(self) -> ServerMetrics:
        return self._metrics


async def test_get_server_metrics_passthrough() -> None:
    """service 把 collector.collect_server() 原样透传（唯一编排逻辑）。"""
    canned = _canned_server()
    svc = SystemMonitorService(_ServerCollector(canned), redis=None)
    assert await svc.get_server_metrics() is canned


# ---- collector：psutil 降级分支（防 500，须显式 mock 触发）----------------------


def test_load_avg_returns_none_when_unavailable(mocker: MockerFixture) -> None:
    """getloadavg 抛 OSError（无该 syscall 的平台）→ _load_avg 返回 None，不冒泡。"""
    mocker.patch(
        "admin_platform.domains.monitor.collector.psutil.getloadavg",
        side_effect=OSError("not available"),
    )
    assert SystemMetricsCollector._load_avg() is None


def test_collect_disks_skips_unreadable_partition(mocker: MockerFixture) -> None:
    """disk_usage 对某分区抛 PermissionError → 跳过该分区（不整体 500）。"""
    mocker.patch(
        "admin_platform.domains.monitor.collector.psutil.disk_partitions",
        return_value=[SimpleNamespace(device="/dev/x", mountpoint="/secret", fstype="ext4")],
    )
    mocker.patch(
        "admin_platform.domains.monitor.collector.psutil.disk_usage",
        side_effect=PermissionError("denied"),
    )
    assert SystemMetricsCollector._collect_disks() == []
