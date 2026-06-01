"""Tag repository — SQLAlchemy 2.x async 数据访问层。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.tag.models import Tag
from admin_platform.domains.tag.schemas import TagCreate, TagUpdate


class TagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paginated(self, page: int, size: int) -> list[Tag]:
        offset = (page - 1) * size
        stmt = select(Tag).offset(offset).limit(size).order_by(Tag.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        stmt = select(func.count()).select_from(Tag)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def get(self, item_id: int) -> Tag | None:
        return await self._session.get(Tag, item_id)

    async def find_by_name(self, name: str) -> Tag | None:
        """按业务唯一键 ``name`` 查找。service 层做 insert 前唯一性预检用。"""
        stmt = select(Tag).where(Tag.name == name).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many_by_ids(self, ids: list[int]) -> list[Tag]:
        """批量取 — todo 分配 tag 时按 id 列表一次查回。

        返回 ``ids`` 中**实际存在**的子集；是否把「部分缺失」视为错误由调用方决定
        （``todo.service`` 走 all-or-nothing 422 语义）。"""
        if not ids:
            return []
        stmt = select(Tag).where(Tag.id.in_(ids))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, payload: TagCreate) -> Tag:
        obj = Tag(**payload.model_dump())
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(self, item_id: int, payload: TagUpdate) -> Tag | None:
        obj = await self._session.get(Tag, item_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self._session.flush()
        return obj

    async def delete(self, item_id: int) -> bool:
        obj = await self._session.get(Tag, item_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True
