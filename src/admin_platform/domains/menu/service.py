"""Menu service —— 业务用例层（菜单树，抛 ``AppError``，错误码 ``menu.*``）。

事务边界由 ``get_session`` 拥有（一请求 = 一事务）。service 决定**何时** raise（触发请求
事务回滚），不抛 HTTPException（分层契约 C3）。镜像 dept service 的树写纪律。

业务不变式：
  * **移动防环** —— update 改 ``parent_id`` 时，新父不能是自身、也不能落在自身子孙集合内
    （邻接表移动成环会让子树脱离根 + 递归 CTE 死循环），违反抛 409 ``menu.CYCLE``。
    移到根（``parent_id=None``）永远安全，不校验。
  * **父存在** —— create / 移动指定 ``parent_id`` 时父菜单须存在，否则 404 ``menu.PARENT_NOT_FOUND``
    （不退化成裸 FK CONFLICT）。
  * **删除 RESTRICT** —— 有直接子菜单时禁删，抛 409 ``menu.HAS_CHILDREN``（与 DB 外键
    ``ondelete=RESTRICT`` 同义，给友好业务码）。

菜单**无 code** —— 不做唯一校验（与 dept/role 不同）。
"""

from __future__ import annotations

from admin_platform.core.errors import AppError
from admin_platform.domains.menu.repository import MenuRepository
from admin_platform.domains.menu.schemas import (
    MenuCreate,
    MenuPage,
    MenuRead,
    MenuUpdate,
)

NOT_FOUND_CODE = "menu.NOT_FOUND"
PARENT_NOT_FOUND_CODE = "menu.PARENT_NOT_FOUND"
CYCLE_CODE = "menu.CYCLE"
HAS_CHILDREN_CODE = "menu.HAS_CHILDREN"


class MenuService:
    def __init__(self, repository: MenuRepository) -> None:
        self._repo = repository

    async def list_(self, *, page: int, size: int) -> MenuPage:
        """offset 分页（ADR 0001 §7.5 envelope）。菜单是全局配置，不受 data_scope 约束。"""
        rows = await self._repo.list_paginated(page, size)
        total = await self._repo.count()
        total_pages = (total + size - 1) // size if size > 0 else 0
        return MenuPage(
            items=[MenuRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=total_pages,
        )

    async def get(self, item_id: int) -> MenuRead:
        row = await self._repo.get(item_id)
        if row is None:
            raise self._not_found(item_id)
        return MenuRead.model_validate(row)

    async def create(self, payload: MenuCreate) -> MenuRead:
        if payload.parent_id is not None and await self._repo.get(payload.parent_id) is None:
            raise self._parent_not_found(payload.parent_id)
        row = await self._repo.create(payload)
        return MenuRead.model_validate(row)

    async def update(self, item_id: int, payload: MenuUpdate) -> MenuRead:
        existing = await self._repo.get(item_id)
        if existing is None:
            raise self._not_found(item_id)
        # 移动（改 parent 到非 None）走树写串行化：先拿 advisory lock，锁内做 parent 存在 + 防环
        # 校验，关掉 _check_no_cycle 的 TOCTOU 窗口（并发移动 A→B、B→A 各自都过、提交后成环）。
        new_parent_id = payload.parent_id if "parent_id" in payload.model_fields_set else None
        if new_parent_id is not None:
            await self._repo.acquire_tree_lock()
            if await self._repo.get(new_parent_id) is None:
                raise self._parent_not_found(new_parent_id)
            await self._check_no_cycle(item_id, payload)
        row = await self._repo.update(item_id, payload)
        if row is None:  # 并发删除兜底：预检后被他人删除
            raise self._not_found(item_id)
        return MenuRead.model_validate(row)

    async def delete(self, item_id: int) -> None:
        row = await self._repo.get(item_id)
        if row is None:
            raise self._not_found(item_id)
        # 树写串行化：锁内重新查子菜单，避免并发把子菜单移走后误判可删（与 DB RESTRICT 一致，友好 409）。
        await self._repo.acquire_tree_lock()
        if await self._repo.count_children(item_id) > 0:
            raise self._has_children(item_id)
        await self._repo.delete(item_id)

    async def _check_no_cycle(self, item_id: int, payload: MenuUpdate) -> None:
        """移动防环：新父不能是自身或自身子孙（移到根 None 永远安全）。"""
        if "parent_id" not in payload.model_fields_set or payload.parent_id is None:
            return
        new_parent_id = payload.parent_id
        if new_parent_id == item_id:
            raise self._cycle(item_id, new_parent_id)
        # list_descendant_menu_ids 含自身，子孙集合即「不可作为新父」的封闭集。
        descendants = await self._repo.list_descendant_menu_ids(item_id)
        if new_parent_id in descendants:
            raise self._cycle(item_id, new_parent_id)

    @staticmethod
    def _not_found(item_id: int) -> AppError:
        return AppError(
            code=NOT_FOUND_CODE,
            title="Menu not found",
            detail=f"id={item_id}",
            status_code=404,
        )

    @staticmethod
    def _parent_not_found(parent_id: int) -> AppError:
        return AppError(
            code=PARENT_NOT_FOUND_CODE,
            title="Parent menu not found",
            detail=f"parent_id={parent_id}",
            status_code=404,
        )

    @staticmethod
    def _cycle(item_id: int, new_parent_id: int) -> AppError:
        return AppError(
            code=CYCLE_CODE,
            title="Menu move would create a cycle",
            detail=f"不能把菜单 id={item_id} 移动到自身或其子孙 id={new_parent_id} 之下",
            status_code=409,
        )

    @staticmethod
    def _has_children(item_id: int) -> AppError:
        return AppError(
            code=HAS_CHILDREN_CODE,
            title="Menu has children",
            detail=f"菜单 id={item_id} 存在子菜单，禁止删除",
            status_code=409,
        )
