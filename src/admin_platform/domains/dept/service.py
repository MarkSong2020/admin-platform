"""Dept service —— 业务用例层（部门树，抛 ``AppError``，错误码 ``dept.*``）。

事务边界由 ``get_session`` 拥有（一请求 = 一事务）。service 决定**何时** raise
（触发请求事务回滚），不抛 HTTPException（分层契约 C3）。

业务不变式：

  * **code 全局唯一** —— create / update（改 code 时）用 ``find_by_code`` 预检，违反抛
    409 ``dept.CODE_DUPLICATE``。DB 的 ``uq_depts_code`` 是竞态兜底：并发预检都通过时
    第二个 INSERT 撞约束 → ``IntegrityError`` handler 按 ``models.py`` 注册映射翻成同一码。
  * **移动防环** —— update 改 ``parent_id`` 时，新父不能是自身、也不能落在自身子孙集合内
    （邻接表移动成环会让子树脱离根 + 递归 CTE 死循环），违反抛 409 ``dept.CYCLE``。
    移到根（``parent_id=None``）永远安全，不校验。
  * **删除 RESTRICT** —— 有直接子部门时禁删，抛 409 ``dept.HAS_CHILDREN``（与 DB 外键
    ``ondelete=RESTRICT`` 同义，但给出友好业务码，避免裸 IntegrityError 退化成无意义 conflict）。
"""

from __future__ import annotations

from admin_platform.authz.data_scope import is_dept_visible
from admin_platform.authz.scope import DataScope
from admin_platform.core.errors import AUTH_FORBIDDEN_BY_SCOPE, AppError
from admin_platform.domains.dept.repository import DeptRepository
from admin_platform.domains.dept.schemas import (
    DeptCreate,
    DeptPage,
    DeptRead,
    DeptUpdate,
)

NOT_FOUND_CODE = "dept.NOT_FOUND"
PARENT_NOT_FOUND_CODE = "dept.PARENT_NOT_FOUND"
CODE_DUPLICATE_CODE = "dept.CODE_DUPLICATE"
CYCLE_CODE = "dept.CYCLE"
HAS_CHILDREN_CODE = "dept.HAS_CHILDREN"


class DeptService:
    def __init__(self, repository: DeptRepository) -> None:
        self._repo = repository

    async def list_(self, *, page: int, size: int, scope: DataScope | None = None) -> DeptPage:
        """offset 分页（ADR 0001 §7.5 envelope）。

        ``scope`` 非空时按数据权限过滤可见部门（**非超管必传**，防泄露完整组织树）；
        超管在 api 层传 None（不过滤）。
        """
        rows = await self._repo.list_paginated(page, size, scope=scope)
        total = await self._repo.count(scope=scope)
        total_pages = (total + size - 1) // size if size > 0 else 0
        return DeptPage(
            items=[DeptRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=total_pages,
        )

    async def get(self, item_id: int, *, scope: DataScope | None = None) -> DeptRead:
        row = await self._repo.get(item_id)
        # 数据权限（Codex 深审 F5）：非超管按 data_scope 限制可读部门——不可见时返回 NOT_FOUND
        # （不泄露存在性，与 list 同口径）。scope=None / ALL（超管 api 层）不限制。
        if row is None or (scope is not None and not is_dept_visible(scope, row.id)):
            raise self._not_found(item_id)
        return DeptRead.model_validate(row)

    async def create(self, payload: DeptCreate, *, scope: DataScope | None = None) -> DeptRead:
        # 数据权限写侧：非超管只能在可见父部门下建子部门（建根 parent=None 需 ALL，否则 403）。
        if scope is not None and not is_dept_visible(scope, payload.parent_id):
            raise self._forbidden_scope()
        if payload.parent_id is not None and await self._repo.get(payload.parent_id) is None:
            raise self._parent_not_found(payload.parent_id)
        if await self._repo.find_by_code(payload.code) is not None:
            raise self._duplicate(payload.code)
        row = await self._repo.create(payload)
        return DeptRead.model_validate(row)

    async def update(
        self, item_id: int, payload: DeptUpdate, *, scope: DataScope | None = None
    ) -> DeptRead:
        existing = await self._repo.get(item_id)
        if existing is None or (scope is not None and not is_dept_visible(scope, existing.id)):
            # 数据权限不可见 = 当作不存在（不泄露存在性）。
            raise self._not_found(item_id)
        await self._check_code_unique(existing, payload)
        # 移动（改 parent 到非 None）走树写串行化：先拿 advisory lock，锁内做 parent 存在 + 数据范围 +
        # 防环校验，关掉 _check_no_cycle 的 TOCTOU 窗口（并发移动 A→B、B→A 各自都过、提交后成环）。
        new_parent_id = payload.parent_id if "parent_id" in payload.model_fields_set else None
        if new_parent_id is not None:
            await self._repo.acquire_tree_lock()
            if await self._repo.get(new_parent_id) is None:
                raise self._parent_not_found(new_parent_id)
            if scope is not None and not is_dept_visible(scope, new_parent_id):
                raise self._forbidden_scope()  # 移到数据范围外的父部门 → 403
            await self._check_no_cycle(item_id, payload)
        row = await self._repo.update(item_id, payload)
        if row is None:  # 并发删除兜底：预检后被他人删除
            raise self._not_found(item_id)
        return DeptRead.model_validate(row)

    async def delete(self, item_id: int, *, scope: DataScope | None = None) -> None:
        row = await self._repo.get(item_id)
        if row is None or (scope is not None and not is_dept_visible(scope, row.id)):
            raise self._not_found(item_id)
        # 树写串行化：锁内重新查子部门，避免并发把子部门移走后误判可删（与 DB RESTRICT 一致，给友好 409）。
        await self._repo.acquire_tree_lock()
        if await self._repo.count_children(item_id) > 0:
            raise self._has_children(item_id)
        await self._repo.delete(item_id)

    async def _check_code_unique(self, existing: object, payload: DeptUpdate) -> None:
        """改 code 且与现值不同时校验全局唯一（未改 code 跳过）。"""
        if "code" not in payload.model_fields_set or payload.code is None:
            return
        if payload.code == getattr(existing, "code", None):
            return
        if await self._repo.find_by_code(payload.code) is not None:
            raise self._duplicate(payload.code)

    async def _check_no_cycle(self, item_id: int, payload: DeptUpdate) -> None:
        """移动防环：新父不能是自身或自身子孙（移到根 None 永远安全）。"""
        if "parent_id" not in payload.model_fields_set or payload.parent_id is None:
            return
        new_parent_id = payload.parent_id
        if new_parent_id == item_id:
            raise self._cycle(item_id, new_parent_id)
        # list_descendant_dept_ids 含自身，子孙集合即「不可作为新父」的封闭集。
        descendants = await self._repo.list_descendant_dept_ids(item_id)
        if new_parent_id in descendants:
            raise self._cycle(item_id, new_parent_id)

    @staticmethod
    def _not_found(item_id: int) -> AppError:
        return AppError(
            code=NOT_FOUND_CODE,
            title="Dept not found",
            detail=f"id={item_id}",
            status_code=404,
        )

    @staticmethod
    def _duplicate(code: str) -> AppError:
        return AppError(
            code=CODE_DUPLICATE_CODE,
            title="Dept code already exists",
            detail=f"code={code!r}",
            status_code=409,
        )

    @staticmethod
    def _parent_not_found(parent_id: int) -> AppError:
        return AppError(
            code=PARENT_NOT_FOUND_CODE,
            title="Parent dept not found",
            detail=f"parent_id={parent_id}",
            status_code=404,
        )

    @staticmethod
    def _cycle(item_id: int, new_parent_id: int) -> AppError:
        return AppError(
            code=CYCLE_CODE,
            title="Dept move would create a cycle",
            detail=f"不能把部门 id={item_id} 移动到自身或其子孙 id={new_parent_id} 之下",
            status_code=409,
        )

    @staticmethod
    def _has_children(item_id: int) -> AppError:
        return AppError(
            code=HAS_CHILDREN_CODE,
            title="Dept has children",
            detail=f"部门 id={item_id} 存在子部门，禁止删除",
            status_code=409,
        )

    @staticmethod
    def _forbidden_scope() -> AppError:
        return AppError(
            code=AUTH_FORBIDDEN_BY_SCOPE,
            title="Forbidden by data scope",
            detail="目标部门不在你的数据权限范围内",
            status_code=403,
        )
