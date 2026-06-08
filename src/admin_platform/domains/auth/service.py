"""登录用例 —— 按 username 查用户、验密码、签 access token（单租户）。

安全设计（经 Codex 安全 PK 收紧，沿用到 P0.9 单租户）：

  * **时序抹平**：无论用户是否存在，每请求恰好对 argon2 ``verify`` 一次（真实 hash 或
    固定 dummy hash），避免"用户不存在跳过 verify"的响应时间差泄露账号是否存在。
  * **统一失败**：用户不存在/停用、密码错 —— 一律 ``auth.LOGIN_FAILED`` + 401，不区分以防枚举。
"""

from __future__ import annotations

from sqlalchemy import select

from admin_platform.audit.emit import build_audit_event, emit_audit
from admin_platform.audit.events import AuditActor, AuditResult, AuditTarget
from admin_platform.core.config import get_settings
from admin_platform.core.errors import AUTH_LOGIN_FAILED, AppError
from admin_platform.core.security import issue_access_token, verify_password
from admin_platform.db.session import db_session
from admin_platform.domains.auth.schemas import LoginResponse
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


async def login(username: str, password: str) -> LoginResponse:
    """校验 (username, password)，成功返回 access token。"""
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

    return LoginResponse(
        access_token=token,
        expires_in=get_settings().auth_access_token_ttl_seconds,
    )
