"""Config service —— 业务用例层（运营参数，抛 ``AppError``，错误码 ``config.*``）。

事务边界由 ``get_session`` 拥有（一请求 = 一事务）。service 决定**何时** raise，不抛 HTTPException
（分层契约 C3）。

业务不变式：
  * **config_key 全局唯一** —— create 用 ``find_by_key`` 预检，违反抛 409 ``config.KEY_DUPLICATE``；
    DB ``uq_configs_key`` 是竞态兜底（IntegrityError handler 翻同码）。
  * **内置参数禁删** —— ``is_builtin=true`` 的参数删除抛 409 ``config.BUILTIN_READONLY``（spec §2.3）。
  * **热更新** —— ``get_value`` 每次读穿 DB（无进程内缓存），更新提交后下次读即新值（spec §2.3 决策 B）。
"""

from __future__ import annotations

from admin_platform.core.errors import AppError
from admin_platform.domains.config.repository import ConfigRepository
from admin_platform.domains.config.schemas import (
    ConfigCreate,
    ConfigPage,
    ConfigRead,
    ConfigUpdate,
    ConfigValueRead,
)

NOT_FOUND_CODE = "config.NOT_FOUND"
KEY_DUPLICATE_CODE = "config.KEY_DUPLICATE"
BUILTIN_READONLY_CODE = "config.BUILTIN_READONLY"


class ConfigService:
    def __init__(self, repository: ConfigRepository) -> None:
        self._repo = repository

    async def list_(self, *, keyword: str | None, page: int, size: int) -> ConfigPage:
        """offset 分页（ADR 0001 §7.5 envelope），可选按 key/name 关键词过滤。"""
        rows = await self._repo.list_paginated(keyword=keyword, page=page, size=size)
        total = await self._repo.count(keyword=keyword)
        total_pages = (total + size - 1) // size if size > 0 else 0
        return ConfigPage(
            items=[ConfigRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=total_pages,
        )

    async def get(self, item_id: int) -> ConfigRead:
        row = await self._repo.get(item_id)
        if row is None:
            raise self._not_found(detail=f"id={item_id}")
        return ConfigRead.model_validate(row)

    async def get_value(self, config_key: str) -> ConfigValueRead:
        """消费契约：按 key **读穿 DB** 取最新值（热更新——无缓存，更新提交后即生效）。"""
        row = await self._repo.find_by_key(config_key)
        if row is None:
            raise self._not_found(detail=f"key={config_key!r}")
        return ConfigValueRead.model_validate(row)

    async def create(self, payload: ConfigCreate) -> ConfigRead:
        if await self._repo.find_by_key(payload.config_key) is not None:
            raise self._duplicate(payload.config_key)
        row = await self._repo.create(payload)
        return ConfigRead.model_validate(row)

    async def update(self, item_id: int, payload: ConfigUpdate) -> ConfigRead:
        row = await self._repo.update(item_id, payload)
        if row is None:  # 不存在 / 并发删除兜底
            raise self._not_found(detail=f"id={item_id}")
        return ConfigRead.model_validate(row)

    async def delete(self, item_id: int) -> None:
        existing = await self._repo.get(item_id)
        if existing is None:
            raise self._not_found(detail=f"id={item_id}")
        if existing.is_builtin:
            raise AppError(
                code=BUILTIN_READONLY_CODE,
                title="Builtin config cannot be deleted",
                detail=f"id={item_id}",
                status_code=409,
            )
        await self._repo.delete(item_id)

    @staticmethod
    def _not_found(*, detail: str) -> AppError:
        return AppError(
            code=NOT_FOUND_CODE, title="Config not found", detail=detail, status_code=404
        )

    @staticmethod
    def _duplicate(config_key: str) -> AppError:
        return AppError(
            code=KEY_DUPLICATE_CODE,
            title="Config key already exists",
            detail=f"key={config_key!r}",
            status_code=409,
        )
