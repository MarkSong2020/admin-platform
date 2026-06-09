"""监控日志查询 repository（P2 Phase 4）—— audit_events / login_logs 只读分页 + 过滤。

跨包读 ORM 模型（``audit.models.AuditEventLog`` / ``domains.auth.models.LoginLog``）——日志由审计
sink / 登录 service 写，监控域只读。过滤条件命中各表既有索引（event_type/actor/status/时间）。
"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.audit.models import AuditEventLog
from admin_platform.domains.auth.models import LoginLog


class MonitorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- audit_events（操作/审计日志）----

    def _audit_filtered(
        self, *, event_type: str | None, actor_user_id: int | None, result_status: str | None
    ) -> Select[tuple[AuditEventLog]]:
        stmt = select(AuditEventLog)
        if event_type is not None:
            stmt = stmt.where(AuditEventLog.event_type == event_type)
        if actor_user_id is not None:
            stmt = stmt.where(AuditEventLog.actor_user_id == actor_user_id)
        if result_status is not None:
            stmt = stmt.where(AuditEventLog.result_status == result_status)
        return stmt

    async def list_audit_events(
        self,
        *,
        event_type: str | None,
        actor_user_id: int | None,
        result_status: str | None,
        page: int,
        size: int,
    ) -> list[AuditEventLog]:
        stmt = (
            self._audit_filtered(
                event_type=event_type, actor_user_id=actor_user_id, result_status=result_status
            )
            .order_by(AuditEventLog.occurred_at.desc(), AuditEventLog.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_audit_events(
        self, *, event_type: str | None, actor_user_id: int | None, result_status: str | None
    ) -> int:
        inner = self._audit_filtered(
            event_type=event_type, actor_user_id=actor_user_id, result_status=result_status
        ).subquery()
        return int(
            (await self._session.execute(select(func.count()).select_from(inner))).scalar_one()
        )

    async def get_audit_event(self, event_pk: int) -> AuditEventLog | None:
        return await self._session.get(AuditEventLog, event_pk)

    # ---- login_logs（登录日志）----

    def _login_filtered(
        self, *, username: str | None, status: str | None
    ) -> Select[tuple[LoginLog]]:
        stmt = select(LoginLog)
        if username is not None:
            stmt = stmt.where(LoginLog.username == username)
        if status is not None:
            stmt = stmt.where(LoginLog.status == status)
        return stmt

    async def list_login_logs(
        self, *, username: str | None, status: str | None, page: int, size: int
    ) -> list[LoginLog]:
        stmt = (
            self._login_filtered(username=username, status=status)
            .order_by(LoginLog.login_at_utc.desc(), LoginLog.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_login_logs(self, *, username: str | None, status: str | None) -> int:
        inner = self._login_filtered(username=username, status=status).subquery()
        return int(
            (await self._session.execute(select(func.count()).select_from(inner))).scalar_one()
        )

    async def get_login_log(self, log_pk: int) -> LoginLog | None:
        return await self._session.get(LoginLog, log_pk)
