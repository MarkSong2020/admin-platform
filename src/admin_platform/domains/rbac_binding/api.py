"""RBAC 绑定 HTTP API —— 子资源 PUT（全量替换）+ GET（回显），挂在 /api/v1 下。

路由形如 ``/users/{id}/roles`` / ``/roles/{id}/menus``。权限点复用资源 edit/query
（decision-log 2026-06-09 §2：不新增 assign 分权，避免 registry 扩张）。actor 由 ``CurrentUser``
构造 ``AuditActor`` 传入 service（不破坏分层：service 不碰 fastapi/CurrentUser）。

错误路径（``responses=``，SDK 生成器据此 emit 类型化错误）：
  * 401 auth.TOKEN_INVALID / 403 auth.FORBIDDEN_BY_ROLE —— 鉴权 / 权限点
  * 404 {user,role}.NOT_FOUND —— 主体不存在 / 数据范围不可见
  * 422 *.<X>_IDS_INVALID —— 绑定 id 集合存在性校验失败（all-or-nothing）
  * 403 auth.FORBIDDEN_BY_SCOPE —— role-dept 绑定不可见部门（数据权限写侧）
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from admin_platform.audit.events import AuditActor
from admin_platform.authz.permissions import Permissions
from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import ProblemDetail
from admin_platform.core.permissions import require_permission
from admin_platform.domains.rbac_binding.deps import get_rbac_binding_service
from admin_platform.domains.rbac_binding.schemas import (
    BindingRead,
    RoleDeptsBinding,
    RoleMenusBinding,
    UserPostsBinding,
    UserRolesBinding,
)
from admin_platform.domains.rbac_binding.service import RbacBindingService

router = APIRouter(prefix="/api/v1", tags=["rbac-binding"])

ServiceDep = Annotated[RbacBindingService, Depends(get_rbac_binding_service)]
UserEditGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_USER_EDIT))]
UserQueryGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_USER_QUERY))]
RoleEditGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_ROLE_EDIT))]
RoleQueryGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_ROLE_QUERY))]

AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
}
PUT_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}
GET_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}


def _actor(user: CurrentUser) -> AuditActor:
    """从 CurrentUser 构造审计 actor（user_id 在 JWT sub 里为 str，审计模型用 int）。"""
    return AuditActor(user_id=int(user.user_id), is_super_admin=user.is_super_admin)


# ---- user-role ----------------------------------------------------------------


@router.put(
    "/users/{user_id}/roles",
    operation_id="bind_user_roles",
    response_model=BindingRead,
    responses=PUT_ERROR_RESPONSES,
)
async def bind_user_roles(
    user_id: int, payload: UserRolesBinding, svc: ServiceDep, user: UserEditGuard
) -> BindingRead:
    ids = await svc.set_user_roles(
        user_id, payload.role_ids, operator=_actor(user), scope=user.data_scope
    )
    return BindingRead(ids=ids)


@router.get(
    "/users/{user_id}/roles",
    operation_id="get_user_roles_binding",
    response_model=BindingRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_user_roles(user_id: int, svc: ServiceDep, user: UserQueryGuard) -> BindingRead:
    return BindingRead(ids=await svc.get_user_roles(user_id, scope=user.data_scope))


# ---- user-post ----------------------------------------------------------------


@router.put(
    "/users/{user_id}/posts",
    operation_id="bind_user_posts",
    response_model=BindingRead,
    responses=PUT_ERROR_RESPONSES,
)
async def bind_user_posts(
    user_id: int, payload: UserPostsBinding, svc: ServiceDep, user: UserEditGuard
) -> BindingRead:
    ids = await svc.set_user_posts(
        user_id, payload.post_ids, operator=_actor(user), scope=user.data_scope
    )
    return BindingRead(ids=ids)


@router.get(
    "/users/{user_id}/posts",
    operation_id="get_user_posts_binding",
    response_model=BindingRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_user_posts(user_id: int, svc: ServiceDep, user: UserQueryGuard) -> BindingRead:
    return BindingRead(ids=await svc.get_user_posts(user_id, scope=user.data_scope))


# ---- role-menu ----------------------------------------------------------------


@router.put(
    "/roles/{role_id}/menus",
    operation_id="bind_role_menus",
    response_model=BindingRead,
    responses=PUT_ERROR_RESPONSES,
)
async def bind_role_menus(
    role_id: int, payload: RoleMenusBinding, svc: ServiceDep, user: RoleEditGuard
) -> BindingRead:
    ids = await svc.set_role_menus(role_id, payload.menu_ids, operator=_actor(user))
    return BindingRead(ids=ids)


@router.get(
    "/roles/{role_id}/menus",
    operation_id="get_role_menus_binding",
    response_model=BindingRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_role_menus(role_id: int, svc: ServiceDep, _user: RoleQueryGuard) -> BindingRead:
    return BindingRead(ids=await svc.get_role_menus(role_id))


# ---- role-dept ----------------------------------------------------------------


@router.put(
    "/roles/{role_id}/depts",
    operation_id="bind_role_depts",
    response_model=BindingRead,
    responses=PUT_ERROR_RESPONSES,
)
async def bind_role_depts(
    role_id: int, payload: RoleDeptsBinding, svc: ServiceDep, user: RoleEditGuard
) -> BindingRead:
    ids = await svc.set_role_depts(
        role_id, payload.dept_ids, operator=_actor(user), scope=user.data_scope
    )
    return BindingRead(ids=ids)


@router.get(
    "/roles/{role_id}/depts",
    operation_id="get_role_depts_binding",
    response_model=BindingRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_role_depts(role_id: int, svc: ServiceDep, _user: RoleQueryGuard) -> BindingRead:
    return BindingRead(ids=await svc.get_role_depts(role_id))
