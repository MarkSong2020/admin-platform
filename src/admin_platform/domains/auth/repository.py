"""Auth refresh token repository —— SQLAlchemy 2.x async（spec 2026-06-09 §1.3）。

承载 rotation + reuse detection + 并发 family 上限的 DB 操作。返回 ORM 行 / None，不抛业务异常
（业务判定在 service）。关键：``find_active_by_jti_for_update`` 用 ``SELECT FOR UPDATE`` 锁行，
关掉同一 refresh token 并发轮换的竞态（Codex 风险 1）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.auth.models import RefreshToken

# per-user refresh advisory lock 命名空间（与 dept 478221 / role 478231-2 / menu 478241-2 /
# post 478251 的单 bigint 锁隔离：本锁用 (ns, user_id) 双 int4 形式，不会跨域互锁）。
# hardening-r1 H1：登录签发、轮换、撤销、强制下线（monitor 复用同 NS）全经此锁串行化同一用户的
# family 变更，关掉并发轮换插入新 token 逃逸并发撤销的 READ COMMITTED 快照竞态。公开（去下划线）
# 供 monitor.repository 复用。
REFRESH_USER_LOCK_NS = 478260


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_user_lock(self, user_id: int) -> None:
        """per-user 事务级 advisory lock —— 串行化同一用户的全部 family 变更：登录签发（签新 family
        + 上限检查，Codex 深审 F）、轮换、撤销、强制下线（hardening-r1 H1）。否则并发轮换插入的新
        token 不在并发撤销语句的快照内 → 逃逸 reuse 检测/logout/强制下线。提交/回滚自动释放。"""
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, :uid)").bindparams(
                ns=REFRESH_USER_LOCK_NS, uid=user_id
            )
        )

    async def create(  # noqa: PLR0913 —— refresh token 字段多且全命名 kwargs，数据访问层可放宽
        self,
        *,
        jti: uuid.UUID,
        family_id: uuid.UUID,
        user_id: int,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        family_absolute_at: datetime,
    ) -> RefreshToken:
        row = RefreshToken(
            jti=jti,
            family_id=family_id,
            user_id=user_id,
            token_hash=token_hash,
            issued_at=issued_at,
            expires_at=expires_at,
            family_absolute_at=family_absolute_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_by_jti_for_update(self, jti: uuid.UUID) -> RefreshToken | None:
        """按 jti 取行并 ``FOR UPDATE`` 锁定（轮换串行化，防并发签出双后继）。"""
        stmt = select(RefreshToken).where(RefreshToken.jti == jti).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_user_id_by_jti(self, jti: uuid.UUID) -> int | None:
        """无锁轻量读 user_id（hardening-r1 H1）：轮换/撤销入口在 ``FOR UPDATE`` 锁行前先取此值
        → ``acquire_user_lock``，保证「先拿 user 锁、再拿行锁」的统一顺序（防与 revoke 死锁）。"""
        stmt = select(RefreshToken.user_id).where(RefreshToken.jti == jti)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def mark_rotated(self, row: RefreshToken, *, new_jti: uuid.UUID, now: datetime) -> None:
        """旧 token 标记为已轮换（rotated_to_jti + revoked，原因 rotated）。"""
        row.rotated_to_jti = new_jti
        row.revoked_at = now
        row.revoked_reason = "rotated"
        row.last_used_at = now
        await self._session.flush()

    async def revoke_family(self, family_id: uuid.UUID, *, reason: str, now: datetime) -> int:
        """撤销整个 family 的全部未撤销 token（reuse detection / logout / concurrency）。返回撤销数。"""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        )
        result = await self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def list_active_families(self, user_id: int, *, now: datetime) -> list[uuid.UUID]:
        """用户当前活跃 family（未撤销且未过期），按最近活跃→最旧排序（并发上限淘汰最旧用）。"""
        # 每 family 取最大 issued_at 作活跃度；只算未撤销未过期的 token。
        stmt = (
            select(RefreshToken.family_id, func.max(RefreshToken.issued_at).label("recent"))
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .group_by(RefreshToken.family_id)
            .order_by(func.max(RefreshToken.issued_at).desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [r.family_id for r in rows]

    async def delete_expired(self, *, before: datetime | None = None) -> int:
        """物理删除已过期 token（CLI cleanup 用）。``before`` 默认 now。返回删除数。"""
        cutoff = before or datetime.now(UTC)
        stmt = delete(RefreshToken).where(RefreshToken.expires_at <= cutoff)
        result = await self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)
