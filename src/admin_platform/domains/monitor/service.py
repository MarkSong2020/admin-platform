"""监控日志查询 service（P2 Phase 4）—— 薄编排：repository → 分页 DTO，detail 缺则 404。

分层：service 不 import fastapi、不抛 HTTPException —— 用 ``AppError``（全局 handler 翻 ProblemDetail）。
"""

from __future__ import annotations

import math

from admin_platform.core.errors import AppError
from admin_platform.domains.monitor.repository import MonitorRepository
from admin_platform.domains.monitor.schemas import (
    AuditEventDetail,
    AuditEventPage,
    AuditEventRead,
    LoginLogPage,
    LoginLogRead,
)

_AUDIT_NOT_FOUND = "monitor.AUDIT_EVENT_NOT_FOUND"
_LOGIN_LOG_NOT_FOUND = "monitor.LOGIN_LOG_NOT_FOUND"


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
