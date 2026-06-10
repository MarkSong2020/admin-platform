"""RBAC 前端契约端点 —— getInfo / getRouters（spec §6 打通）。

跨域聚合（user 基础信息 + PermissionProvider 角色/权限 + MenuProvider 菜单树），故放
``api/v1`` 顶层而非某业务域。payload 形状按若依冻结（§6.1）：
  * ``GET /api/v1/auth/user-info``（getInfo）：user / roles / permissions。
  * ``GET /api/v1/menus/routers``（getRouters）：动态路由树。

实现要点：handler 本身在事件循环线程，**直接 await provider 的异步内核**（``a_*``），不走
同步桥（``run_in_host_loop`` 只在 ``require_permission`` 这类同步依赖的 threadpool 线程用）。
账号状态：``require_current_user`` 只验 token；停用账号的 getRouters 由 MenuProvider 内部
``status`` 校验返回空树（spec §2.3，Codex F1）。getInfo 同样经 provider 真实查 DB。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends

from admin_platform.api.v1.rbac_schemas import UserInfoResponse, UserInfoUser
from admin_platform.authz.permissions import SUPER_ADMIN_WILDCARD
from admin_platform.authz.providers import MenuProvider, PermissionProvider
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import AUTH_ACCOUNT_DISABLED, AppError, ProblemDetail
from admin_platform.core.permissions import get_menu_provider, get_permission_provider
from admin_platform.domains.menu.routers import RouterVO, build_routers
from admin_platform.domains.user.deps import get_user_service
from admin_platform.domains.user.service import UserService

router = APIRouter(tags=["rbac"])

CurrentUserDep = Annotated[CurrentUser, Depends(require_current_user)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
_AUTH_ERRORS: dict[int | str, dict[str, object]] = {401: {"model": ProblemDetail}}
_AUTH_ERRORS_WITH_403: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
}

# 超管展示角色（§2.4）：合成固定 code，避免前端因 DB 角色缺失而漂移。
_SUPER_ADMIN_ROLE = "superadmin"


@router.get(
    "/api/v1/auth/user-info",
    operation_id="auth_user_info",
    response_model=UserInfoResponse,
    responses=_AUTH_ERRORS_WITH_403,
)
async def get_info(
    current: CurrentUserDep,
    svc: UserServiceDep,
    provider: Annotated[PermissionProvider, Depends(get_permission_provider)],
) -> UserInfoResponse:
    """getInfo（§6.1）：当前用户 + 角色 code + 权限标识。超管合成 ["superadmin"] / ["*:*:*"]。

    账号状态校验（spec §2.3 不绕账号状态，与 require_permission / getRouters 同口径）：停用账号
    即使持有效 token 也 403 ACCOUNT_DISABLED，不下发任何角色/权限（否则前端凭旧 token 仍显示
    已撤权的菜单/按钮）。
    """
    user_id = int(current.user_id)
    if not await provider.a_get_is_active(user_id):
        raise AppError(
            code=AUTH_ACCOUNT_DISABLED,
            title="Account disabled",
            detail="账号已停用",
            status_code=int(HTTPStatus.FORBIDDEN),
        )
    user = await svc.get(user_id)  # 看自己永远可见（无 scope）
    if await provider.a_get_is_super_admin(user_id):
        roles = [_SUPER_ADMIN_ROLE]
        permissions = [SUPER_ADMIN_WILDCARD]
    else:
        roles = sorted(await provider.a_get_user_role_codes(user_id))
        permissions = sorted(await provider.a_get_user_permissions(user_id))
    return UserInfoResponse(
        user=UserInfoUser.model_validate(user),
        roles=roles,
        permissions=permissions,
    )


@router.get(
    "/api/v1/menus/routers",
    operation_id="menus_routers",
    response_model=list[RouterVO],
    responses=_AUTH_ERRORS,
)
async def get_routers(
    current: CurrentUserDep,
    provider: Annotated[MenuProvider, Depends(get_menu_provider)],
) -> list[RouterVO]:
    """getRouters（§6.1）：用户可见菜单树 → 若依 RouterVO payload。停用账号返回空树（provider 内）。"""
    tree = await provider.a_get_user_menu_tree(int(current.user_id))
    return build_routers(tree)
