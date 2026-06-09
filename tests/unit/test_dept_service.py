"""DeptService 单元测试 —— stub repository 隔离业务规则（DB-free）。

不是 mock 行为断言：测的是 service 在「repo 说存在/不存在/有子/成环」等前置条件下**自己**
抛什么领域错误码（``dept.*``）；repo 只提供前置条件（DI 缝）。覆盖：
code 重复 409 / 移动成环 409（自身 + 子孙）/ 删除有子 409 / NOT_FOUND 404 / 正常 CRUD / 分页。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.errors import AppError
from admin_platform.domains.dept.models import Dept
from admin_platform.domains.dept.repository import DeptRepository
from admin_platform.domains.dept.schemas import DeptCreate, DeptUpdate
from admin_platform.domains.dept.service import DeptService

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _dept(
    did: int, *, code: str, name: str = "dept", parent_id: int | None = None, sort_order: int = 0
) -> Dept:
    """构造预置全部 ``DeptRead`` 字段的 transient Dept（不入库）。

    SQLAlchemy 的 ``default=`` 只在 flush 生效，transient 实例需手工补齐 sort_order /
    status / 时间戳，否则 ``DeptRead.model_validate`` 校验缺字段失败。
    """
    obj = Dept(name=name, code=code, parent_id=parent_id)
    obj.id = did
    obj.sort_order = sort_order
    obj.status = "active"
    obj.leader = None
    obj.phone = None
    obj.email = None
    obj.created_at = _TS
    obj.updated_at = _TS
    return obj


class _StubRepo:
    """最小 stub —— 只实现各用例会调到的方法。"""

    def __init__(
        self,
        *,
        rows: list[Dept] | None = None,
        by_code: dict[str, Dept] | None = None,
        children: int = 0,
        descendants: frozenset[int] = frozenset(),
    ) -> None:
        self._rows = {row.id: row for row in (rows or [])}
        self._by_code = by_code or {}
        self._children = children
        self._descendants = descendants
        self.update_called = False

    async def list_paginated(
        self, page: int, size: int, *, scope: object | None = None
    ) -> list[Dept]:
        start = (page - 1) * size
        return list(self._rows.values())[start : start + size]

    async def count(self, *, scope: object | None = None) -> int:
        return len(self._rows)

    async def acquire_tree_lock(self) -> None:
        """stub no-op（真实是 pg_advisory_xact_lock，单测无 DB）。"""

    async def get(self, dept_id: int) -> Dept | None:
        return self._rows.get(dept_id)

    async def find_by_code(self, code: str) -> Dept | None:
        return self._by_code.get(code)

    async def count_children(self, dept_id: int) -> int:
        return self._children

    async def list_descendant_dept_ids(self, dept_id: int) -> frozenset[int]:
        return self._descendants

    async def create(self, payload: DeptCreate) -> Dept:
        return _dept(
            1,
            code=payload.code,
            name=payload.name,
            parent_id=payload.parent_id,
            sort_order=payload.sort_order,
        )

    async def update(self, dept_id: int, payload: DeptUpdate) -> Dept | None:
        self.update_called = True
        row = self._rows.get(dept_id)
        if row is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        return row

    async def delete(self, dept_id: int) -> bool:
        return self._rows.pop(dept_id, None) is not None


def _svc(repo: _StubRepo) -> DeptService:
    return DeptService(cast("DeptRepository", repo))


# ---- get / create ----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).get(999)
    assert exc.value.code == "dept.NOT_FOUND"
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_ok() -> None:
    out = await _svc(_StubRepo()).create(DeptCreate(name="研发部", code="RD"))
    assert out.id == 1
    assert out.code == "RD"
    assert out.name == "研发部"


@pytest.mark.asyncio
async def test_create_duplicate_code_raises_409() -> None:
    existing = _dept(5, code="RD")
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(by_code={"RD": existing})).create(DeptCreate(name="dup", code="RD"))
    assert exc.value.code == "dept.CODE_DUPLICATE"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_nonexistent_parent_raises_404() -> None:
    """create 指定不存在的父部门 → dept.PARENT_NOT_FOUND（不退化成 FK CONFLICT）。"""
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).create(DeptCreate(name="x", code="X", parent_id=99))
    assert exc.value.code == "dept.PARENT_NOT_FOUND"
    assert exc.value.status_code == 404


# ---- update：移动防环 ------------------------------------------------------


@pytest.mark.asyncio
async def test_update_move_into_self_raises_cycle_409() -> None:
    node = _dept(2, code="A", parent_id=1)
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(rows=[node], descendants=frozenset({2}))).update(
            2, DeptUpdate(parent_id=2)
        )
    assert exc.value.code == "dept.CYCLE"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_move_into_descendant_raises_cycle_409() -> None:
    # 树 A(2)->B(3)->C(4)，descendants(A) = {2,3,4}；把 A 移到 C（存在）下成环。
    node = _dept(2, code="A")
    child_c = _dept(4, code="C", parent_id=3)
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(rows=[node, child_c], descendants=frozenset({2, 3, 4}))).update(
            2, DeptUpdate(parent_id=4)
        )
    assert exc.value.code == "dept.CYCLE"


@pytest.mark.asyncio
async def test_update_move_to_root_ok() -> None:
    # 显式置 parent_id=None（移到根）永远安全，不触发防环。
    node = _dept(3, code="B", parent_id=2)
    out = await _svc(_StubRepo(rows=[node], descendants=frozenset({3}))).update(
        3, DeptUpdate(parent_id=None)
    )
    assert out.parent_id is None


@pytest.mark.asyncio
async def test_update_move_under_valid_parent_ok() -> None:
    # 新父 9（存在、不在 B 的子孙集合内）→ 合法移动。
    node = _dept(3, code="B", parent_id=2)
    parent9 = _dept(9, code="P9")
    out = await _svc(_StubRepo(rows=[node, parent9], descendants=frozenset({3}))).update(
        3, DeptUpdate(parent_id=9)
    )
    assert out.parent_id == 9


@pytest.mark.asyncio
async def test_update_move_to_root_forbidden_for_non_all_scope() -> None:
    # Codex 深审越权：非超管（CUSTOM_DEPT）把可见部门显式移到根（parent_id=None）→ 403。
    # 堵 update parent=None 绕过数据范围（对齐 create 建根需 ALL 不变式）。
    node = _dept(3, code="B", parent_id=2)
    scope = DataScope(ScopeType.CUSTOM_DEPT, user_id=1, visible_dept_ids=frozenset({3}))
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(rows=[node])).update(3, DeptUpdate(parent_id=None), scope=scope)
    assert exc.value.code == "auth.FORBIDDEN_BY_SCOPE"
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_move_to_root_ok_for_all_scope() -> None:
    # ALL scope（超管）显式移到根仍放行 —— 修复不误伤超管。
    node = _dept(3, code="B", parent_id=2)
    scope = DataScope(ScopeType.ALL, user_id=1)
    out = await _svc(_StubRepo(rows=[node])).update(3, DeptUpdate(parent_id=None), scope=scope)
    assert out.parent_id is None


@pytest.mark.asyncio
async def test_update_move_to_nonexistent_parent_raises_404() -> None:
    # 移到不存在的父部门 → dept.PARENT_NOT_FOUND（parent 预检在防环前）。
    node = _dept(3, code="B")
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(rows=[node])).update(3, DeptUpdate(parent_id=99))
    assert exc.value.code == "dept.PARENT_NOT_FOUND"
    assert exc.value.status_code == 404


# ---- update：code 唯一 + NOT_FOUND -----------------------------------------


@pytest.mark.asyncio
async def test_update_code_duplicate_raises_409() -> None:
    node = _dept(3, code="B")
    taken = _dept(7, code="TAKEN")
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(rows=[node], by_code={"TAKEN": taken})).update(
            3, DeptUpdate(code="TAKEN")
        )
    assert exc.value.code == "dept.CODE_DUPLICATE"


@pytest.mark.asyncio
async def test_update_same_code_ok() -> None:
    # code 改成自身现值 → 不触发唯一冲突（仅改其它字段）。
    node = _dept(3, code="B")
    out = await _svc(_StubRepo(rows=[node], by_code={"B": node})).update(
        3, DeptUpdate(code="B", name="新名")
    )
    assert out.name == "新名"


@pytest.mark.asyncio
async def test_update_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).update(999, DeptUpdate(name="x"))
    assert exc.value.code == "dept.NOT_FOUND"
    assert exc.value.status_code == 404


# ---- delete：RESTRICT 有子禁删 ---------------------------------------------


@pytest.mark.asyncio
async def test_delete_with_children_raises_409() -> None:
    node = _dept(2, code="A")
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(rows=[node], children=3)).delete(2)
    assert exc.value.code == "dept.HAS_CHILDREN"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_leaf_ok() -> None:
    node = _dept(4, code="C")
    repo = _StubRepo(rows=[node], children=0)
    await _svc(repo).delete(4)
    assert await repo.get(4) is None


@pytest.mark.asyncio
async def test_delete_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).delete(999)
    assert exc.value.code == "dept.NOT_FOUND"


# ---- 分页 envelope ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_pagination_envelope() -> None:
    rows = [_dept(i, code=f"D{i}") for i in range(1, 24)]  # 23 条 → 边界 total_pages=3
    page = await _svc(_StubRepo(rows=rows)).list_(page=2, size=10)
    assert page.page == 2
    assert page.size == 10
    assert page.total == 23
    assert page.total_pages == 3
    assert len(page.items) == 10


@pytest.mark.asyncio
async def test_list_empty_returns_zero_total_pages() -> None:
    page = await _svc(_StubRepo()).list_(page=1, size=20)
    assert page.items == []
    assert page.total == 0
    assert page.total_pages == 0
