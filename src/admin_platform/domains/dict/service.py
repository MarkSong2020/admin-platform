"""Dict service —— 业务用例层（两资源：字典类型 + 字典数据，抛 ``AppError``，错误码 ``dict.*``）。

事务边界由 ``get_session`` 拥有（一请求 = 一事务）。service 决定**何时** raise，不抛 HTTPException
（分层契约 C3）。

业务不变式：
  * **type 全局唯一** —— create_type 预检 409 ``dict.TYPE_DUPLICATE``（DB ``uq_dict_types_type`` 兜底）。
  * **删类型需空** —— 类型下有数据时拒删 409 ``dict.TYPE_HAS_DATA``（对齐 FK RESTRICT，不静默级联）。
  * **内置类型禁删** —— ``is_builtin`` 类型 409 ``dict.TYPE_BUILTIN_READONLY``。
  * **数据必属已存在类型** —— create_data 校验 404 ``dict.TYPE_NOT_FOUND``。
  * **同类型内 value 唯一** —— DB ``uq_dict_data_type_value`` 兜底翻 409 ``dict.DATA_DUPLICATE``。
  * **单默认值** —— set ``is_default`` 时先清同类型其它默认（spec §2.2）。
"""

from __future__ import annotations

from admin_platform.core.errors import AppError
from admin_platform.domains.dict.repository import DictRepository
from admin_platform.domains.dict.schemas import (
    DictDataCreate,
    DictDataPage,
    DictDataRead,
    DictDataUpdate,
    DictTypeCreate,
    DictTypePage,
    DictTypeRead,
    DictTypeUpdate,
)

TYPE_NOT_FOUND_CODE = "dict.TYPE_NOT_FOUND"
TYPE_DUPLICATE_CODE = "dict.TYPE_DUPLICATE"
TYPE_HAS_DATA_CODE = "dict.TYPE_HAS_DATA"
TYPE_BUILTIN_READONLY_CODE = "dict.TYPE_BUILTIN_READONLY"
DATA_NOT_FOUND_CODE = "dict.DATA_NOT_FOUND"
# 下两码由 DB 约束竞态兜底（IntegrityError handler 据 models.py 注册映射抛），service 不直接 raise；
# 集中声明以便枚举 dict 域全部错误码（对抗审查 S5）。
DATA_DUPLICATE_CODE = "dict.DATA_DUPLICATE"
DEFAULT_DUPLICATE_CODE = "dict.DEFAULT_DUPLICATE"


def _pages(total: int, size: int) -> int:
    return (total + size - 1) // size if size > 0 else 0


class DictService:
    def __init__(self, repository: DictRepository) -> None:
        self._repo = repository

    # ---- 字典类型 ----------------------------------------------------------

    async def list_types(self, *, keyword: str | None, page: int, size: int) -> DictTypePage:
        rows = await self._repo.list_types_paginated(keyword=keyword, page=page, size=size)
        total = await self._repo.count_types(keyword=keyword)
        return DictTypePage(
            items=[DictTypeRead.model_validate(r) for r in rows],
            page=page,
            size=size,
            total=total,
            total_pages=_pages(total, size),
        )

    async def get_type(self, type_id: int) -> DictTypeRead:
        row = await self._repo.get_type(type_id)
        if row is None:
            raise self._type_not_found(type_id)
        return DictTypeRead.model_validate(row)

    async def create_type(self, payload: DictTypeCreate) -> DictTypeRead:
        if await self._repo.find_type_by_type(payload.type) is not None:
            raise AppError(
                code=TYPE_DUPLICATE_CODE,
                title="Dict type already exists",
                detail=f"type={payload.type!r}",
                status_code=409,
            )
        row = await self._repo.create_type(payload)
        return DictTypeRead.model_validate(row)

    async def update_type(self, type_id: int, payload: DictTypeUpdate) -> DictTypeRead:
        row = await self._repo.update_type(type_id, payload)
        if row is None:
            raise self._type_not_found(type_id)
        return DictTypeRead.model_validate(row)

    async def delete_type(self, type_id: int) -> None:
        existing = await self._repo.get_type(type_id)
        if existing is None:
            raise self._type_not_found(type_id)
        if existing.is_builtin:
            raise AppError(
                code=TYPE_BUILTIN_READONLY_CODE,
                title="Builtin dict type cannot be deleted",
                detail=f"id={type_id}",
                status_code=409,
            )
        if await self._repo.count_data_for_type(type_id) > 0:
            raise AppError(
                code=TYPE_HAS_DATA_CODE,
                title="Dict type still has data",
                detail=f"id={type_id}",
                status_code=409,
            )
        await self._repo.delete_type(type_id)

    # ---- 字典数据 ----------------------------------------------------------

    async def list_data(self, *, dict_type_id: int | None, page: int, size: int) -> DictDataPage:
        rows = await self._repo.list_data_paginated(dict_type_id=dict_type_id, page=page, size=size)
        total = await self._repo.count_data(dict_type_id=dict_type_id)
        return DictDataPage(
            items=[DictDataRead.model_validate(r) for r in rows],
            page=page,
            size=size,
            total=total,
            total_pages=_pages(total, size),
        )

    async def get_data(self, data_id: int) -> DictDataRead:
        row = await self._repo.get_data(data_id)
        if row is None:
            raise self._data_not_found(data_id)
        return DictDataRead.model_validate(row)

    async def list_data_by_type(self, type_str: str) -> list[DictDataRead]:
        """消费契约：按 type 取启用数据（类型不存在 → 空列表，对齐 RuoYi）。"""
        rows = await self._repo.list_data_by_type(type_str, enabled_only=True)
        return [DictDataRead.model_validate(r) for r in rows]

    async def create_data(self, payload: DictDataCreate) -> DictDataRead:
        if await self._repo.get_type(payload.dict_type_id) is None:
            raise self._type_not_found(payload.dict_type_id)
        if payload.is_default:
            await self._repo.clear_other_defaults(payload.dict_type_id, except_id=None)
        row = await self._repo.create_data(payload)
        return DictDataRead.model_validate(row)

    async def update_data(self, data_id: int, payload: DictDataUpdate) -> DictDataRead:
        existing = await self._repo.get_data(data_id)
        if existing is None:
            raise self._data_not_found(data_id)
        if payload.is_default is True:
            await self._repo.clear_other_defaults(existing.dict_type_id, except_id=data_id)
        row = await self._repo.update_data(data_id, payload)
        if row is None:  # 并发删除兜底
            raise self._data_not_found(data_id)
        return DictDataRead.model_validate(row)

    async def delete_data(self, data_id: int) -> None:
        ok = await self._repo.delete_data(data_id)
        if not ok:
            raise self._data_not_found(data_id)

    @staticmethod
    def _type_not_found(type_id: int) -> AppError:
        return AppError(
            code=TYPE_NOT_FOUND_CODE,
            title="Dict type not found",
            detail=f"id={type_id}",
            status_code=404,
        )

    @staticmethod
    def _data_not_found(data_id: int) -> AppError:
        return AppError(
            code=DATA_NOT_FOUND_CODE,
            title="Dict data not found",
            detail=f"id={data_id}",
            status_code=404,
        )
