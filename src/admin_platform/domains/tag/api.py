"""Tags HTTP API — /api/v1/tags 下的 CRUD 路由。

第二个 example domain；``responses=`` 显式声明纪律与 todo 一致：
  * 404 TAG_NOT_FOUND       — get/update/delete 命中不存在 id
  * 409 TAG_NAME_DUPLICATE  — create/update 想用已存在 name
  * 422 VALIDATION_FAILED   — Pydantic schema 拒绝 payload
  * 400/409/422 framework.IDEMPOTENCY_* — middleware 在 POST 上的拒绝
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.core.errors import ProblemDetail
from admin_platform.core.idempotency import idempotent
from admin_platform.db.session import get_session
from admin_platform.domains.tag.repository import TagRepository
from admin_platform.domains.tag.schemas import TagCreate, TagPage, TagRead, TagUpdate
from admin_platform.domains.tag.service import TagService

router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


async def _get_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TagService:
    return TagService(TagRepository(session))


ServiceDep = Annotated[TagService, Depends(_get_service)]
PageQ = Annotated[int, Query(ge=1, description="页码（从 1 开始）")]
SizeQ = Annotated[int, Query(ge=1, le=100, description="每页条数（上限 100）")]
NOT_FOUND_RESPONSE: dict[int | str, dict[str, object]] = {404: {"model": ProblemDetail}}
PATCH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}
IDEMPOTENT_POST_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}


@router.get("", operation_id="tags_list", response_model=TagPage)
async def list_tags(svc: ServiceDep, page: PageQ = 1, size: SizeQ = 20) -> TagPage:
    return await svc.list_(page=page, size=size)


@router.get(
    "/{item_id}",
    operation_id="tags_get",
    response_model=TagRead,
    responses=NOT_FOUND_RESPONSE,
)
async def get_tag(item_id: int, svc: ServiceDep) -> TagRead:
    return await svc.get(item_id)


@router.post(
    "",
    operation_id="tags_create",
    response_model=TagRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_tag(payload: TagCreate, svc: ServiceDep) -> TagRead:
    return await svc.create(payload)


@router.patch(
    "/{item_id}",
    operation_id="tags_update",
    response_model=TagRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_tag(item_id: int, payload: TagUpdate, svc: ServiceDep) -> TagRead:
    return await svc.update(item_id, payload)


@router.delete(
    "/{item_id}",
    operation_id="tags_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND_RESPONSE,
)
async def delete_tag(item_id: int, svc: ServiceDep) -> None:
    await svc.delete(item_id)
