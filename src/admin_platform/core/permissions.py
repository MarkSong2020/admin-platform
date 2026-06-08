"""RBAC 权限校验依赖（spec §3.2）。

``require_permission(perm)`` 产出 FastAPI 依赖，实现「默认 deny + 后端强校验」：
仅当当前用户拥有权限点 ``perm``（或为超管短路）才放行，否则 403。权限 / 数据范围
不进 JWT（spec §3.1），由本依赖在请求时经 ``PermissionProvider`` 查 DB 填充到
``CurrentUser``（Q8：不缓存、改权限立即生效）。

超管短路（spec §2.3）：``is_super_admin`` 布尔信任根放行，覆盖 RBAC 权限点 +
data_scope（视作 ALL 范围）；但**不绕过**登录（``require_current_user`` 在前）、
账号状态、审计、业务不变式、资源存在性。短路只认布尔，不认 permissions 通配。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends

from admin_platform.audit.emit import build_audit_event, emit_audit
from admin_platform.audit.events import AuditActor, AuditResult
from admin_platform.authz.permissions import ALL_PERMISSIONS
from admin_platform.authz.providers import MenuProvider, PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import (
    AUTH_ACCOUNT_DISABLED,
    AUTH_FORBIDDEN_BY_ROLE,
    AppError,
)

# 路由实际使用的权限点集（require_permission 调用时登记，spec §13.2 三组集合之②）。
# 装饰器在各 api 模块 import 时执行 → 导入全部域 api 后本集合即「路由用集」，供契约机检。
USED_PERMISSIONS: set[str] = set()


def get_permission_provider() -> PermissionProvider:
    """FastAPI 依赖：PermissionProvider 注入点（fail-closed）。

    P1 真实 DB Provider 在 RBAC 域（role/menu）落地后实现，并经
    ``app.dependency_overrides`` 或真实依赖接线；未接线时抛错（不静默放行）。
    机制层单测用 ``dependency_overrides`` / 直接传参注入 stub。
    """
    raise RuntimeError(
        "PermissionProvider 未接线（P1 机制就绪，待 RBAC 域落地后注入真实 Provider）"
    )


def get_menu_provider() -> MenuProvider:
    """FastAPI 依赖：MenuProvider 注入点（fail-closed，镜像 get_permission_provider）。

    getRouters 端点（§6.1）的菜单树数据源；由组合根 ``main.py`` 经 ``dependency_overrides``
    注入真实 ``DbMenuProvider``，未接线时抛错（不静默返回空菜单）。
    """
    raise RuntimeError("MenuProvider 未接线（待组合根注入 DbMenuProvider）")


def require_permission(perm: str) -> Callable[..., CurrentUser]:
    """产出校验权限点 ``perm`` 的 FastAPI 依赖（默认 deny）。

    用法（守卫端点 + 注入填充后的 user）::

        @router.get("/users")
        async def list_users(
            user: CurrentUser = Depends(require_permission("system:user:list")),
        ): ...
    """

    # registry 真相源校验（spec §13.2）：路由只能用已注册的权限点，否则 fail-fast（防悬空 /
    # 拼错权限点变成永远无人拥有的死守卫）。同时登记到 USED_PERMISSIONS 供三组集合契约机检。
    if perm not in ALL_PERMISSIONS:
        raise ValueError(
            f"未注册的权限点 {perm!r}：必须先在 authz.permissions.Permissions 声明（spec §13.2）"
        )
    USED_PERMISSIONS.add(perm)

    def _emit_denied(user_id: int, error_code: str) -> None:
        """审计：权限拒绝（spec §13.3 三类事件之一）。超管不绕审计（§2.3）。最小 hook，
        request 段（method/path/ip）留 P2 中间件补；emit 失败不阻断主流程（见 emit_audit）。"""
        emit_audit(
            build_audit_event(
                event_type="permission_denied",
                action=perm,
                title="权限拒绝",
                actor=AuditActor(user_id=user_id),
                result=AuditResult(
                    status="denied", http_status=int(HTTPStatus.FORBIDDEN), error_code=error_code
                ),
                risk_level="medium",
            )
        )

    def _dep(
        base_user: Annotated[CurrentUser, Depends(require_current_user)],
        provider: Annotated[PermissionProvider, Depends(get_permission_provider)],
    ) -> CurrentUser:
        user_id = int(base_user.user_id)

        # 账号状态请求期校验（spec §2.3「不绕过账号状态」+ Codex 深审）：持有效 token 但账号
        # 停用（status != active）即使是超管 / 有角色也一律 403——放在超管短路之前，停用账号
        # 不享任何短路。get_is_active 默认 True（内存 stub），真实 DbPermissionProvider 查 DB。
        if not provider.get_is_active(user_id):
            _emit_denied(user_id, AUTH_ACCOUNT_DISABLED)
            raise AppError(
                code=AUTH_ACCOUNT_DISABLED,
                title="Account disabled",
                detail="账号已停用",
                status_code=int(HTTPStatus.FORBIDDEN),
            )

        # 超管短路：覆盖 RBAC + data_scope（ALL 范围）；登录已由 require_current_user 保证。
        if provider.get_is_super_admin(user_id):
            return replace(
                base_user,
                is_super_admin=True,
                data_scope=DataScope(ScopeType.ALL, user_id=user_id),
            )

        # 默认 deny：未显式拥有该权限点即拒绝。
        permissions = provider.get_user_permissions(user_id)
        if perm not in permissions:
            _emit_denied(user_id, AUTH_FORBIDDEN_BY_ROLE)
            raise AppError(
                code=AUTH_FORBIDDEN_BY_ROLE,
                title="Forbidden",
                detail=f"缺少权限: {perm}",
                status_code=int(HTTPStatus.FORBIDDEN),
            )

        data_scope = provider.get_effective_data_scope(user_id)
        return replace(
            base_user,
            is_super_admin=False,
            permissions=permissions,
            dept_id=data_scope.dept_id,
            data_scope=data_scope,
        )

    return _dep
