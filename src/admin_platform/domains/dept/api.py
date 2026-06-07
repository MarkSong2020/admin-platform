"""Depts HTTP API —— /api/v1/depts 下的 CRUD 路由。

鉴权 + 授权（spec §3.2 默认 deny）：每个端点用 ``require_permission`` 守卫显式声明所需
权限点（对标若依 ``system:dept:{action}``）。超管短路在依赖内最前（spec §2.3）。守卫即
基础设施层依赖（类似 ``require_current_user``），不破坏分层契约。

错误路径在 ``responses=`` 声明，SDK 生成器据此 emit 类型化错误类（ADR §1）：
  * 401 auth.TOKEN_INVALID         —— 未携带 / 无效 token
  * 403 auth.FORBIDDEN_BY_ROLE     —— 缺少所需权限点
  * 404 dept.NOT_FOUND             —— get/update/delete 命中不存在的 id
  * 409 dept.CODE_DUPLICATE        —— create/update 想用已存在 code
  * 409 dept.CYCLE                 —— update 把部门移到自身或其子孙之下
  * 409 dept.HAS_CHILDREN          —— delete 有子部门的部门
  * 422 framework.VALIDATION_FAILED —— Pydantic 拒绝 payload
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import ProblemDetail
from admin_platform.core.idempotency import idempotent
from admin_platform.core.permissions import require_permission
from admin_platform.domains.dept.deps import get_dept_service
from admin_platform.domains.dept.schemas import (
    DeptCreate,
    DeptPage,
    DeptRead,
    DeptUpdate,
)
from admin_platform.domains.dept.service import DeptService

router = APIRouter(prefix="/api/v1/depts", tags=["depts"])

ServiceDep = Annotated[DeptService, Depends(get_dept_service)]
PageQ = Annotated[int, Query(ge=1, description="页码（从 1 开始）")]
SizeQ = Annotated[int, Query(ge=1, le=100, description="每页条数（上限 100）")]

# 权限守卫（默认 deny + 超管短路）。对标若依 system:dept:{action}：list/query/add/edit/remove。
ListGuard = Annotated[CurrentUser, Depends(require_permission("system:dept:list"))]
QueryGuard = Annotated[CurrentUser, Depends(require_permission("system:dept:query"))]
AddGuard = Annotated[CurrentUser, Depends(require_permission("system:dept:add"))]
EditGuard = Annotated[CurrentUser, Depends(require_permission("system:dept:edit"))]
RemoveGuard = Annotated[CurrentUser, Depends(require_permission("system:dept:remove"))]

# 受守卫端点都可能返回 401（未登录）/ 403（缺权限）—— 声明进 OpenAPI。
AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
}
GET_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
# PATCH：404（不存在）+ 409（code 重复 / 移动成环）+ 422（校验）。
PATCH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}
# DELETE：404（不存在）+ 409（有子部门 RESTRICT）。
DELETE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
}
# v0.4.9+ IdempotencyMiddleware 在 middleware 层就会拒绝以下 POST 情况：
#   400 framework.IDEMPOTENCY_KEY_INVALID        （key 超过 255 字符）
#   409 framework.IDEMPOTENT_RETRY_IN_FLIGHT     （同 key+body 仍在运行）
#   422 framework.IDEMPOTENCY_KEY_REUSED         （同 key 但 body 不同）
# 叠加业务 409 dept.CODE_DUPLICATE（code 重复）。FastAPI 看不到这些状态码，
# 所以 generator 必须在 ``responses=`` 显式声明，否则 SDK 漏掉这些错误路径。
IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    400: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}


@router.get("", operation_id="depts_list", response_model=DeptPage, responses=AUTH_ERROR_RESPONSES)
async def list_depts(
    svc: ServiceDep, _user: ListGuard, page: PageQ = 1, size: SizeQ = 20
) -> DeptPage:
    return await svc.list_(page=page, size=size)


@router.get(
    "/{item_id}",
    operation_id="depts_get",
    response_model=DeptRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_dept(item_id: int, svc: ServiceDep, _user: QueryGuard) -> DeptRead:
    return await svc.get(item_id)


# ADR §11：POST 默认幂等 —— 调用方可以用同一个 Idempotency-Key header 安全
# 重试。装饰器顺序 —— ``@idempotent`` 必须放**最内层**（紧贴 ``async def``），
# 它是 marker（返回原函数、保留签名）；外层守卫 / wrapper 在它之上。详见
# ``core/idempotency.py`` 的 ``idempotent`` docstring；``tests/unit/test_idempotency.py`` 守门。
@router.post(
    "",
    operation_id="depts_create",
    response_model=DeptRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_dept(payload: DeptCreate, svc: ServiceDep, _user: AddGuard) -> DeptRead:
    return await svc.create(payload)


@router.patch(
    "/{item_id}",
    operation_id="depts_update",
    response_model=DeptRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_dept(
    item_id: int, payload: DeptUpdate, svc: ServiceDep, _user: EditGuard
) -> DeptRead:
    return await svc.update(item_id, payload)


@router.delete(
    "/{item_id}",
    operation_id="depts_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DELETE_ERROR_RESPONSES,
)
async def delete_dept(item_id: int, svc: ServiceDep, _user: RemoveGuard) -> None:
    await svc.delete(item_id)
