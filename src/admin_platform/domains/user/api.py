"""Users HTTP API —— /api/v1/users 下的 CRUD 路由。

鉴权 + 授权（spec §3.2 默认 deny，Codex 深审 F2 补齐）：非公开路径 AuthMiddleware 强制
有效 token；每个端点再用 ``require_permission`` 守卫显式声明所需权限点（对标若依
``system:user:{action}``）。超管短路 + 账号停用校验在依赖内（spec §2.3）。守卫即基础设施层
依赖（类似 ``require_current_user``），不破坏分层契约。

错误路径在 ``responses=`` 声明，SDK 生成器据此 emit 类型化错误类（ADR §1）：
  * 401 auth.TOKEN_INVALID                —— 未携带 / 无效 token
  * 403 auth.FORBIDDEN_BY_ROLE            —— 缺少所需权限点
  * 404 user.NOT_FOUND                    —— get/update/delete 命中不存在的 id
  * 409 user.USERNAME_DUPLICATE           —— create 想用已存在 username
  * 409 user.LAST_SUPER_ADMIN             —— update 停用 / delete 最后一个超管（M12 补声明）
  * 422 framework.VALIDATION_FAILED       —— Pydantic 拒绝 payload
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from admin_platform.authz.permissions import Permissions
from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import ProblemDetail
from admin_platform.core.idempotency import idempotent
from admin_platform.core.permissions import require_permission
from admin_platform.core.rbac_audit import audited_write
from admin_platform.domains.user.deps import get_user_service
from admin_platform.domains.user.schemas import (
    UserCreate,
    UserListQuery,
    UserPage,
    UserRead,
    UserUpdate,
)
from admin_platform.domains.user.service import UserService

router = APIRouter(prefix="/api/v1/users", tags=["users"])

ServiceDep = Annotated[UserService, Depends(get_user_service)]

# 权限守卫（默认 deny + 超管短路）。对标若依 system:user:{action}：list/query/add/edit/remove。
ListGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_USER_LIST))]
QueryGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_USER_QUERY))]
AddGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_USER_ADD))]
EditGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_USER_EDIT))]
RemoveGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_USER_REMOVE))]

# 受守卫端点都可能返回 401（未登录）/ 403（缺权限）—— 声明进 OpenAPI。
AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
}
# 列表端点叠加 422：order_by 非 allowlist 字段 → framework.SORT_FIELD_INVALID（防注入拒绝）。
LIST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    422: {"model": ProblemDetail},
}
NOT_FOUND_RESPONSE: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
PATCH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},  # M12：停用最后一个超管 / dept_id 关联冲突 → 409
    422: {"model": ProblemDetail},
}
DELETE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},  # M12：删最后一个超管 → 409 LAST_SUPER_ADMIN
}
POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    400: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}


@router.get("", operation_id="users_list", response_model=UserPage, responses=LIST_ERROR_RESPONSES)
async def list_users(
    svc: ServiceDep,
    user: ListGuard,
    query: Annotated[UserListQuery, Query()],
) -> UserPage:
    # page/size 折进 UserListQuery（query-model 与独立标量 page/size Query 并存时，标量令整个
    # model 形参无法从 query 填充，canonical 请求报 422「该模型参数 missing」——与 extra 策略无关，
    # query-model 实测并不 forbid 额外参数）；折进后仍以 query 参数形式暴露在 OpenAPI。
    # 非超管按 data_scope 过滤可见用户（用户按所属部门可见）；超管 data_scope=ALL 不过滤。
    # 过滤 / 排序 AND 叠加在 data_scope 之上（service+repository），不绕过数据权限。
    return await svc.list_(query, page=query.page, size=query.size, scope=user.data_scope)


@router.get(
    "/{user_id}",
    operation_id="users_get",
    response_model=UserRead,
    responses=NOT_FOUND_RESPONSE,
)
async def get_user(user_id: int, svc: ServiceDep, user: QueryGuard) -> UserRead:
    return await svc.get(user_id, scope=user.data_scope)


@router.post(
    "",
    operation_id="users_create",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    responses=POST_ERROR_RESPONSES,
)
@idempotent
async def create_user(payload: UserCreate, svc: ServiceDep, user: AddGuard) -> UserRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_USER_ADD,
        "user",
        coro=svc.create(payload, scope=user.data_scope),
        display=lambda u: u.username,
        success_status=201,
    )


@router.patch(
    "/{user_id}",
    operation_id="users_update",
    response_model=UserRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_user(
    user_id: int, payload: UserUpdate, svc: ServiceDep, user: EditGuard
) -> UserRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_USER_EDIT,
        "user",
        coro=svc.update(user_id, payload, scope=user.data_scope),
        target_id=user_id,
        display=lambda u: u.username,
    )


@router.delete(
    "/{user_id}",
    operation_id="users_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DELETE_ERROR_RESPONSES,
)
async def delete_user(user_id: int, svc: ServiceDep, user: RemoveGuard) -> None:
    await audited_write(
        user,
        Permissions.SYSTEM_USER_REMOVE,
        "user",
        coro=svc.delete(user_id, scope=user.data_scope),
        target_id=user_id,
    )
