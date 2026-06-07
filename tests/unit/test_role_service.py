"""RoleService 单元测试 —— stub repository 隔离业务规则（DB-free）。

不是 mock 行为断言：测的是 service 在「repo 说存在/不存在/code 被占」等前置条件下**自己**抛
什么领域错误码（``role.*``）；repo 只提供前置条件（DI 缝）。覆盖：
code 重复 409 / 改 code 撞占用 409 / NOT_FOUND 404 / 正常 CRUD / 分页 envelope。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.role.models import Role
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.role.schemas import RoleCreate, RoleUpdate
from admin_platform.domains.role.service import RoleService

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _role(rid: int, *, code: str, name: str = "role", data_scope: str = "self") -> Role:
    """构造预置全部 ``RoleRead`` 字段的 transient Role（不入库）。

    SQLAlchemy 的 ``default=`` 只在 flush 生效，transient 实例需手工补齐，否则
    ``RoleRead.model_validate`` 校验缺字段失败。sort_order / status 取固定缺省（用例不变它们）。
    """
    obj = Role(name=name, code=code)
    obj.id = rid
    obj.data_scope = data_scope
    obj.sort_order = 0
    obj.status = "active"
    obj.created_at = _TS
    obj.updated_at = _TS
    return obj


class _StubRepo:
    """最小 stub —— 只实现各用例会调到的方法。"""

    def __init__(
        self,
        *,
        rows: list[Role] | None = None,
        by_code: dict[str, Role] | None = None,
    ) -> None:
        self._rows = {row.id: row for row in (rows or [])}
        self._by_code = by_code or {}

    async def list_paginated(self, page: int, size: int) -> list[Role]:
        start = (page - 1) * size
        return list(self._rows.values())[start : start + size]

    async def count(self) -> int:
        return len(self._rows)

    async def get(self, role_id: int) -> Role | None:
        return self._rows.get(role_id)

    async def find_by_code(self, code: str) -> Role | None:
        return self._by_code.get(code)

    async def create(self, payload: RoleCreate) -> Role:
        return _role(1, code=payload.code, name=payload.name, data_scope=payload.data_scope)

    async def update(self, role_id: int, payload: RoleUpdate) -> Role | None:
        row = self._rows.get(role_id)
        if row is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        return row

    async def delete(self, role_id: int) -> bool:
        return self._rows.pop(role_id, None) is not None


def _svc(repo: _StubRepo) -> RoleService:
    return RoleService(cast("RoleRepository", repo))


# ---- get / create ----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).get(999)
    assert exc.value.code == "role.NOT_FOUND"
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_ok() -> None:
    out = await _svc(_StubRepo()).create(RoleCreate(name="管理员", code="admin", data_scope="all"))
    assert out.id == 1
    assert out.code == "admin"
    assert out.data_scope == "all"


@pytest.mark.asyncio
async def test_create_duplicate_code_raises_409() -> None:
    existing = _role(5, code="admin")
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(by_code={"admin": existing})).create(
            RoleCreate(name="dup", code="admin")
        )
    assert exc.value.code == "role.CODE_DUPLICATE"
    assert exc.value.status_code == 409


# ---- update：code 唯一 + NOT_FOUND -----------------------------------------


@pytest.mark.asyncio
async def test_update_code_duplicate_raises_409() -> None:
    node = _role(3, code="B")
    taken = _role(7, code="TAKEN")
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(rows=[node], by_code={"TAKEN": taken})).update(
            3, RoleUpdate(code="TAKEN")
        )
    assert exc.value.code == "role.CODE_DUPLICATE"


@pytest.mark.asyncio
async def test_update_same_code_ok() -> None:
    # code 改成自身现值 → 不触发唯一冲突（仅改其它字段）。
    node = _role(3, code="B")
    out = await _svc(_StubRepo(rows=[node], by_code={"B": node})).update(
        3, RoleUpdate(code="B", name="新名")
    )
    assert out.name == "新名"


@pytest.mark.asyncio
async def test_update_data_scope_ok() -> None:
    node = _role(3, code="B", data_scope="self")
    out = await _svc(_StubRepo(rows=[node])).update(3, RoleUpdate(data_scope="self_dept_and_below"))
    assert out.data_scope == "self_dept_and_below"


@pytest.mark.asyncio
async def test_update_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).update(999, RoleUpdate(name="x"))
    assert exc.value.code == "role.NOT_FOUND"
    assert exc.value.status_code == 404


# ---- delete ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_ok() -> None:
    node = _role(4, code="C")
    repo = _StubRepo(rows=[node])
    await _svc(repo).delete(4)
    assert await repo.get(4) is None


@pytest.mark.asyncio
async def test_delete_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).delete(999)
    assert exc.value.code == "role.NOT_FOUND"


# ---- 分页 envelope ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_pagination_envelope() -> None:
    rows = [_role(i, code=f"R{i}") for i in range(1, 24)]  # 23 条 → 边界 total_pages=3
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
