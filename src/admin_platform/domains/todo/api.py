"""Todos HTTP API — /api/v1/todos 下的 CRUD 路由。

教科书蓝本路由。注意每条错误路径都在 ``responses=`` 里声明，SDK 生成器
就能据此 emit 类型化的错误类（ADR §1）：

  * 404 TODO_NOT_FOUND       — get/update/delete 命中不存在 id
  * 409 TODO_TITLE_DUPLICATE — create/update 想用已存在 title
  * 422 VALIDATION_FAILED    — Pydantic schema 拒绝 payload
  * 422 TODO_TAG_NOT_FOUND   — tag_ids 含不存在 id（v0.5.1）
  * 400/409/422 framework.IDEMPOTENCY_* — middleware 在 POST 上的拒绝

每条路径的「为何」详见 ``doc/architecture/EXAMPLE_DOMAIN.md``。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.core.errors import ProblemDetail
from admin_platform.core.idempotency import idempotent
from admin_platform.db.session import get_session
from admin_platform.domains.tag.repository import TagRepository
from admin_platform.domains.todo.repository import TodoRepository
from admin_platform.domains.todo.schemas import TodoCreate, TodoPage, TodoRead, TodoUpdate
from admin_platform.domains.todo.service import TodoService

router = APIRouter(prefix="/api/v1/todos", tags=["todos"])


async def _get_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TodoService:
    # v0.5.1 — TodoService 现在需要 TagRepository 做 tag 关联管理。两个 repo
    # 共享同一 AsyncSession，所有写操作落在同一请求事务内（不会出现跨
    # domain 部分提交）。
    return TodoService(TodoRepository(session), TagRepository(session))


ServiceDep = Annotated[TodoService, Depends(_get_service)]
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


@router.get("", operation_id="todos_list", response_model=TodoPage)
async def list_todos(svc: ServiceDep, page: PageQ = 1, size: SizeQ = 20) -> TodoPage:
    return await svc.list_(page=page, size=size)


@router.get(
    "/{item_id}",
    operation_id="todos_get",
    response_model=TodoRead,
    responses=NOT_FOUND_RESPONSE,
)
async def get_todo(item_id: int, svc: ServiceDep) -> TodoRead:
    return await svc.get(item_id)


# ADR §11：POST 默认幂等。装饰器顺序 —— ``@idempotent`` 必须放**最内层**
# （紧贴 ``async def``）；详细原因看 core/idempotency.py（涉及
# functools.wraps 在某些写法下的相互作用）。
@router.post(
    "",
    operation_id="todos_create",
    response_model=TodoRead,
    status_code=status.HTTP_201_CREATED,
    responses=IDEMPOTENT_POST_ERROR_RESPONSES,
)
@idempotent
async def create_todo(payload: TodoCreate, svc: ServiceDep) -> TodoRead:
    return await svc.create(payload)


@router.patch(
    "/{item_id}",
    operation_id="todos_update",
    response_model=TodoRead,
    responses=PATCH_ERROR_RESPONSES,
)
async def update_todo(item_id: int, payload: TodoUpdate, svc: ServiceDep) -> TodoRead:
    return await svc.update(item_id, payload)


@router.delete(
    "/{item_id}",
    operation_id="todos_delete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND_RESPONSE,
)
async def delete_todo(item_id: int, svc: ServiceDep) -> None:
    await svc.delete(item_id)
