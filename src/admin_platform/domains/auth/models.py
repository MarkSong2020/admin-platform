"""Auth ORM 映射 — 表 ``auth_refresh_tokens``（P1.4 refresh token 落库可撤销）。

opaque refresh token 的服务端状态（spec 2026-06-09 §1.2）：只存 ``token_hash``
（HMAC-SHA256，不存明文）+ 轮换链（``family_id`` / ``rotated_to_jti``）+ 撤销标记。
rotation + reuse detection（用已轮换 token → 撤销整个 family）+ 并发 family 上限的状态载体。

device 信息（ip/ua）**只审计不强绑定校验**（后台 IP/UA 常变，强绑定误杀）—— P1.4 暂不落列。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.db.base import Base, IdMixin, TimestampMixin


class RefreshToken(Base, IdMixin, TimestampMixin):
    __tablename__ = "auth_refresh_tokens"

    __table_args__ = (
        # 活跃 token 查询主路径（按用户筛未撤销未过期）+ family 轮换链 + jti/hash 唯一 + 过期清理。
        Index("ix_auth_refresh_tokens_user_family", "user_id", "family_id"),
        Index("ix_auth_refresh_tokens_user_active", "user_id", "revoked_at", "expires_at"),
        Index("ix_auth_refresh_tokens_expires_at", "expires_at"),
    )

    jti: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, comment="当前token标识(UUID)")
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, comment="轮换链family(一次登录=一family)")
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), comment="所属用户ID"
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, comment="HMAC-SHA256(pepper,secret)的hex(不存明文)"
    )
    rotated_to_jti: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, comment="轮换后继jti(非空=已被轮换,再用即reuse)"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="撤销时间(非空=已撤销)"
    )
    revoked_reason: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="撤销原因(rotated/logout/reuse_detected/concurrency_limit/expired_cleanup)",
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="签发时间(UTC)")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="过期时间(UTC,absolute上限)"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后轮换时间(UTC)"
    )
