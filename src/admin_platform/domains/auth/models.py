"""Auth ORM 映射 — 表 ``auth_refresh_tokens``（P1.4）+ ``login_logs``（P2 登录日志）。

opaque refresh token 的服务端状态（spec 2026-06-09 §1.2）：只存 ``token_hash``
（HMAC-SHA256，不存明文）+ 轮换链（``family_id`` / ``rotated_to_jti``）+ 撤销标记。
rotation + reuse detection（用已轮换 token → 撤销整个 family）+ 并发 family 上限的状态载体。

device 信息（ip/ua）**只审计不强绑定校验**（后台 IP/UA 常变，强绑定误杀）—— P1.4 暂不落列。

``LoginLog``（P2 §2.2，对标 RuoYi ``sys_logininfor``）：登录尝试历史，覆盖成功 + 所有失败模式
（密码错 / 账号锁 / 限流 / 验证码）。与 ``audit_events`` 有意重叠（登录失败两处都有）——审计轨 vs
登录历史，回答不同问题。``user_id`` **无 FK**（失败时可空 + 用户删后留存），``request_id`` 关联
``audit_events``。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class RefreshToken(Base, IdMixin, TimestampMixin):
    __tablename__ = "auth_refresh_tokens"

    __table_args__ = (
        # 活跃 token 查询主路径（按用户筛未撤销未过期）+ family 轮换链 + jti/hash 唯一 + 过期清理。
        Index("ix_auth_refresh_tokens_user_family", "user_id", "family_id"),
        Index("ix_auth_refresh_tokens_user_active", "user_id", "revoked_at", "expires_at"),
        Index("ix_auth_refresh_tokens_expires_at", "expires_at"),
        # family_id 前导索引（hardening-r1 M）：revoke_family / get_online_session / 在线用户
        # family_id IN(子查询) 全按纯 family_id 过滤；(user_id,family_id) 复合索引前导是 user_id，
        # 服务不了纯 family 查询 → 全表扫。
        Index("ix_auth_refresh_tokens_family", "family_id"),
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
        UTCDateTime(), nullable=True, comment="撤销时间(非空=已撤销)"
    )
    revoked_reason: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="撤销原因(rotated/logout/reuse_detected/concurrency_limit/expired_cleanup)",
    )
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime(), comment="签发时间(UTC)")
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), comment="过期时间(UTC,min(idle,family_absolute))"
    )
    family_absolute_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        comment="family绝对过期上限(UTC,首登锚定,轮换透传不随清理漂移)",
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True, comment="最后轮换时间(UTC)"
    )


class LoginLog(Base, IdMixin, TimestampMixin):
    """登录日志（P2 §2.2，RuoYi ``sys_logininfor`` 对标）。append-only，每次登录尝试一条。"""

    __tablename__ = "login_logs"

    __table_args__ = (
        # 查询主路径：按账号查历史、按用户查、按状态筛（失败/锁）、按时间倒序。
        Index("ix_login_logs_username_time", "username", "login_at_utc"),
        Index("ix_login_logs_user_time", "user_id", "login_at_utc"),
        Index("ix_login_logs_status", "status"),
        Index("ix_login_logs_login_at", "login_at_utc"),
        # 复合索引（status 过滤 + login_at_utc 倒序 + id tiebreaker）——支撑 logininfor「按状态筛 +
        # 时间倒序」深翻页：MySQL 反向扫描复合索引免 sort，避免 OFFSET 深分页全表扫（PK 项3）。
        Index("ix_login_logs_status_time", "status", "login_at_utc", "id"),
    )

    username: Mapped[str] = mapped_column(String(64), comment="尝试登录的用户名")
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="用户ID(失败/不存在时可空,无FK)"
    )
    status: Mapped[str] = mapped_column(
        String(16), comment="success/failure/locked/rate_limited/captcha_required"
    )
    reason_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="失败原因码(error_code)"
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="客户端IP")
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="User-Agent")
    request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="请求ID(关联audit_events)"
    )
    login_at_utc: Mapped[datetime] = mapped_column(UTCDateTime(), comment="登录尝试时刻(UTC)")
