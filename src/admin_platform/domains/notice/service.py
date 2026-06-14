"""Notice service —— 业务用例层（运营公告，抛 ``AppError``，错误码 ``notice.*``）。

事务边界由 ``get_session`` 拥有（一请求 = 一事务）。service 决定**何时** raise（触发请求
事务回滚），不抛 HTTPException（分层契约 C3）。扁平域无唯一键、无树，只有 404 一条业务错误。
"""

from __future__ import annotations

from admin_platform.core.errors import AppError
from admin_platform.core.pagination import compute_total_pages
from admin_platform.domains.notice.repository import NoticeRepository
from admin_platform.domains.notice.schemas import (
    NoticeCreate,
    NoticePage,
    NoticeRead,
    NoticeUpdate,
)

NOT_FOUND_CODE = "notice.NOT_FOUND"


class NoticeService:
    def __init__(self, repository: NoticeRepository) -> None:
        self._repo = repository

    async def list_(
        self, *, notice_type: str | None, status: str | None, page: int, size: int
    ) -> NoticePage:
        """offset 分页（ADR 0001 §7.5 envelope），可选按类型 / 状态过滤。"""
        rows = await self._repo.list_paginated(
            notice_type=notice_type, status=status, page=page, size=size
        )
        total = await self._repo.count(notice_type=notice_type, status=status)
        return NoticePage(
            items=[NoticeRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=compute_total_pages(total, size),
        )

    async def get(self, item_id: int) -> NoticeRead:
        row = await self._repo.get(item_id)
        if row is None:
            raise self._not_found(item_id)
        return NoticeRead.model_validate(row)

    async def create(self, payload: NoticeCreate) -> NoticeRead:
        row = await self._repo.create(payload)
        return NoticeRead.model_validate(row)

    async def update(self, item_id: int, payload: NoticeUpdate) -> NoticeRead:
        row = await self._repo.update(item_id, payload)
        if row is None:  # 不存在 / 并发删除兜底
            raise self._not_found(item_id)
        return NoticeRead.model_validate(row)

    async def delete(self, item_id: int) -> None:
        ok = await self._repo.delete(item_id)
        if not ok:
            raise self._not_found(item_id)

    @staticmethod
    def _not_found(item_id: int) -> AppError:
        return AppError(
            code=NOT_FOUND_CODE,
            title="Notice not found",
            detail=f"id={item_id}",
            status_code=404,
        )
