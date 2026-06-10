"""监控日志查询 repository（P2 Phase 4）—— audit_events / login_logs 只读分页 + 过滤。

跨包读 ORM 模型（``audit.models.AuditEventLog`` / ``domains.auth.models.LoginLog``）——日志由审计
sink / 登录 service 写，监控域只读。过滤条件命中各表既有索引（event_type/actor/status/时间）。

P4 在线用户：跨包读 ``auth.models.RefreshToken`` + ``user.models.User``，按 family 聚合活动会话
（命中 ``ix_auth_refresh_tokens_user_active``）；强制下线复用 ``revoke_family`` 同款 UPDATE 语义。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Row, Select, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.audit.models import AuditEventLog
from admin_platform.domains.auth.models import LoginLog, RefreshToken
from admin_platform.domains.auth.repository import REFRESH_USER_LOCK_NS
from admin_platform.domains.user.models import User


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

    # ---- 在线用户（活动 refresh token family 派生）----

    def _active_sessions_stmt(
        self, *, now: datetime
    ) -> Select[tuple[uuid.UUID, int, str, datetime, datetime, datetime]]:
        """活动会话聚合 select：按 family 分组，join users 取用户名。

        「活动 family」= 至少有 1 个未撤销且未过期 token 的 family（子查询 ``active_families``）。
        聚合跨该 family **全部 token**（不止活动 token），故：
          * login_time = min(issued_at) = family 首签 = **真实登录时刻**（轮换不丢失原点——
            每次 refresh 撤销旧 token，若只算活动 token 会把登录时间算成最近一次轮换时间）；
          * last_active_time = max(coalesce(last_used_at, issued_at)) = 最近轮换/使用；
          * expires_at = max(expires_at) = 当前活动 token 的有效过期（family 内各 token 的
            expires_at 随轮换前移，仅 family_absolute 上限共享锚点，故取 max 得最新一枚）。
        """
        active_families = (
            select(RefreshToken.family_id)
            .where(RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > now)
            .distinct()
        )
        return (
            select(
                RefreshToken.family_id.label("session_id"),
                RefreshToken.user_id.label("user_id"),
                User.username.label("username"),
                func.min(RefreshToken.issued_at).label("login_time"),
                func.max(func.coalesce(RefreshToken.last_used_at, RefreshToken.issued_at)).label(
                    "last_active_time"
                ),
                func.max(RefreshToken.expires_at).label("expires_at"),
            )
            .join(User, User.id == RefreshToken.user_id)
            .where(RefreshToken.family_id.in_(active_families))
            .group_by(RefreshToken.family_id, RefreshToken.user_id, User.username)
        )

    async def list_online_sessions(
        self, *, now: datetime, page: int, size: int
    ) -> list[Row[tuple[uuid.UUID, int, str, datetime, datetime, datetime]]]:
        stmt = (
            self._active_sessions_stmt(now=now)
            .order_by(
                func.max(func.coalesce(RefreshToken.last_used_at, RefreshToken.issued_at)).desc(),
                # tiebreaker：last_active 撞值时 family_id 兜底，保证跨页 offset/limit 稳定（不漏/不重）。
                RefreshToken.family_id.desc(),
            )
            .offset((page - 1) * size)
            .limit(size)
        )
        return list((await self._session.execute(stmt)).all())

    async def count_online_sessions(self, *, now: datetime) -> int:
        stmt = select(func.count(func.distinct(RefreshToken.family_id))).where(
            RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > now
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def get_online_session(
        self, family_id: uuid.UUID, *, now: datetime
    ) -> Row[tuple[uuid.UUID, int, str, datetime, datetime, datetime]] | None:
        """取单个活动会话（强制下线前的存在性检查 + 取用户名供审计 display）。"""
        stmt = self._active_sessions_stmt(now=now).where(RefreshToken.family_id == family_id)
        return (await self._session.execute(stmt)).first()

    async def acquire_user_lock(self, user_id: int) -> None:
        """复用 auth 的 per-user advisory lock（同 NS，hardening-r1 H1）：强制下线撤销 family 前先取
        锁，与 refresh 轮换/撤销串行化——否则并发轮换插入的新 token 不在本次撤销语句快照内 → 逃逸。"""
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, :uid)").bindparams(
                ns=REFRESH_USER_LOCK_NS, uid=user_id
            )
        )

    async def revoke_online_session(
        self, family_id: uuid.UUID, *, reason: str, now: datetime
    ) -> int:
        """撤销该 family 全部未撤销 token（镜像 auth.RefreshTokenRepository.revoke_family）。返回撤销数。

        ⚠️ 仅撤销 refresh token：access JWT 无状态，当前 access token 到期前仍有效（≤access TTL 窗口）。
        即时踢出需 access denylist（触鉴权中间件，留后续）。对标 RuoYi 在线用户档此语义可接受。
        """
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        )
        result = await self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)
