"""登录用例 —— 按 username 查用户、验密码、签 access token（单租户）。

安全设计（经 Codex 安全 PK 收紧，沿用到 P0.9 单租户）：

  * **时序抹平**：无论用户是否存在，每请求恰好对 argon2 ``verify`` 一次（真实 hash 或
    固定 dummy hash），避免"用户不存在跳过 verify"的响应时间差泄露账号是否存在。
  * **统一失败**：用户不存在/停用、密码错 —— 一律 ``auth.LOGIN_FAILED`` + 401，不区分以防枚举。
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus

from redis.asyncio import Redis

from admin_platform.audit.emit import build_audit_event, emit_audit
from admin_platform.audit.events import AuditActor, AuditResult, AuditTarget, RiskLevel
from admin_platform.core.config import get_settings
from admin_platform.core.errors import (
    AUTH_CAPTCHA_REQUIRED,
    AUTH_LOGIN_FAILED,
    AUTH_LOGIN_RATE_LIMITED,
    AUTH_PASSWORD_INCORRECT,
    AUTH_PASSWORD_TOO_WEAK,
    AppError,
)
from admin_platform.core.security import (
    ahash_password,
    averify_password,
    issue_access_token,
)
from admin_platform.db.session import db_session
from admin_platform.domains.auth import login_guard
from admin_platform.domains.auth.captcha import generate_captcha, verify_captcha
from admin_platform.domains.auth.login_log import record_login_attempt
from admin_platform.domains.auth.refresh_service import (
    issue_login_refresh,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from admin_platform.domains.auth.repository import RefreshTokenRepository
from admin_platform.domains.auth.schemas import CaptchaResponse, LoginResponse
from admin_platform.domains.user.models import User
from admin_platform.domains.user.repository import UserRepository

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

    # 块前声明（review F2：失败路径的 record_login_attempt 移出业务 session 块，避免在外层连接
    # 仍持有时开第二个独立 session → 每次失败登录占 2 连接；登录日志独立 session 落在块外即可）。
    login_failed = False
    failed_user_id: int | None = None
    success_user_id = 0
    success_username = ""
    token = ""
    issued = None
    async with db_session() as session:
        # M13：经 UserRepository 查（不在 service 手写 SQL）——查询口径集中在 repository，将来给
        # users 加软删/全局过滤只改一处，不漏登录这条最敏感路径。
        user = await UserRepository(session).find_by_username(username)

        # 只有"active 用户"才算候选；否则用 dummy hash 走同一条 verify，时序一致。
        active_user = user if (user is not None and user.status == _ACTIVE) else None
        password_hash = (
            active_user.password_hash if active_user is not None else _DUMMY_PASSWORD_HASH
        )
        # argon2 verify 下沉线程池（M1）：不堵事件循环（dummy hash 路径同样下沉，时序仍一致）。
        password_ok = await averify_password(password, password_hash)

        if active_user is None or not password_ok:
            _emit_login_failed(username)
            failed_user_id = active_user.id if active_user is not None else None
            login_failed = True
        else:
            success_user_id = active_user.id
            success_username = active_user.username
            token = issue_access_token(user_id=active_user.id, username=active_user.username)
            # P1.4：签发 refresh token（新 family）+ 并发上限淘汰最旧 family（同事务）。
            # pepper 未配时降级不发 refresh（向后兼容，同 auth_enabled/idempotency 的可选风格）——
            # 配了 APP_AUTH_REFRESH_TOKEN_PEPPER 才启用 refresh flow。
            if get_settings().auth_refresh_token_pepper:
                # per-user lock 串行化签发 + 上限（Codex 深审 F，防并发登录超 max_sessions）。
                issued = await issue_login_refresh(session, user_id=active_user.id)

    # 业务 session 块已退出（连接释放）。失败：块外落登录日志 + raise（审计已在块内 emit 进缓冲）。
    if login_failed:
        # record_failure（redis 计数）移出业务事务块（M2 hardening-r1）：Redis 慢/挂时不再连带
        # 占住 DB 连接（与 review F2 把 record_login_attempt 移出块外同口径）。
        if redis is not None:
            await login_guard.record_failure(redis, username=username, client_ip=client_ip)
        await record_login_attempt(
            username=username,
            status="failure",
            reason_code=AUTH_LOGIN_FAILED,
            user_id=failed_user_id,
        )
        raise _login_failed()

    # 登录成功：清失败计数 + 解软锁（spec §1.5）。
    if redis is not None:
        await login_guard.clear_on_success(redis, username=username, client_ip=client_ip)

    # P2：成功审计 + 登录日志（均在业务事务提交后落，时点正确）。
    _emit_login_success(success_user_id, success_username)
    await record_login_attempt(username=success_username, status="success", user_id=success_user_id)

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


def _emit_password_change(user_id: int, username: str, *, ok: bool) -> None:
    """改密审计（high-risk，成功/失败都记）。密码明文绝不进 metadata（deny-list 也会兜底脱敏）。"""
    result = (
        AuditResult(status="success", http_status=200)
        if ok
        else AuditResult(status="failure", http_status=400, error_code=AUTH_PASSWORD_INCORRECT)
    )
    emit_audit(
        build_audit_event(
            event_type="password_change",
            action="auth.change_password",
            title="修改密码" if ok else "修改密码失败（原密码错）",
            actor=AuditActor(user_id=user_id, username=username),
            target=AuditTarget(type="user", id=str(user_id), display=username),
            result=result,
            risk_level="high",
        )
    )


def _validate_new_password(new_password: str, *, username: str, old_password: str) -> None:
    """新密码强度（service 层：需 user 上下文）。长度≥12 / 不含首尾空白已在 schema 校验。

    复用 CLI 既有标准（不等于用户名）+ 要求新密码 ≠ 原密码（用户拍板 2026-06-15）。
    """
    if new_password == username:
        raise AppError(
            code=AUTH_PASSWORD_TOO_WEAK,
            title="Weak password",
            detail="新密码不能与用户名相同",
            status_code=int(HTTPStatus.UNPROCESSABLE_ENTITY),
        )
    if new_password == old_password:
        raise AppError(
            code=AUTH_PASSWORD_TOO_WEAK,
            title="Weak password",
            detail="新密码不能与原密码相同",
            status_code=int(HTTPStatus.UNPROCESSABLE_ENTITY),
        )


async def change_password(user_id: int, old_password: str, new_password: str) -> LoginResponse:
    """自助改密（已登录用户改自己）：验原密 → 校验新密强度 → 哈希更新 → 撤全部旧 refresh 会话 →
    给当前会话重签新 token（方案 A，用户拍板 2026-06-15）。

    安全：改密成功撤销该用户**所有**旧 refresh family（含可能被盗的），响应返回一对新 access+refresh，
    当前会话换新 token 无缝继续、其他设备旧 refresh 全失效需重登。事务边界同 ``refresh()``：撤销 +
    改密 + 重签是一个事务的原子副作用；失败（原密码错/弱密码）在事务内 catch、正常退出上下文
    （COMMIT 空事务无害）后再 re-raise——若让异常直接穿出会 ROLLBACK，但失败路径本就无业务写，
    审计已 emit 进缓冲（不随 rollback 丢）。原密码错返 400（``auth.PASSWORD_INCORRECT``，已鉴权故非
    401）；不额外限流（用户拍板：JWT 已确立身份）。
    """
    deferred: AppError | None = None
    response: LoginResponse | None = None
    actor_username = ""
    async with db_session() as session:
        try:
            user = await UserRepository(session).get(user_id)
            # 已过 require_current_user，user 理论必存在且 active；防御兜底（token 未过期但账号已删/停用）。
            if user is None or user.status != _ACTIVE:
                raise _login_failed()
            actor_username = user.username
            # 验原密码（线程池 argon2，同 login 路径）。
            if not await averify_password(old_password, user.password_hash):
                _emit_password_change(user_id, user.username, ok=False)
                raise AppError(
                    code=AUTH_PASSWORD_INCORRECT,
                    title="Current password incorrect",
                    detail="当前密码不正确",
                    status_code=400,
                )
            _validate_new_password(new_password, username=user.username, old_password=old_password)
            # 哈希新密码 + 写入（线程池）。
            user.password_hash = await ahash_password(new_password)
            await session.flush()
            # access token 始终重签（无状态 JWT）。refresh 的「撤全部旧 family + 重签新」绑定在 pepper
            # 门控内（review P1-2）：要么都做（pepper 配了），要么都不做（pepper 未配则本就无 refresh
            # flow）——避免 pepper 未配时「撤全部旧 family 却不发新 refresh」造成隐性强制登出。
            access = issue_access_token(user_id=user.id, username=user.username)
            issued = None
            if get_settings().auth_refresh_token_pepper:
                # 锁序 H1：先 user 锁再撤，与轮换/logout 同顺序防竞态。
                refresh_repo = RefreshTokenRepository(session)
                await refresh_repo.acquire_user_lock(user_id)
                now = datetime.now(UTC)
                for family_id in await refresh_repo.list_active_families(user_id, now=now):
                    await refresh_repo.revoke_family(family_id, reason="password_changed", now=now)
                issued = await issue_refresh_token(session, user_id=user_id)
            response = LoginResponse(
                access_token=access,
                expires_in=get_settings().auth_access_token_ttl_seconds,
                refresh_token=issued.token if issued is not None else None,
                refresh_expires_in=issued.expires_in if issued is not None else None,
            )
        except AppError as exc:
            deferred = exc
    if deferred is not None:
        raise deferred
    if response is None:  # 不变式：无 deferred ⇒ response 已构造；防御兜底（理论不可达）。
        raise _login_failed()
    # 成功审计（事务提交后 emit，同 login 成功路径时点正确）。
    _emit_password_change(user_id, actor_username, ok=True)
    return response
