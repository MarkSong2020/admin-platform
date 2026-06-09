"""Notice repository —— SQLAlchemy 2.x async 数据访问层。返回 ORM 行 / None / 集合，不抛业务异常。

扁平域无绑定、无唯一键，只有标准 CRUD + 可选 ``notice_type`` / ``status`` 过滤（管理端列表用）。
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.notice.models import Notice
from admin_platform.domains.notice.schemas import NoticeCreate, NoticeUpdate


def _filters(notice_type: str | None, status: str | None) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if notice_type is not None:
        conds.append(Notice.notice_type == notice_type)
    if status is not None:
        conds.append(Notice.status == status)
    return conds


class NoticeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paginated(
        self, *, notice_type: str | None, status: str | None, page: int, size: int
    ) -> list[Notice]:
        offset = (page - 1) * size
        stmt = (
            select(Notice)
            .where(*_filters(notice_type, status))
            .offset(offset)
            .limit(size)
            .order_by(Notice.id.desc())  # 公告按新→旧
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, *, notice_type: str | None, status: str | None) -> int:
        stmt = select(func.count()).select_from(Notice).where(*_filters(notice_type, status))
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def get(self, item_id: int) -> Notice | None:
        return await self._session.get(Notice, item_id)

    async def create(self, payload: NoticeCreate) -> Notice:
        obj = Notice(**payload.model_dump())
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(self, item_id: int, payload: NoticeUpdate) -> Notice | None:
        obj = await self._session.get(Notice, item_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self._session.flush()
        # onupdate=func.now() 让 updated_at 过期；异步 session 下后续序列化访问过期列触发隐式
        # 刷新报错（Errata #7）。显式 refresh 取回新值。
        await self._session.refresh(obj)
        return obj

    async def delete(self, item_id: int) -> bool:
        obj = await self._session.get(Notice, item_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True
