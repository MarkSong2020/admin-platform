"""监控日志查询 DTO（P2 §6 / Phase 4）—— audit_events（操作日志）+ login_logs（登录日志）。

只读视图：list 用 summary 列（不含完整 envelope payload，避免响应膨胀）；detail 额外带 ``payload``
（完整 envelope，无损取证）+ request 段。分页 envelope 对齐 ADR 0001 §7.5（RolePage 同款）。

C5/C6 分层：schemas 不 import models / sqlalchemy（纯 Pydantic DTO，from_attributes 读 ORM 属性）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class _UtcDatetimeModel(BaseModel):
    """把 MySQL DATETIME 读回的 naive datetime 统一解释为 UTC。"""

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def _normalize_datetime(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return value


class AuditEventRead(_UtcDatetimeModel):
    """审计/操作日志列表项（summary，不含完整 payload）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str
    event_type: str
    action: str
    title: str
    occurred_at: datetime
    actor_user_id: int | None
    actor_username: str | None
    actor_is_super_admin: bool
    target_type: str | None
    target_id: str | None
    target_display: str | None
    ip: str | None
    method: str | None
    path: str | None
    result_status: str
    result_http_status: int | None
    result_error_code: str | None
    duration_ms: int | None
    risk_level: str
    redaction_applied: bool
    created_at: datetime


class AuditEventDetail(AuditEventRead):
    """审计事件详情：summary + 完整 envelope payload + request 关联段。"""

    request_id: str | None
    trace_id: str | None
    user_agent: str | None
    payload: dict[str, Any]


class AuditEventPage(BaseModel):
    """审计日志分页 envelope（ADR 0001 §7.5）。"""

    items: list[AuditEventRead]
    page: int
    size: int
    total: int
    total_pages: int


class LoginLogRead(_UtcDatetimeModel):
    """登录日志项（RuoYi sys_logininfor 对标）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    user_id: int | None
    status: str
    reason_code: str | None
    ip: str | None
    user_agent: str | None
    request_id: str | None
    login_at_utc: datetime
    created_at: datetime


class LoginLogPage(BaseModel):
    """登录日志分页 envelope。"""

    items: list[LoginLogRead]
    page: int
    size: int
    total: int
    total_pages: int


# ---- P4 服务监控（psutil 采集，对标 RuoYi 服务监控）------------------------------


class ServerCpu(BaseModel):
    """CPU 指标。"""

    cores: int | None  # 逻辑核心数
    percent: float  # 总体使用率 %
    per_cpu: list[float]  # 各核使用率 %
    load_avg: list[float] | None  # 1/5/15 分钟平均负载（仅类 Unix）


class ServerMemory(BaseModel):
    """物理内存指标（字节）。"""

    total: int
    available: int
    used: int
    percent: float


class ServerSwap(BaseModel):
    """交换分区指标（字节）。"""

    total: int
    used: int
    free: int
    percent: float


class ServerDisk(BaseModel):
    """单个磁盘分区用量（字节）。"""

    device: str
    mountpoint: str
    fstype: str
    total: int
    used: int
    free: int
    percent: float


class ServerSys(_UtcDatetimeModel):
    """主机基本信息。"""

    hostname: str
    os_name: str
    os_release: str
    arch: str
    python_version: str
    boot_time: datetime


class ServerProcess(_UtcDatetimeModel):
    """当前应用进程指标。"""

    pid: int
    cpu_percent: float
    memory_percent: float
    memory_rss: int  # 常驻内存（字节）
    num_threads: int
    create_time: datetime


class ServerMetrics(_UtcDatetimeModel):
    """服务监控聚合响应。"""

    cpu: ServerCpu
    memory: ServerMemory
    swap: ServerSwap
    disks: list[ServerDisk]
    sys: ServerSys
    process: ServerProcess
    collected_at: datetime


# ---- P4 缓存监控（Redis INFO，对标 RuoYi 缓存监控）--------------------------------


class CacheCommandStat(BaseModel):
    """单条 Redis 命令统计（``commandstats``）。"""

    name: str
    calls: int
    usec: int
    usec_per_call: float


class CacheRedisInfo(BaseModel):
    """Redis ``INFO`` 关键字段摘要。字段缺失（不同 Redis 版本）时为 None。"""

    version: str | None
    mode: str | None
    uptime_seconds: int | None
    connected_clients: int | None
    used_memory: int | None
    used_memory_human: str | None
    maxmemory: int | None
    mem_fragmentation_ratio: float | None
    keyspace_hits: int | None
    keyspace_misses: int | None
    hit_rate: float | None  # 命中率 = hits / (hits + misses)，无样本则 0.0
    total_commands_processed: int | None


class CacheMetrics(_UtcDatetimeModel):
    """缓存监控聚合响应。Redis 未配置 / 不可达时 ``available=False``（不抛 500）。"""

    available: bool
    db_size: int | None  # 当前 db 的 key 数量
    info: CacheRedisInfo | None
    command_stats: list[CacheCommandStat]
    collected_at: datetime


# ---- P4 在线用户（活动 refresh token family 派生，对标 RuoYi 在线用户）-------------


class OnlineSession(_UtcDatetimeModel):
    """一个在线会话 = 一个活动 refresh token family（一次登录）。

    设备信息（IP/UA）按 P1.4 决策不落 refresh token，故此处不含——会话级 IP/UA 需查登录日志。
    """

    session_id: str  # family_id（UUID 字符串），强制下线按此撤销
    user_id: int
    username: str
    login_time: datetime  # family 首签时间（登录时刻）
    last_active_time: datetime  # 最近一次轮换/签发时间
    expires_at: datetime  # 会话绝对过期上限


class OnlineSessionPage(BaseModel):
    """在线会话分页 envelope。"""

    items: list[OnlineSession]
    page: int
    size: int
    total: int
    total_pages: int
