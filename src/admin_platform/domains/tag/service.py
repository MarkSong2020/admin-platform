"""Tag service — 业务用例层。

跟 todo 同一套模式（详见 ``doc/architecture/EXAMPLE_DOMAIN.md``）：
  * 缺 id ⇒ NOT_FOUND
  * insert / PATCH 前先做 NAME_DUPLICATE 预检（DB UniqueConstraint
    作为竞态兜底）

tag 在 todo↔tag 多对多关系中是「较简单的一方」。关联表（``todo_tags``）
的写入由 ``todo/service.py`` 负责，本 service 只管 tag 自身的生命周期，
不引入跨 domain 逻辑。
"""

from __future__ import annotations

from admin_platform.core.errors import AppError
from admin_platform.domains.tag.repository import TagRepository
from admin_platform.domains.tag.schemas import TagCreate, TagPage, TagRead, TagUpdate

NOT_FOUND_CODE = "admin_platform.TAG_NOT_FOUND"
NAME_DUPLICATE_CODE = "admin_platform.TAG_NAME_DUPLICATE"


class TagService:
    def __init__(self, repository: TagRepository) -> None:
        self._repo = repository

    async def list_(self, *, page: int, size: int) -> TagPage:
        rows = await self._repo.list_paginated(page, size)
        total = await self._repo.count()
        total_pages = (total + size - 1) // size if size > 0 else 0
        return TagPage(
            items=[TagRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=total_pages,
        )

    async def get(self, item_id: int) -> TagRead:
        row = await self._repo.get(item_id)
        if row is None:
            raise self._not_found(item_id)
        return TagRead.model_validate(row)

    async def create(self, payload: TagCreate) -> TagRead:
        if await self._repo.find_by_name(payload.name) is not None:
            raise AppError(
                code=NAME_DUPLICATE_CODE,
                title="Tag name already exists",
                detail=f"name={payload.name!r}",
                status_code=409,
            )
        row = await self._repo.create(payload)
        return TagRead.model_validate(row)

    async def update(self, item_id: int, payload: TagUpdate) -> TagRead:
        if payload.name is not None:
            existing = await self._repo.find_by_name(payload.name)
            if existing is not None and existing.id != item_id:
                raise AppError(
                    code=NAME_DUPLICATE_CODE,
                    title="Tag name already exists",
                    detail=f"name={payload.name!r}",
                    status_code=409,
                )
        row = await self._repo.update(item_id, payload)
        if row is None:
            raise self._not_found(item_id)
        return TagRead.model_validate(row)

    async def delete(self, item_id: int) -> None:
        ok = await self._repo.delete(item_id)
        if not ok:
            raise self._not_found(item_id)

    @staticmethod
    def _not_found(item_id: int) -> AppError:
        return AppError(
            code=NOT_FOUND_CODE,
            title="Tag not found",
            detail=f"id={item_id}",
            status_code=404,
        )
