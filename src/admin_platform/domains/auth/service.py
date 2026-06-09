"""登录用例 —— 按 username 查用户、验密码、签 access token（单租户）。

安全设计（经 Codex 安全 PK 收紧，沿用到 P0.9 单租户）：

  * **时序抹平**：无论用户是否存在，每请求恰好对 argon2 ``verify`` 一次（真实 hash 或
    固定 dummy hash），避免"用户不存在跳过 verify"的响应时间差泄露账号是否存在。
  * **统一失败**：用户不存在/停用、密码错 —— 一律 ``auth.LOGIN_FAILED`` + 401，不区分以防枚举。
"""

from __future__ import annotations

from http import HTTPStatus

from redis.asyncio import Redis
from sqlalchemy import select

from admin_platform.audit.emit import build_audit_event, emit_audit
from admin_platform.audit.events import AuditActor, AuditResult, AuditTarget
from admin_platform.core.config import get_settings
from admin_platform.core.errors import (
    AUTH_CAPTCHA_REQUIRED,
    AUTH_LOGIN_FAILED,
    AUTH_LOGIN_RATE_LIMITED,
    AppError,
)
from admin_platform.core.security import issue_access_token, verify_password
from admin_platform.db.session import db_session
from admin_platform.domains.auth import login_guard
from admin_platform.domains.auth.captcha import generate_captcha, verify_captcha
from admin_platform.domains.auth.refresh_service import (
    enforce_concurrency_limit,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from admin_platform.domains.auth.schemas import CaptchaResponse, LoginResponse
from admin_platform.domains.user.models import User

# 固定合法 argon2id hash（参数同生产默认 m=64MiB/t=3/p=4）——用户不存在/停用时对它 verify
# 一次抹平时序。不是真实凭据：任何输入都不会匹配。模块常量，避免每请求重算 hash。
_DUMMY_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$iDw2tHYbLK1W2ePHxneZrQ$75ZMyLvreUpo6erTEm/U5TnvtnlU2/srTZYqcAJoaMY"  # noqa: S105

_ACTIVE = "active"


def _login_failed() -> AppError:
    """统一登录失败（不区分失败原因以防枚举）。"""
    return AppError(
        code=AUTH_LOGIN_FAILED,
        title="Login failed",
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def login(  # noqa: PLR0913 —— 登录用例需 captcha/ip/redis 上下文，命名 kwargs，用例层可放宽
    username: str,
    password: str,
    *,
    captcha_id: str | None = None,
    captcha_answer: str | None = None,
    client_ip: str | None = None,
    redis: Redis | None = None,
) -> LoginResponse:
    """校验 (username, password)，成功返回 access token（+ refresh，P1.4）。

    ``redis`` 非空时启用验证码 + 限流（Q14）：IP 超限 → 429；账号软锁 / 失败达阈值要求验证码
    （未提供有效验证码）→ ``auth.CAPTCHA_REQUIRED``；其余失败累加计数。``redis`` 为空（未部署
    Redis）则跳过限流/验证码（向后兼容，同 refresh pepper 降级）。
    """
    # 限流前置（spec §1.5）：在密码校验前判定，防撞库放大 argon2 成本。
    if redis is not None:
        decision = await login_guard.pre_check(redis, username=username, client_ip=client_ip)
        if decision.ip_rate_limited:
            raise AppError(
                code=AUTH_LOGIN_RATE_LIMITED,
                title="Too many attempts",
                detail="请求过于频繁，请稍后再试",
                status_code=int(HTTPStatus.TOO_MANY_REQUESTS),
                headers={"Retry-After": str(get_settings().auth_login_lock_seconds)},
            )
        # 账号软锁（Codex 复审修复）：硬锁 —— 锁定期内统一 401 LOGIN_FAILED（不被验证码解锁，
        # 防枚举不暴露「锁定状态」）。decision-log「账号软锁 10min / 统一 401」。
        if decision.account_locked:
            await login_guard.record_failure(redis, username=username, client_ip=client_ip)
            raise _login_failed()
        # 失败达阈值 → 要求验证码（Q14：失败 N 次后才要，非首登必填）。
        if decision.require_captcha and not await verify_captcha(redis, captcha_id, captcha_answer):
            raise AppError(
                code=AUTH_CAPTCHA_REQUIRED,
                title="Captcha required",
                detail="请先通过验证码",
                status_code=int(HTTPStatus.FORBIDDEN),
            )

    async with db_session() as session:
        user = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()

        # 只有"active 用户"才算候选；否则用 dummy hash 走同一条 verify，时序一致。
        active_user = user if (user is not None and user.status == _ACTIVE) else None
        password_hash = (
            active_user.password_hash if active_user is not None else _DUMMY_PASSWORD_HASH
        )
        password_ok = verify_password(password, password_hash)

        if active_user is None or not password_ok:
            if redis is not None:
                await login_guard.record_failure(redis, username=username, client_ip=client_ip)
            # 审计：登录失败（spec §13.3 三类事件之一）。防枚举——不暴露「用户是否存在」，
            # 只把尝试的 username 记进 target.display；actor 留空（尚未确立身份）。
            emit_audit(
                build_audit_event(
                    event_type="login_failed",
                    action="auth.login",
                    title="登录失败",
                    actor=AuditActor(),
                    target=AuditTarget(type="user", display=username),
                    result=AuditResult(
                        status="failure", http_status=401, error_code=AUTH_LOGIN_FAILED
                    ),
                    risk_level="medium",
                )
            )
            raise _login_failed()

        token = issue_access_token(user_id=active_user.id, username=active_user.username)
        # P1.4：签发 refresh token（新 family）+ 并发上限淘汰最旧 family（同事务）。
        # pepper 未配时降级不发 refresh（向后兼容，同 auth_enabled/idempotency 的可选风格）——
        # 配了 APP_AUTH_REFRESH_TOKEN_PEPPER 才启用 refresh flow。
        issued = None
        if get_settings().auth_refresh_token_pepper:
            issued = await issue_refresh_token(session, user_id=active_user.id)
            await enforce_concurrency_limit(session, user_id=active_user.id)

    # 登录成功：清失败计数 + 解软锁（spec §1.5）。
    if redis is not None:
        await login_guard.clear_on_success(redis, username=username, client_ip=client_ip)

    return LoginResponse(
        access_token=token,
        expires_in=get_settings().auth_access_token_ttl_seconds,
        refresh_token=issued.token if issued is not None else None,
        refresh_expires_in=issued.expires_in if issued is not None else None,
    )


async def refresh(raw_token: str) -> LoginResponse:
    """轮换 refresh token → 新 access + 新 refresh（spec 2026-06-09 §1.3）。"""
    async with db_session() as session:
        result = await rotate_refresh_token(session, raw_token=raw_token)
        user = await session.get(User, result.user_id)
        if user is None or user.status != _ACTIVE:
            # 用户已删/停用：撤销该 family 并拒绝（不签新 access）。
            await revoke_refresh_token(session, raw_token=raw_token)
            raise _login_failed()
        access = issue_access_token(user_id=user.id, username=user.username)
    return LoginResponse(
        access_token=access,
        expires_in=get_settings().auth_access_token_ttl_seconds,
        refresh_token=result.refresh.token,
        refresh_expires_in=result.refresh.expires_in,
    )


async def logout(raw_token: str) -> None:
    """登出：按 refresh token 撤销其整个 family（幂等，token 非法也返回成功）。"""
    async with db_session() as session:
        await revoke_refresh_token(session, raw_token=raw_token)


async def issue_captcha(redis: Redis) -> CaptchaResponse:
    """生成算术验证码（spec §1.4）。"""
    captcha_id, question = await generate_captcha(redis)
    return CaptchaResponse(
        captcha_id=captcha_id,
        question=question,
        expires_in=get_settings().auth_captcha_ttl_seconds,
    )
