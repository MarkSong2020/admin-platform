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
from admin_platform.audit.events import AuditActor, AuditResult, AuditTarget, RiskLevel
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
from admin_platform.domains.auth.login_log import record_login_attempt
from admin_platform.domains.auth.refresh_service import (
    issue_login_refresh,
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


def _emit_login_failed(username: str, *, risk_level: RiskLevel = "medium") -> None:
    """登录失败审计（spec §13.3 三类必审事件之一）。防枚举：actor 留空（尚未确立身份），
    只把尝试的 username 记进 ``target.display``，不暴露「用户是否存在 / 是否被锁」。
    """
    emit_audit(
        build_audit_event(
            event_type="login_failed",
            action="auth.login",
            title="登录失败",
            actor=AuditActor(),
            target=AuditTarget(type="user", display=username),
            result=AuditResult(status="failure", http_status=401, error_code=AUTH_LOGIN_FAILED),
            risk_level=risk_level,
        )
    )


def _emit_login_success(user_id: int, username: str) -> None:
    """登录成功审计（P2：让 envelope 覆盖完整登录活动，compliance 常要成功登录留痕）。"""
    emit_audit(
        build_audit_event(
            event_type="login_success",
            action="auth.login",
            title="登录成功",
            actor=AuditActor(user_id=user_id, username=username),
            target=AuditTarget(type="user", id=str(user_id), display=username),
            result=AuditResult(status="success", http_status=200),
            risk_level="low",
        )
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
    （未提供有效验证码）→ ``auth.CAPTCHA_REQUIRED``；其余失败累加计数。``redis`` 是否非空由 api 层
    ``_login_guard_redis`` 按 ``auth_login_guard_enabled`` 决定（与 idempotency 解耦，Codex 深审）：
    guard 关 → None → 跳过限流/验证码。
    """
    # 限流前置（spec §1.5）：在密码校验前判定，防撞库放大 argon2 成本。
    if redis is not None:
        decision = await login_guard.pre_check(redis, username=username, client_ip=client_ip)
        if decision.ip_rate_limited:
            await record_login_attempt(
                username=username, status="rate_limited", reason_code=AUTH_LOGIN_RATE_LIMITED
            )
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
            # 审计（Workflow 深审）：锁定窗口内的持续尝试正是暴力破解最该留痕的时刻，
            # 不能因「对客户端防枚举不暴露锁定状态」而连内部审计一起省略。risk 升 high。
            _emit_login_failed(username, risk_level="high")
            await record_login_attempt(
                username=username, status="locked", reason_code=AUTH_LOGIN_FAILED
            )
            raise _login_failed()
        # 失败达阈值 → 要求验证码（Q14：失败 N 次后才要，非首登必填）。
        if decision.require_captcha and not await verify_captcha(redis, captcha_id, captcha_answer):
            await record_login_attempt(
                username=username, status="captcha_required", reason_code=AUTH_CAPTCHA_REQUIRED
            )
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
            _emit_login_failed(username)
            await record_login_attempt(
                username=username,
                status="failure",
                reason_code=AUTH_LOGIN_FAILED,
                user_id=active_user.id if active_user is not None else None,
            )
            raise _login_failed()

        token = issue_access_token(user_id=active_user.id, username=active_user.username)
        # P1.4：签发 refresh token（新 family）+ 并发上限淘汰最旧 family（同事务）。
        # pepper 未配时降级不发 refresh（向后兼容，同 auth_enabled/idempotency 的可选风格）——
        # 配了 APP_AUTH_REFRESH_TOKEN_PEPPER 才启用 refresh flow。
        issued = None
        if get_settings().auth_refresh_token_pepper:
            # per-user lock 串行化签发 + 上限（Codex 深审 F，防并发登录超 max_sessions）。
            issued = await issue_login_refresh(session, user_id=active_user.id)

    # 登录成功：清失败计数 + 解软锁（spec §1.5）。
    if redis is not None:
        await login_guard.clear_on_success(redis, username=username, client_ip=client_ip)

    # P2：成功审计 + 登录日志（均在业务事务提交后落，时点正确）。
    _emit_login_success(active_user.id, active_user.username)
    await record_login_attempt(
        username=active_user.username, status="success", user_id=active_user.id
    )

    return LoginResponse(
        access_token=token,
        expires_in=get_settings().auth_access_token_ttl_seconds,
        refresh_token=issued.token if issued is not None else None,
        refresh_expires_in=issued.expires_in if issued is not None else None,
    )


async def refresh(raw_token: str) -> LoginResponse:
    """轮换 refresh token → 新 access + 新 refresh（spec 2026-06-09 §1.3）。

    事务边界关键（Codex 深审 🔴-2）：拒绝路径（reuse 检测撤销 family / 停用账号撤销）的
    **撤销是安全副作用，必须随本事务提交**。若直接 ``raise AppError`` 让其穿出
    ``db_session()`` 的 ``session.begin()``，异常会触发 ROLLBACK → 撤销失效（401 照样返回，
    但 family 仍 active，防盗用 / 停用即失效形同虚设）。故在事务内 catch、正常退出上下文
    （COMMIT 副作用）后再 re-raise。无副作用的 ``REFRESH_TOKEN_INVALID`` 路径提交空事务无害。
    """
    response: LoginResponse | None = None
    deferred: AppError | None = None
    async with db_session() as session:
        try:
            result = await rotate_refresh_token(session, raw_token=raw_token)
            user = await session.get(User, result.user_id)
            if user is None or user.status != _ACTIVE:
                # 用户已删/停用：撤销该 family 并拒绝（不签新 access）。
                await revoke_refresh_token(session, raw_token=raw_token)
                # 审计（Round-3 对称）：停用/删除账号仍持有效 refresh → 强制撤销 family，是安全
                # 相关信号（token 存活超过账号有效期），与 reuse 路径（refresh_reused）对称留痕。
                # actor 用 token 已确立的 user_id（区别于 login 路径的 actor 留空防枚举）。
                emit_audit(
                    build_audit_event(
                        event_type="login_failed",
                        action="auth.refresh",
                        title="refresh 拒绝（账号停用/删除）",
                        actor=AuditActor(user_id=result.user_id),
                        target=AuditTarget(type="user", id=str(result.user_id)),
                        result=AuditResult(
                            status="failure", http_status=401, error_code=AUTH_LOGIN_FAILED
                        ),
                        risk_level="medium",
                    )
                )
                raise _login_failed()
            access = issue_access_token(user_id=user.id, username=user.username)
            response = LoginResponse(
                access_token=access,
                expires_in=get_settings().auth_access_token_ttl_seconds,
                refresh_token=result.refresh.token,
                refresh_expires_in=result.refresh.expires_in,
            )
        except AppError as exc:
            deferred = exc
    if deferred is not None:
        raise deferred
    if response is None:  # 不变式：无 deferred ⇒ response 已构造；防御性兜底（理论不可达）
        raise _login_failed()
    return response


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
