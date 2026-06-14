"""Roles HTTP API —— /api/v1/roles 下的 CRUD 路由。

鉴权 + 授权（spec §3.2 默认 deny）：每个端点用 ``require_permission`` 守卫显式声明所需
权限点（对标若依 ``system:role:{action}``）。超管短路在依赖内最前（spec §2.3）。守卫即
基础设施层依赖（类似 ``require_current_user``），不破坏分层契约。

错误路径在 ``responses=`` 声明，SDK 生成器据此 emit 类型化错误类（ADR §1）：
  * 401 auth.TOKEN_INVALID         —— 未携带 / 无效 token
  * 403 auth.FORBIDDEN_BY_ROLE     —— 缺少所需权限点
  * 404 role.NOT_FOUND             —— get/update/delete 命中不存在的 id
  * 409 role.CODE_DUPLICATE        —— create/update 想用已存在 code
  * 422 framework.VALIDATION_FAILED —— Pydantic 拒绝 payload
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
from admin_platform.domains.role.deps import get_role_service
from admin_platform.domains.role.schemas import (
    RoleCreate,
    RoleListQuery,
    RolePage,
    RoleRead,
    RoleUpdate,
)
from admin_platform.domains.role.service import RoleService

router = APIRouter(prefix="/api/v1/roles", tags=["roles"])

ServiceDep = Annotated[RoleService, Depends(get_role_service)]

# 权限守卫（默认 deny + 超管短路）。对标若依 system:role:{action}：list/query/add/edit/remove。
ListGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_ROLE_LIST))]
QueryGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_ROLE_QUERY))]
AddGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_ROLE_ADD))]
EditGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_ROLE_EDIT))]
RemoveGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_ROLE_REMOVE))]

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
GET_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
# PATCH：404（不存在）+ 409（code 重复）+ 422（校验）。
PATCH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}
# DELETE：404（不存在）。
DELETE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
# v0.4.9+ IdempotencyMiddleware 在 middleware 层就会拒绝以下 POST 情况：
#   400 framework.IDEMPOTENCY_KEY_INVALID        （key 超过 255 字符）
#   409 framework.IDEMPOTENT_RETRY_IN_FLIGHT     （同 key+body 仍在运行）
#   422 framework.IDEMPOTENCY_KEY_REUSED         （同 key 但 body 不同）
# 叠加业务 409 role.CODE_DUPLICATE（code 重复）。FastAPI 看不到这些状态码，
# 所以 generator 必须在 ``responses=`` 显式声明，否则 SDK 漏掉这些错误路径。
IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    400: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}


@router.get("", operation_id="roles_list", response_model=RolePage, responses=LIST_ERROR_RESPONSES)
async def list_roles(
    svc: ServiceDep,
    _user: ListGuard,
    query: Annotated[RoleListQuery, Query()],
) -> RolePage:
    # page/size 折进 RoleListQuery（query-model 与独立标量 page/size Query 并存时，标量令整个
    # model 形参无法从 query 填充，canonical 请求报 422「该模型参数 missing」——与 extra 策略无关，
    # query-model 实测并不 forbid 额外参数）；折进后仍以 query 参数形式暴露在 OpenAPI。
    return await svc.list_(query, page=query.page, size=query.size)


@router.get(
    "/{item_id}",
    operation_id="roles_get",
    response_model=RoleRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_role(item_id: int, svc: ServiceDep, _user: QueryGuard) -> RoleRead:
    return await svc.get(item_id)


# ADR §11：POST 默认幂等 —— 调用方可以用同一个 Idempotency-Key header 安全重试。
# 装饰器顺序 —— ``@idempotent`` 必须放**最内层**（紧贴 ``async def``），它是 marker；
# 外层守卫在它之上。详见 ``core/idempotency.py``；``tests/unit/test_idempotency.py`` 守门。
@router.post(
    "",
    operation_id="roles_create",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_role(payload: RoleCreate, svc: ServiceDep, user: AddGuard) -> RoleRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_ROLE_ADD,
        "role",
        coro=svc.create(payload, is_super_admin=user.is_super_admin),
        display=lambda r: r.code,
        success_status=201,
    )


@router.patch(
    "/{item_id}",
    operation_id="roles_update",
    response_model=RoleRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_role(
    item_id: int, payload: RoleUpdate, svc: ServiceDep, user: EditGuard
) -> RoleRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_ROLE_EDIT,
        "role",
        coro=svc.update(item_id, payload, is_super_admin=user.is_super_admin),
        target_id=item_id,
        display=lambda r: r.code,
    )


@router.delete(
    "/{item_id}",
    operation_id="roles_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DELETE_ERROR_RESPONSES,
)
async def delete_role(item_id: int, svc: ServiceDep, user: RemoveGuard) -> None:
    await audited_write(
        user,
        Permissions.SYSTEM_ROLE_REMOVE,
        "role",
        coro=svc.delete(item_id),
        target_id=item_id,
    )
