"""Posts HTTP API —— /api/v1/posts 下的 CRUD 路由。

鉴权 + 授权（spec §3.2 默认 deny）：每个端点用 ``require_permission`` 守卫显式声明所需
权限点（对标若依 ``system:post:{action}``）。超管短路在依赖内最前（spec §2.3）。守卫即
基础设施层依赖（类似 ``require_current_user``），不破坏分层契约。

错误路径在 ``responses=`` 声明，SDK 生成器据此 emit 类型化错误类（ADR §1）：
  * 401 auth.TOKEN_INVALID         —— 未携带 / 无效 token
  * 403 auth.FORBIDDEN_BY_ROLE     —— 缺少所需权限点
  * 404 post.NOT_FOUND             —— get/update/delete 命中不存在的 id
  * 409 post.CODE_DUPLICATE        —— create/update 想用已存在 code
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
from admin_platform.domains.post.deps import get_post_service
from admin_platform.domains.post.schemas import (
    PostCreate,
    PostPage,
    PostRead,
    PostUpdate,
)
from admin_platform.domains.post.service import PostService

router = APIRouter(prefix="/api/v1/posts", tags=["posts"])

ServiceDep = Annotated[PostService, Depends(get_post_service)]
PageQ = Annotated[int, Query(ge=1, description="页码（从 1 开始）")]
SizeQ = Annotated[int, Query(ge=1, le=100, description="每页条数（上限 100）")]

# 权限守卫（默认 deny + 超管短路）。对标若依 system:post:{action}：list/query/add/edit/remove。
ListGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_LIST))]
QueryGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_QUERY))]
AddGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_ADD))]
EditGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_EDIT))]
RemoveGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_POST_REMOVE))]

# 受守卫端点都可能返回 401（未登录）/ 403（缺权限）—— 声明进 OpenAPI。
AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
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
# 叠加业务 409 post.CODE_DUPLICATE（code 重复）。FastAPI 看不到这些状态码，
# 所以 generator 必须在 ``responses=`` 显式声明，否则 SDK 漏掉这些错误路径。
IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    400: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}


@router.get("", operation_id="posts_list", response_model=PostPage, responses=AUTH_ERROR_RESPONSES)
async def list_posts(
    svc: ServiceDep, _user: ListGuard, page: PageQ = 1, size: SizeQ = 20
) -> PostPage:
    return await svc.list_(page=page, size=size)


@router.get(
    "/{item_id}",
    operation_id="posts_get",
    response_model=PostRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_post(item_id: int, svc: ServiceDep, _user: QueryGuard) -> PostRead:
    return await svc.get(item_id)


# ADR §11：POST 默认幂等 —— 调用方可以用同一个 Idempotency-Key header 安全重试。
# 装饰器顺序 —— ``@idempotent`` 必须放**最内层**（紧贴 ``async def``），它是 marker；
# 外层守卫在它之上。详见 ``core/idempotency.py``；``tests/unit/test_idempotency.py`` 守门。
@router.post(
    "",
    operation_id="posts_create",
    response_model=PostRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_post(payload: PostCreate, svc: ServiceDep, user: AddGuard) -> PostRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_POST_ADD,
        "post",
        coro=svc.create(payload),
        display=lambda p: p.code,
        success_status=201,
    )


@router.patch(
    "/{item_id}",
    operation_id="posts_update",
    response_model=PostRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_post(
    item_id: int, payload: PostUpdate, svc: ServiceDep, user: EditGuard
) -> PostRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_POST_EDIT,
        "post",
        coro=svc.update(item_id, payload),
        target_id=item_id,
        display=lambda p: p.code,
    )


@router.delete(
    "/{item_id}",
    operation_id="posts_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DELETE_ERROR_RESPONSES,
)
async def delete_post(item_id: int, svc: ServiceDep, user: RemoveGuard) -> None:
    await audited_write(
        user,
        Permissions.SYSTEM_POST_REMOVE,
        "post",
        coro=svc.delete(item_id),
        target_id=item_id,
    )
