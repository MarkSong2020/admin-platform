"""Config repository —— SQLAlchemy 2.x async 数据访问层。返回 ORM 行 / None / 集合，不抛业务异常。

除标准 CRUD 外，承载：``find_by_key``（唯一性预检）+ ``get_value_by_key``（消费契约**读穿**取
最新值，无缓存——热更新由「每次读 DB」保证，spec §2.3 决策 B）。
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.config.models import Config
from admin_platform.domains.config.schemas import ConfigCreate, ConfigUpdate


def _filters(keyword: str | None) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if keyword:
        like = f"%{keyword}%"
        conds.append(Config.config_key.ilike(like) | Config.name.ilike(like))
    return conds


class ConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paginated(self, *, keyword: str | None, page: int, size: int) -> list[Config]:
        offset = (page - 1) * size
        stmt = (
            select(Config).where(*_filters(keyword)).offset(offset).limit(size).order_by(Config.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, *, keyword: str | None) -> int:
        stmt = select(func.count()).select_from(Config).where(*_filters(keyword))
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def get(self, item_id: int) -> Config | None:
        return await self._session.get(Config, item_id)

    async def find_by_key(self, config_key: str) -> Config | None:
        """按 config_key 查找（唯一性预检 + 消费契约读穿）。"""
        result = await self._session.execute(
            select(Config).where(Config.config_key == config_key).limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, payload: ConfigCreate) -> Config:
        obj = Config(**payload.model_dump())
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(self, item_id: int, payload: ConfigUpdate) -> Config | None:
        obj = await self._session.get(Config, item_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self._session.flush()
        # onupdate=func.now() 让 updated_at 过期；异步 session 下后续序列化访问触发隐式刷新报错
        # （Errata #7）。显式 refresh 取回新值。
        await self._session.refresh(obj)
        return obj

    async def delete(self, item_id: int) -> bool:
        obj = await self._session.get(Config, item_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True
