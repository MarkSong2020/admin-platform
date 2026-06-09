"""系统指标采集器（P4 服务/缓存监控）—— repository 层的「基础设施读」类比。

服务监控走 psutil（CPU / 内存 / 磁盘 / 进程），缓存监控走 Redis ``INFO``。
没有 DB 表，所以不走 SQLAlchemy repository；本类承担同等角色：raw 采集，
不含业务策略（超时 / 降级在 service 层）。

⚠️ psutil 调用是**阻塞 syscall**（ASYNC lint 禁在 async 函数里直接调），故 server 采集
整体放进 ``anyio.to_thread.run_sync`` 的同步函数里跑，不占事件循环。
"""

from __future__ import annotations

import platform
from datetime import UTC, datetime
from typing import Any

import anyio.to_thread
import psutil
from redis.asyncio import Redis

from admin_platform.domains.monitor.schemas import (
    CacheCommandStat,
    CacheMetrics,
    CacheRedisInfo,
    ServerCpu,
    ServerDisk,
    ServerMemory,
    ServerMetrics,
    ServerProcess,
    ServerSwap,
    ServerSys,
)


class SystemMetricsCollector:
    """无状态采集器：每次调用重新读 psutil / Redis，不缓存（监控要实时）。"""

    async def collect_server(self) -> ServerMetrics:
        """采集服务器指标。psutil 阻塞调用整体下沉到线程池，不阻塞事件循环。"""
        return await anyio.to_thread.run_sync(self._collect_server_sync)

    def _collect_server_sync(self) -> ServerMetrics:
        # CPU：interval=None 为非阻塞（返回距上次调用的瞬时使用率）。首次调用可能为 0.0。
        cpu = ServerCpu(
            cores=psutil.cpu_count(logical=True),
            percent=psutil.cpu_percent(interval=None),
            per_cpu=psutil.cpu_percent(interval=None, percpu=True),
            load_avg=self._load_avg(),
        )
        vm = psutil.virtual_memory()
        memory = ServerMemory(
            total=vm.total, available=vm.available, used=vm.used, percent=vm.percent
        )
        sm = psutil.swap_memory()
        swap = ServerSwap(total=sm.total, used=sm.used, free=sm.free, percent=sm.percent)
        proc = psutil.Process()
        with proc.oneshot():
            process = ServerProcess(
                pid=proc.pid,
                cpu_percent=proc.cpu_percent(interval=None),
                memory_percent=proc.memory_percent(),
                memory_rss=proc.memory_info().rss,
                num_threads=proc.num_threads(),
                create_time=datetime.fromtimestamp(proc.create_time(), tz=UTC),
            )
        sys_info = ServerSys(
            hostname=platform.node(),
            os_name=platform.system(),
            os_release=platform.release(),
            arch=platform.machine(),
            python_version=platform.python_version(),
            boot_time=datetime.fromtimestamp(psutil.boot_time(), tz=UTC),
        )
        return ServerMetrics(
            cpu=cpu,
            memory=memory,
            swap=swap,
            disks=self._collect_disks(),
            sys=sys_info,
            process=process,
            collected_at=datetime.now(UTC),
        )

    @staticmethod
    def _load_avg() -> list[float] | None:
        """1/5/15 分钟平均负载（仅类 Unix；Windows 无则 None）。"""
        try:
            return list(psutil.getloadavg())
        except AttributeError, OSError:
            return None

    @staticmethod
    def _collect_disks() -> list[ServerDisk]:
        """物理分区用量。单个分区读失败（权限 / 不可达挂载）跳过，不让整体 500。"""
        disks: list[ServerDisk] = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except PermissionError, OSError:
                continue
            disks.append(
                ServerDisk(
                    device=part.device,
                    mountpoint=part.mountpoint,
                    fstype=part.fstype,
                    total=usage.total,
                    used=usage.used,
                    free=usage.free,
                    percent=usage.percent,
                )
            )
        return disks

    async def collect_cache(self, redis: Redis) -> CacheMetrics:
        """采集 Redis 指标。调用方（service）负责超时与异常降级。"""
        info: dict[str, Any] = await redis.info()
        cmdstats: dict[str, Any] = await redis.info("commandstats")
        db_size: int = await redis.dbsize()

        hits = _as_int(info.get("keyspace_hits"))
        misses = _as_int(info.get("keyspace_misses"))
        hit_rate = _hit_rate(hits, misses)
        redis_info = CacheRedisInfo(
            version=_as_str(info.get("redis_version")),
            mode=_as_str(info.get("redis_mode")),
            uptime_seconds=_as_int(info.get("uptime_in_seconds")),
            connected_clients=_as_int(info.get("connected_clients")),
            used_memory=_as_int(info.get("used_memory")),
            used_memory_human=_as_str(info.get("used_memory_human")),
            maxmemory=_as_int(info.get("maxmemory")),
            mem_fragmentation_ratio=_as_float(info.get("mem_fragmentation_ratio")),
            keyspace_hits=hits,
            keyspace_misses=misses,
            hit_rate=hit_rate,
            total_commands_processed=_as_int(info.get("total_commands_processed")),
        )
        return CacheMetrics(
            available=True,
            db_size=db_size,
            info=redis_info,
            command_stats=_parse_command_stats(cmdstats),
            collected_at=datetime.now(UTC),
        )


def _parse_command_stats(raw: dict[str, Any]) -> list[CacheCommandStat]:
    """``info("commandstats")`` → ``{'cmdstat_get': {'calls': N, 'usec': N, ...}}`` 展开为列表。"""
    stats: list[CacheCommandStat] = []
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        name = key[len("cmdstat_") :] if key.startswith("cmdstat_") else key
        stats.append(
            CacheCommandStat(
                name=name,
                calls=_as_int(val.get("calls")) or 0,
                usec=_as_int(val.get("usec")) or 0,
                usec_per_call=_as_float(val.get("usec_per_call")) or 0.0,
            )
        )
    return stats


def _hit_rate(hits: int | None, misses: int | None) -> float | None:
    if hits is None or misses is None:
        return None
    total = hits + misses
    return round(hits / total, 4) if total else 0.0


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)
