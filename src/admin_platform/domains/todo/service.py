"""Todo service — 业务用例层。

事务边界由 ``get_session`` 拥有（一请求 = 一事务）。service 决定**何时**
raise（触发请求事务回滚），也可以用 ``session.begin_nested()`` 开
SAVEPOINT 做 saga 流程里的部分提交。

本层强制的业务不变式（把「数据存储操作」翻译成「用例」的关键）：

  * **title 唯一性** — 在 repo.create / repo.update **之前**检查，违反则抛
    ``admin_platform.TODO_TITLE_DUPLICATE``（409）。DB UniqueConstraint 是
    竞态兜底；service 层的预检让调用方拿到干净的领域错误码，而不是泄露
    的 ``IntegrityError``。
  * **tag id 存在性（v0.5.1）** — 传了 ``tag_ids`` 时所有 id 必须解析到
    现存的 Tag 行。部分缺失 ⇒ 422 ``admin_platform.TODO_TAG_NOT_FOUND``。
    走 all-or-nothing 语义，避免「调用方传 3 个、悄悄关联 2 个」的丢失。

**跨 domain 依赖说明**：TodoService 持有 ``TagRepository``（而非
``TagService``），因为关联管理是 Tag-存储形状的关切，不是 Tag-业务规则
的关切。service 不调用其它 service —— 只持有对方 domain 的 repository，
保持依赖方向无环。
"""

from __future__ import annotations

from admin_platform.core.errors import AppError
from admin_platform.domains.tag.repository import TagRepository
from admin_platform.domains.todo.repository import TodoRepository
from admin_platform.domains.todo.schemas import TodoCreate, TodoPage, TodoRead, TodoUpdate

NOT_FOUND_CODE = "admin_platform.TODO_NOT_FOUND"
TITLE_DUPLICATE_CODE = "admin_platform.TODO_TITLE_DUPLICATE"
TAG_NOT_FOUND_CODE = "admin_platform.TODO_TAG_NOT_FOUND"


class TodoService:
    def __init__(self, repository: TodoRepository, tag_repository: TagRepository) -> None:
        self._repo = repository
        self._tag_repo = tag_repository

    async def list_(self, *, page: int, size: int) -> TodoPage:
        rows = await self._repo.list_paginated(page, size)
        total = await self._repo.count()
        total_pages = (total + size - 1) // size if size > 0 else 0
        return TodoPage(
            items=[TodoRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=total_pages,
        )

    async def get(self, item_id: int) -> TodoRead:
        row = await self._repo.get(item_id)
        if row is None:
            raise self._not_found(item_id)
        return TodoRead.model_validate(row)

    async def create(self, payload: TodoCreate) -> TodoRead:
        if await self._repo.find_by_title(payload.title) is not None:
            raise AppError(
                code=TITLE_DUPLICATE_CODE,
                title="Todo title already exists",
                detail=f"title={payload.title!r}",
                status_code=409,
            )
        tags = await self._resolve_tags(payload.tag_ids)
        row = await self._repo.create(payload, tags=tags)
        return TodoRead.model_validate(row)

    async def update(self, item_id: int, payload: TodoUpdate) -> TodoRead:
        if payload.title is not None:
            existing = await self._repo.find_by_title(payload.title)
            if existing is not None and existing.id != item_id:
                raise AppError(
                    code=TITLE_DUPLICATE_CODE,
                    title="Todo title already exists",
                    detail=f"title={payload.title!r}",
                    status_code=409,
                )
        tags = await self._resolve_tags(payload.tag_ids)
        row = await self._repo.update(item_id, payload, tags=tags)
        if row is None:
            raise self._not_found(item_id)
        return TodoRead.model_validate(row)

    async def delete(self, item_id: int) -> None:
        ok = await self._repo.delete(item_id)
        if not ok:
            raise self._not_found(item_id)

    async def _resolve_tags(self, tag_ids: list[int] | None) -> list | None:  # type: ignore[type-arg]
        """All-or-nothing 的 tag 解析。

        返回值：
          * ``None`` — 当 ``tag_ids`` 是 None 时，作为 repository 的 sentinel
            意思「保留现有关联不动」（PATCH 专用语义）
          * 空列表 — 当 ``tag_ids`` 是 ``[]`` 时，明确「清空所有 tag」
          * Tag ORM 列表 — 全量替换集合

        抛错：
          AppError 422 TODO_TAG_NOT_FOUND，当任一 id 不存在时。
        """
        if tag_ids is None:
            return None
        if not tag_ids:
            return []
        # 去重但保留调用方传入的顺序（人通常关心这个）。
        unique_ids = list(dict.fromkeys(tag_ids))
        tags = await self._tag_repo.get_many_by_ids(unique_ids)
        if len(tags) != len(unique_ids):
            found = {tag.id for tag in tags}
            missing = [i for i in unique_ids if i not in found]
            raise AppError(
                code=TAG_NOT_FOUND_CODE,
                title="One or more tag ids do not exist",
                detail=f"missing_tag_ids={missing}",
                status_code=422,
            )
        return tags

    @staticmethod
    def _not_found(item_id: int) -> AppError:
        return AppError(
            code=NOT_FOUND_CODE,
            title="Todo not found",
            detail=f"id={item_id}",
            status_code=404,
        )
