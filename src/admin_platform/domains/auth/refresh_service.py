"""refresh token 用例编排（spec 2026-06-09 §1.3）—— 签发 / 轮换 / reuse 检测 / 撤销。

service 抛 ``AppError``（不抛 HTTPException），错误码 ``auth.*``。事务边界由调用方
（``db_session``）拥有；轮换走 ``SELECT FOR UPDATE`` 锁行串行化（防并发签出双后继）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.audit.emit import build_audit_event, emit_audit
from admin_platform.audit.events import AuditActor, AuditResult
from admin_platform.core.config import get_settings
from admin_platform.core.errors import (
    AUTH_REFRESH_TOKEN_INVALID,
    AUTH_REFRESH_TOKEN_REUSED,
    AppError,
)
from admin_platform.core.security import (
    generate_refresh_token,
    parse_refresh_token,
    verify_refresh_secret,
)
from admin_platform.domains.auth.repository import RefreshTokenRepository


@dataclass(frozen=True)
class IssuedRefresh:
    """签发结果：明文 token（只此一次给客户端）+ jti + 过期秒数 + family（供调用方关联）。"""

    token: str
    jti: uuid.UUID
    expires_in: int
    family_id: uuid.UUID


def _now() -> datetime:
    return datetime.now(UTC)


async def issue_refresh_token(
    session: AsyncSession,
    *,
    user_id: int,
    family_id: uuid.UUID | None = None,
    family_absolute_at: datetime | None = None,
) -> IssuedRefresh:
    """签发新 refresh token row。``family_id`` 为空 = 新登录（新 family）；非空 = 轮换续链。

    双 TTL：本 token 过期 = ``min(now+idle, family_absolute)``。``family_absolute`` 在新登录
    时 = ``now+absolute_ttl``，轮换时由调用方传入「首登锚定」的上限（不因轮换无限续期）。
    """
    settings = get_settings()
    now = _now()
    fam = family_id or uuid.uuid4()
    family_absolute = family_absolute_at or (
        now + timedelta(seconds=settings.auth_refresh_absolute_ttl_seconds)
    )
    idle_expires = now + timedelta(seconds=settings.auth_refresh_idle_ttl_seconds)
    expires_at = min(idle_expires, family_absolute)

    token, jti_str, token_hash = generate_refresh_token()
    jti = uuid.UUID(jti_str)
    repo = RefreshTokenRepository(session)
    await repo.create(
        jti=jti,
        family_id=fam,
        user_id=user_id,
        token_hash=token_hash,
        issued_at=now,
        expires_at=expires_at,
    )
    return IssuedRefresh(
        token=token,
        jti=jti,
        expires_in=int((expires_at - now).total_seconds()),
        family_id=fam,
    )


async def enforce_concurrency_limit(session: AsyncSession, *, user_id: int) -> None:
    """并发 family 上限：超过 ``max_sessions_per_user`` 时撤销最旧 family（concurrency_limit）。

    在新 family 已创建后调用 —— 活跃 family 数 > 上限即把最旧的逐个撤销到上限内。
    """
    settings = get_settings()
    now = _now()
    repo = RefreshTokenRepository(session)
    families = await repo.list_active_families(user_id, now=now)  # 最近→最旧
    overflow = families[settings.auth_refresh_max_sessions_per_user :]
    for fam in overflow:
        await repo.revoke_family(fam, reason="concurrency_limit", now=now)


async def issue_login_refresh(session: AsyncSession, *, user_id: int) -> IssuedRefresh:
    """登录签发 refresh —— per-user advisory lock 串行化「签新 family + 并发上限淘汰」临界区
    （Codex 深审 F）：先拿锁再签发，关掉并发登录各自签 family 互不可见、超 max_sessions 的窗口。
    """
    repo = RefreshTokenRepository(session)
    await repo.acquire_user_lock(user_id)
    issued = await issue_refresh_token(session, user_id=user_id)
    await enforce_concurrency_limit(session, user_id=user_id)
    return issued


@dataclass(frozen=True)
class RotationResult:
    """轮换结果：新 refresh token + 关联 user_id（供签新 access token）。"""

    refresh: IssuedRefresh
    user_id: int


async def rotate_refresh_token(session: AsyncSession, *, raw_token: str) -> RotationResult:
    """轮换：校验 → 锁行 → reuse 检测 → 签新 token + 旧 token 标记 rotated。

    reuse detection（RFC 9700）：用已轮换（``rotated_to_jti`` 非空）的 token → 撤销整个 family
    + 抛 ``auth.REFRESH_TOKEN_REUSED``（token theft 信号）。其余无效一律
    ``auth.REFRESH_TOKEN_INVALID``（不暴露细节）。
    """
    parsed = parse_refresh_token(raw_token)
    if parsed is None:
        raise _invalid()
    jti_str, secret = parsed
    try:
        jti = uuid.UUID(jti_str)
    except ValueError:
        raise _invalid() from None

    now = _now()
    repo = RefreshTokenRepository(session)
    row = await repo.get_by_jti_for_update(jti)  # FOR UPDATE 锁行
    if row is None or not verify_refresh_secret(secret, row.token_hash):
        raise _invalid()

    # reuse detection：已轮换过的 token 再被使用 → token theft，撤销整个 family。
    if row.rotated_to_jti is not None or row.revoked_reason == "reuse_detected":
        await repo.revoke_family(row.family_id, reason="reuse_detected", now=now)
        # 审计：token theft 高风险信号（spec §13.3，audit_event.v1 EventType 演进）。
        emit_audit(
            build_audit_event(
                event_type="refresh_reused",
                action="auth.refresh",
                title="refresh token 重用检测",
                actor=AuditActor(user_id=row.user_id),
                result=AuditResult(
                    status="denied", http_status=401, error_code=AUTH_REFRESH_TOKEN_REUSED
                ),
                risk_level="high",
            )
        )
        raise AppError(
            code=AUTH_REFRESH_TOKEN_REUSED,
            title="Refresh token reused",
            detail="refresh token 重复使用，该会话已全部失效，请重新登录",
            status_code=401,
        )

    # 已撤销（非轮换原因，如 logout/concurrency）或已过期 → 无效。
    if row.revoked_at is not None or row.expires_at <= now:
        raise _invalid()

    # absolute 上限锚定 family 首登（轮换不续期 absolute）：超上限即拒绝，须重登。
    settings = get_settings()
    origin = await repo.get_family_origin_issued_at(row.family_id)
    family_absolute = (origin or row.issued_at) + timedelta(
        seconds=settings.auth_refresh_absolute_ttl_seconds
    )
    if now >= family_absolute:
        raise _invalid()

    # 正常轮换：签新 token（续链，沿用 family + absolute 锚），旧 token 标 rotated。
    new = await issue_refresh_token(
        session,
        user_id=row.user_id,
        family_id=row.family_id,
        family_absolute_at=family_absolute,
    )
    await repo.mark_rotated(row, new_jti=new.jti, now=now)
    return RotationResult(refresh=new, user_id=row.user_id)


async def revoke_refresh_token(session: AsyncSession, *, raw_token: str) -> bool:
    """logout：按 refresh token 撤销其整个 family。token 非法/查无 → 静默返回 False（logout 幂等）。"""
    parsed = parse_refresh_token(raw_token)
    if parsed is None:
        return False
    jti_str, secret = parsed
    try:
        jti = uuid.UUID(jti_str)
    except ValueError:
        return False
    repo = RefreshTokenRepository(session)
    row = await repo.get_by_jti_for_update(jti)
    if row is None or not verify_refresh_secret(secret, row.token_hash):
        return False
    await repo.revoke_family(row.family_id, reason="logout", now=_now())
    return True


def _invalid() -> AppError:
    return AppError(
        code=AUTH_REFRESH_TOKEN_INVALID,
        title="Refresh token invalid",
        detail="refresh token 无效或已过期，请重新登录",
        status_code=401,
    )
