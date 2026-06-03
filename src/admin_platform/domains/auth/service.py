"""登录用例（Task 6）—— system_session 查租户/用户、验密码、签 access token。

安全设计（经 Codex 安全 PK 收紧）：

  * **时序抹平**：无论租户/用户是否存在，每请求恰好对 argon2 ``verify`` 一次（真实 hash 或
    固定 dummy hash），避免"用户不存在跳过 verify"的响应时间差泄露账号是否存在。
  * **统一失败**：租户不存在/停用、用户不存在/停用、密码错 —— 一律 ``auth.LOGIN_FAILED`` +
    401，不区分以防枚举。
  * **is_platform 绑定哨兵租户**：仅当 ``tenant.code=="PLATFORM"`` 且 ``user.is_platform_admin``
    才签平台 token；否则非 PLATFORM 租户里一条脏 ``is_platform_admin=True`` 数据就能签出
    跨租户 bypass token。
  * **system_session bypass 全租户过滤** → 必须显式 ``where(tenant_id, username)``（见 ADR-A/E）。
"""

from __future__ import annotations

from sqlalchemy import select

from admin_platform.core.config import get_settings
from admin_platform.core.errors import AUTH_LOGIN_FAILED, AppError
from admin_platform.core.security import issue_access_token, verify_password
from admin_platform.db.session import system_session
from admin_platform.domains.auth.schemas import LoginResponse
from admin_platform.domains.tenant.models import Tenant
from admin_platform.domains.user.models import User

# 固定合法 argon2id hash（参数同生产默认 m=64MiB/t=3/p=4）——用户不存在/停用时对它 verify
# 一次抹平时序。不是真实凭据：任何输入都不会匹配。模块常量，避免每请求重算 hash。
_DUMMY_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$iDw2tHYbLK1W2ePHxneZrQ$75ZMyLvreUpo6erTEm/U5TnvtnlU2/srTZYqcAJoaMY"  # noqa: S105

_PLATFORM_CODE = "PLATFORM"
_ACTIVE = "active"


def _login_failed() -> AppError:
    """统一登录失败（不区分失败原因以防枚举）。"""
    return AppError(
        code=AUTH_LOGIN_FAILED,
        title="Login failed",
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def login(tenant_code: str, username: str, password: str) -> LoginResponse:
    """校验 (tenant_code, username, password)，成功返回带 tenant 上下文的 access token。"""
    async with system_session() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.code == tenant_code))
        ).scalar_one_or_none()

        user: User | None = None
        if tenant is not None and tenant.status == _ACTIVE:
            user = (
                await session.execute(
                    select(User).where(User.tenant_id == tenant.id, User.username == username)
                )
            ).scalar_one_or_none()

        # 只有"active 用户"才算候选；否则用 dummy hash 走同一条 verify，时序一致。
        active_user = user if (user is not None and user.status == _ACTIVE) else None
        password_hash = (
            active_user.password_hash if active_user is not None else _DUMMY_PASSWORD_HASH
        )
        password_ok = verify_password(password, password_hash)

        if active_user is None or not password_ok:
            raise _login_failed()

        # is_platform 必须绑定 PLATFORM 哨兵租户 + is_platform_admin（防脏数据签平台 token）。
        is_platform = bool(
            tenant is not None and tenant.code == _PLATFORM_CODE and active_user.is_platform_admin
        )
        token = issue_access_token(
            user_id=active_user.id,
            tenant_id=active_user.tenant_id,
            is_platform=is_platform,
            username=active_user.username,
        )

    return LoginResponse(
        access_token=token,
        expires_in=get_settings().auth_access_token_ttl_seconds,
    )
