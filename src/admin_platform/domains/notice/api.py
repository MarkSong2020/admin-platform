"""Notices HTTP API —— /api/v1/notices 下的 CRUD 路由。

鉴权 + 授权（spec §3.2 默认 deny）：每个端点用 ``require_permission`` 守卫声明所需权限点
（对标若依 ``system:notice:{action}``）。写操作经 ``audited_write`` 织入 rbac_write 审计。

错误路径在 ``responses=`` 声明（ADR §1）：
  * 401 auth.TOKEN_INVALID         —— 未携带 / 无效 token
  * 403 auth.FORBIDDEN_BY_ROLE     —— 缺少所需权限点
  * 404 notice.NOT_FOUND           —— get/update/delete 命中不存在的 id
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
from admin_platform.domains.notice.deps import get_notice_service
from admin_platform.domains.notice.schemas import (
    NoticeCreate,
    NoticePage,
    NoticeRead,
    NoticeType,
    NoticeUpdate,
    StatusValue,
)
from admin_platform.domains.notice.service import NoticeService

router = APIRouter(prefix="/api/v1/notices", tags=["notices"])

ServiceDep = Annotated[NoticeService, Depends(get_notice_service)]
PageQ = Annotated[int, Query(ge=1, description="页码（从 1 开始）")]
SizeQ = Annotated[int, Query(ge=1, le=100, description="每页条数（上限 100）")]
# 过滤参数用 Literal（对抗审查建议）：非法值 → 422 而非静默返回空，暴露调用方 typo。
# status 参数走 alias（函数形参名 status_filter 避让 ``from fastapi import status``，
# 但对外暴露名仍是 ``status``，对抗审查 S4——否则 ?status= 过滤实质失效）。
TypeQ = Annotated[NoticeType | None, Query(description="按公告类型过滤(notification/announcement)")]
StatusQ = Annotated[
    StatusValue | None, Query(alias="status", description="按状态过滤(active/disabled)")
]

# 权限守卫（默认 deny + 超管短路）。对标若依 system:notice:{action}。
ListGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_NOTICE_LIST))]
QueryGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_NOTICE_QUERY))]
AddGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_NOTICE_ADD))]
EditGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_NOTICE_EDIT))]
RemoveGuard = Annotated[CurrentUser, Depends(require_permission(Permissions.SYSTEM_NOTICE_REMOVE))]

AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
}
GET_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
PATCH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}
DELETE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    404: {"model": ProblemDetail},
}
# IdempotencyMiddleware 在 middleware 层拒绝的 POST 情况（400/409/422，FastAPI 看不到）。
IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **AUTH_ERROR_RESPONSES,
    400: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}


@router.get(
    "", operation_id="notices_list", response_model=NoticePage, responses=AUTH_ERROR_RESPONSES
)
async def list_notices(
    svc: ServiceDep,
    _user: ListGuard,
    notice_type: TypeQ = None,
    status_filter: StatusQ = None,
    page: PageQ = 1,
    size: SizeQ = 20,
) -> NoticePage:
    return await svc.list_(notice_type=notice_type, status=status_filter, page=page, size=size)


@router.get(
    "/{item_id}",
    operation_id="notices_get",
    response_model=NoticeRead,
    responses=GET_ERROR_RESPONSES,
)
async def get_notice(item_id: int, svc: ServiceDep, _user: QueryGuard) -> NoticeRead:
    return await svc.get(item_id)


@router.post(
    "",
    operation_id="notices_create",
    response_model=NoticeRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_notice(payload: NoticeCreate, svc: ServiceDep, user: AddGuard) -> NoticeRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_NOTICE_ADD,
        "notice",
        coro=svc.create(payload),
        display=lambda n: n.title,
        success_status=201,
    )


@router.patch(
    "/{item_id}",
    operation_id="notices_update",
    response_model=NoticeRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_notice(
    item_id: int, payload: NoticeUpdate, svc: ServiceDep, user: EditGuard
) -> NoticeRead:
    return await audited_write(
        user,
        Permissions.SYSTEM_NOTICE_EDIT,
        "notice",
        coro=svc.update(item_id, payload),
        target_id=item_id,
        display=lambda n: n.title,
    )


@router.delete(
    "/{item_id}",
    operation_id="notices_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=DELETE_ERROR_RESPONSES,
)
async def delete_notice(item_id: int, svc: ServiceDep, user: RemoveGuard) -> None:
    await audited_write(
        user,
        Permissions.SYSTEM_NOTICE_REMOVE,
        "notice",
        coro=svc.delete(item_id),
        target_id=item_id,
    )
