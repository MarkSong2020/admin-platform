"""Dict repository —— SQLAlchemy 2.x async 数据访问层（两资源：dict_types + dict_data）。

返回 ORM 行 / None / 集合，不抛业务异常。承载跨两表的查询：``count_data_for_type``（删类型预检）、
``list_data_by_type``（消费契约：按 type 字符串取启用数据）、``clear_other_defaults``（单默认值）。
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.core.pagination import ilike_contains
from admin_platform.domains.dict.models import DictData, DictType
from admin_platform.domains.dict.schemas import (
    DictDataCreate,
    DictDataUpdate,
    DictTypeCreate,
    DictTypeUpdate,
)


def _type_filters(keyword: str | None) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if keyword:
        conds.append(
            ilike_contains(DictType.name, keyword) | ilike_contains(DictType.type, keyword)
        )
    return conds


class DictRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- 字典类型 dict_types -----------------------------------------------

    async def list_types_paginated(
        self, *, keyword: str | None, page: int, size: int
    ) -> list[DictType]:
        offset = (page - 1) * size
        stmt = (
            select(DictType)
            .where(*_type_filters(keyword))
            .offset(offset)
            .limit(size)
            .order_by(DictType.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_types(self, *, keyword: str | None) -> int:
        stmt = select(func.count()).select_from(DictType).where(*_type_filters(keyword))
        return int((await self._session.execute(stmt)).scalar_one())

    async def get_type(self, type_id: int) -> DictType | None:
        return await self._session.get(DictType, type_id)

    async def find_type_by_type(self, type_str: str) -> DictType | None:
        """按 type 字符串查找（唯一性预检 + 消费契约定位）。"""
        result = await self._session.execute(
            select(DictType).where(DictType.type == type_str).limit(1)
        )
        return result.scalar_one_or_none()

    async def create_type(self, payload: DictTypeCreate) -> DictType:
        obj = DictType(**payload.model_dump())
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update_type(self, type_id: int, payload: DictTypeUpdate) -> DictType | None:
        obj = await self._session.get(DictType, type_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self._session.flush()
        await self._session.refresh(obj)  # Errata #7：取回 onupdate 的 updated_at
        return obj

    async def delete_type(self, type_id: int) -> bool:
        obj = await self._session.get(DictType, type_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True

    async def count_data_for_type(self, type_id: int) -> int:
        """该类型下的字典数据条数（删类型预检：>0 则拒删，对齐 FK RESTRICT）。"""
        stmt = select(func.count()).select_from(DictData).where(DictData.dict_type_id == type_id)
        return int((await self._session.execute(stmt)).scalar_one())

    # ---- 字典数据 dict_data ------------------------------------------------

    async def list_data_paginated(
        self, *, dict_type_id: int | None, page: int, size: int
    ) -> list[DictData]:
        offset = (page - 1) * size
        conds = [DictData.dict_type_id == dict_type_id] if dict_type_id is not None else []
        stmt = (
            select(DictData)
            .where(*conds)
            .offset(offset)
            .limit(size)
            .order_by(DictData.dict_type_id, DictData.sort_order, DictData.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_data(self, *, dict_type_id: int | None) -> int:
        conds = [DictData.dict_type_id == dict_type_id] if dict_type_id is not None else []
        stmt = select(func.count()).select_from(DictData).where(*conds)
        return int((await self._session.execute(stmt)).scalar_one())

    async def get_data(self, data_id: int) -> DictData | None:
        return await self._session.get(DictData, data_id)

    async def list_data_by_type(self, type_str: str, *, enabled_only: bool) -> list[DictData]:
        """消费契约：按 type 字符串取该类型数据（启用项，按 sort 排序）；类型不存在返回空。

        ``enabled_only`` 下停用的字典类型（``DictType.status != active``）也返回空——停用类型
        不应继续向消费方下发数据（对抗审查 S3），否则 status 字段对消费面失效。
        """
        type_row = await self.find_type_by_type(type_str)
        if type_row is None:
            return []
        if enabled_only and type_row.status != "active":
            return []
        conds = [DictData.dict_type_id == type_row.id]
        if enabled_only:
            conds.append(DictData.status == "active")
        stmt = select(DictData).where(*conds).order_by(DictData.sort_order, DictData.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def clear_other_defaults(self, dict_type_id: int, *, except_id: int | None) -> None:
        """把同类型其它行的 is_default 置 false（单默认值不变式，set 默认前调用）。"""
        conds = [DictData.dict_type_id == dict_type_id, DictData.is_default.is_(True)]
        if except_id is not None:
            conds.append(DictData.id != except_id)
        await self._session.execute(update(DictData).where(*conds).values(is_default=False))

    async def create_data(self, payload: DictDataCreate) -> DictData:
        obj = DictData(**payload.model_dump())
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update_data(self, data_id: int, payload: DictDataUpdate) -> DictData | None:
        obj = await self._session.get(DictData, data_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self._session.flush()
        await self._session.refresh(obj)  # Errata #7
        return obj

    async def delete_data(self, data_id: int) -> bool:
        obj = await self._session.get(DictData, data_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True
