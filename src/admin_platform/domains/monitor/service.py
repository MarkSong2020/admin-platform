"""监控日志查询 service（P2 Phase 4）—— 薄编排：repository → 分页 DTO，detail 缺则 404。

分层：service 不 import fastapi、不抛 HTTPException —— 用 ``AppError``（全局 handler 翻 ProblemDetail）。
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from admin_platform.core.errors import AppError
from admin_platform.domains.monitor.collector import SystemMetricsCollector
from admin_platform.domains.monitor.repository import MonitorRepository
from admin_platform.domains.monitor.schemas import (
    AuditEventDetail,
    AuditEventPage,
    AuditEventRead,
    CacheMetrics,
    LoginLogPage,
    LoginLogRead,
    OnlineSession,
    OnlineSessionPage,
    ServerMetrics,
)

_AUDIT_NOT_FOUND = "monitor.AUDIT_EVENT_NOT_FOUND"
_LOGIN_LOG_NOT_FOUND = "monitor.LOGIN_LOG_NOT_FOUND"
_ONLINE_NOT_FOUND = "monitor.ONLINE_SESSION_NOT_FOUND"
# 强制下线写入的撤销原因（auth_refresh_tokens.revoked_reason，自由文本列）。
_FORCED_LOGOUT_REASON = "forced_logout"
# 缓存采集超时：监控不该因 Redis 慢/挂而拖垮请求，超时即降级为 available=False。
_CACHE_TIMEOUT_S = 2.0


def _total_pages(total: int, size: int) -> int:
    return math.ceil(total / size) if total else 0


class MonitorService:
    def __init__(self, repo: MonitorRepository) -> None:
        self._repo = repo

    async def list_audit_events(
        self,
        *,
        event_type: str | None,
        actor_user_id: int | None,
        result_status: str | None,
        page: int,
        size: int,
    ) -> AuditEventPage:
        rows = await self._repo.list_audit_events(
            event_type=event_type,
            actor_user_id=actor_user_id,
            result_status=result_status,
            page=page,
            size=size,
        )
        total = await self._repo.count_audit_events(
            event_type=event_type, actor_user_id=actor_user_id, result_status=result_status
        )
        return AuditEventPage(
            items=[AuditEventRead.model_validate(r) for r in rows],
            page=page,
            size=size,
            total=total,
            total_pages=_total_pages(total, size),
        )

    async def get_audit_event(self, event_pk: int) -> AuditEventDetail:
        row = await self._repo.get_audit_event(event_pk)
        if row is None:
            raise AppError(code=_AUDIT_NOT_FOUND, title="Audit event not found", status_code=404)
        return AuditEventDetail.model_validate(row)

    async def list_login_logs(
        self, *, username: str | None, status: str | None, page: int, size: int
    ) -> LoginLogPage:
        rows = await self._repo.list_login_logs(
            username=username, status=status, page=page, size=size
        )
        total = await self._repo.count_login_logs(username=username, status=status)
        return LoginLogPage(
            items=[LoginLogRead.model_validate(r) for r in rows],
            page=page,
            size=size,
            total=total,
            total_pages=_total_pages(total, size),
        )

    async def get_login_log(self, log_pk: int) -> LoginLogRead:
        row = await self._repo.get_login_log(log_pk)
        if row is None:
            raise AppError(code=_LOGIN_LOG_NOT_FOUND, title="Login log not found", status_code=404)
        return LoginLogRead.model_validate(row)

    # ---- 在线用户 ----

    async def list_online_sessions(self, *, page: int, size: int) -> OnlineSessionPage:
        now = datetime.now(UTC)
        rows = await self._repo.list_online_sessions(now=now, page=page, size=size)
        total = await self._repo.count_online_sessions(now=now)
        return OnlineSessionPage(
            items=[
                OnlineSession(
                    session_id=str(r.session_id),
                    user_id=r.user_id,
                    username=r.username,
                    login_time=r.login_time,
                    last_active_time=r.last_active_time,
                    expires_at=r.expires_at,
                )
                for r in rows
            ],
            page=page,
            size=size,
            total=total,
            total_pages=_total_pages(total, size),
        )

    async def force_logout(self, session_id: uuid.UUID) -> str:
        """强制下线：撤销该会话 family，返回被踢用户名（供审计 display）。会话不存在/已结束 → 404。"""
        now = datetime.now(UTC)
        row = await self._repo.get_online_session(session_id, now=now)
        if row is None:
            raise AppError(
                code=_ONLINE_NOT_FOUND, title="Online session not found", status_code=404
            )
        await self._repo.revoke_online_session(session_id, reason=_FORCED_LOGOUT_REASON, now=now)
        return row.username


class SystemMonitorService:
    """服务 / 缓存监控编排（P4）。无 DB session：服务监控直采，缓存监控带超时 + 降级。

    缓存监控刻意**不抛 500**：Redis 未配置或不可达时返回 ``available=False`` —— 监控面板要
    能显示「缓存挂了」，而不是自己也跟着 500。超时上限 ``_CACHE_TIMEOUT_S`` 防慢 Redis 拖垮请求。
    """

    def __init__(self, collector: SystemMetricsCollector, redis: Redis | None) -> None:
        self._collector = collector
        self._redis = redis

    async def get_server_metrics(self) -> ServerMetrics:
        return await self._collector.collect_server()

    async def get_cache_metrics(self) -> CacheMetrics:
        if self._redis is None:
            return self._cache_unavailable()
        try:
            return await asyncio.wait_for(
                self._collector.collect_cache(self._redis), timeout=_CACHE_TIMEOUT_S
            )
        except TimeoutError, RedisError, OSError:
            return self._cache_unavailable()

    @staticmethod
    def _cache_unavailable() -> CacheMetrics:
        return CacheMetrics(
            available=False,
            db_size=None,
            info=None,
            command_stats=[],
            collected_at=datetime.now(UTC),
        )
