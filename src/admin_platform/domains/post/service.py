"""Post service —— 业务用例层（RBAC 岗位，抛 ``AppError``，错误码 ``post.*``）。

事务边界由 ``get_session`` 拥有（一请求 = 一事务）。service 决定**何时** raise（触发请求
事务回滚），不抛 HTTPException（分层契约 C3）。

业务不变式：
  * **code 全局唯一** —— create / update（改 code 时）用 ``find_by_code`` 预检，违反抛 409
    ``post.CODE_DUPLICATE``。DB 的 ``uq_posts_code`` 是竞态兜底：并发预检都通过时第二个
    INSERT 撞约束 → ``IntegrityError`` handler 按 ``models.py`` 注册映射翻成同一码。

岗位是扁平域：无树、无 data_scope，故比 role service 更简单（无 O2 归一）。
"""

from __future__ import annotations

from admin_platform.core.errors import AppError
from admin_platform.domains.post.repository import PostRepository
from admin_platform.domains.post.schemas import (
    PostCreate,
    PostPage,
    PostRead,
    PostUpdate,
)

NOT_FOUND_CODE = "post.NOT_FOUND"
CODE_DUPLICATE_CODE = "post.CODE_DUPLICATE"


class PostService:
    def __init__(self, repository: PostRepository) -> None:
        self._repo = repository

    async def list_(self, *, page: int, size: int) -> PostPage:
        """offset 分页（ADR 0001 §7.5 envelope）。岗位是全局配置，不受 data_scope 约束。"""
        rows = await self._repo.list_paginated(page, size)
        total = await self._repo.count()
        total_pages = (total + size - 1) // size if size > 0 else 0
        return PostPage(
            items=[PostRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=total_pages,
        )

    async def get(self, item_id: int) -> PostRead:
        row = await self._repo.get(item_id)
        if row is None:
            raise self._not_found(item_id)
        return PostRead.model_validate(row)

    async def create(self, payload: PostCreate) -> PostRead:
        if await self._repo.find_by_code(payload.code) is not None:
            raise self._duplicate(payload.code)
        row = await self._repo.create(payload)
        return PostRead.model_validate(row)

    async def update(self, item_id: int, payload: PostUpdate) -> PostRead:
        existing = await self._repo.get(item_id)
        if existing is None:
            raise self._not_found(item_id)
        await self._check_code_unique(existing, payload)
        row = await self._repo.update(item_id, payload)
        if row is None:  # 并发删除兜底：预检后被他人删除
            raise self._not_found(item_id)
        return PostRead.model_validate(row)

    async def delete(self, item_id: int) -> None:
        ok = await self._repo.delete(item_id)
        if not ok:
            raise self._not_found(item_id)

    async def _check_code_unique(self, existing: object, payload: PostUpdate) -> None:
        """改 code 且与现值不同时校验全局唯一（未改 code 跳过）。"""
        if "code" not in payload.model_fields_set or payload.code is None:
            return
        if payload.code == getattr(existing, "code", None):
            return
        if await self._repo.find_by_code(payload.code) is not None:
            raise self._duplicate(payload.code)

    @staticmethod
    def _not_found(item_id: int) -> AppError:
        return AppError(
            code=NOT_FOUND_CODE,
            title="Post not found",
            detail=f"id={item_id}",
            status_code=404,
        )

    @staticmethod
    def _duplicate(code: str) -> AppError:
        return AppError(
            code=CODE_DUPLICATE_CODE,
            title="Post code already exists",
            detail=f"code={code!r}",
            status_code=409,
        )
