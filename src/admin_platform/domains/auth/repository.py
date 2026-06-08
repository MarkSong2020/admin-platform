"""Auth refresh token repository —— SQLAlchemy 2.x async（spec 2026-06-09 §1.3）。

承载 rotation + reuse detection + 并发 family 上限的 DB 操作。返回 ORM 行 / None，不抛业务异常
（业务判定在 service）。关键：``find_active_by_jti_for_update`` 用 ``SELECT FOR UPDATE`` 锁行，
关掉同一 refresh token 并发轮换的竞态（Codex 风险 1）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.auth.models import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(  # noqa: PLR0913 —— refresh token 字段多且全命名 kwargs，数据访问层可放宽
        self,
        *,
        jti: uuid.UUID,
        family_id: uuid.UUID,
        user_id: int,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> RefreshToken:
        row = RefreshToken(
            jti=jti,
            family_id=family_id,
            user_id=user_id,
            token_hash=token_hash,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_by_jti_for_update(self, jti: uuid.UUID) -> RefreshToken | None:
        """按 jti 取行并 ``FOR UPDATE`` 锁定（轮换串行化，防并发签出双后继）。"""
        stmt = select(RefreshToken).where(RefreshToken.jti == jti).with_for_update()
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

    async def get_family_origin_issued_at(self, family_id: uuid.UUID) -> datetime | None:
        """family 首个 token 的 issued_at（absolute 上限锚点，轮换不续期 absolute）。"""
        stmt = select(func.min(RefreshToken.issued_at)).where(RefreshToken.family_id == family_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

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
