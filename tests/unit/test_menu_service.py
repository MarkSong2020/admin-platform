"""MenuService 单元测试 —— stub repository 覆盖 NOT_FOUND 分支。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.menu.schemas import MenuCreate, MenuUpdate
from admin_platform.domains.menu.service import MenuService

# 固定时间戳 —— stub 必须完整镜像 ORM 行（含 TimestampMixin 的 created_at/updated_at），
# 否则 MenuRead.model_validate 缺字段校验失败（原则 #4：mock 完整镜像真实 API）。
_TS = datetime(2026, 1, 1, tzinfo=UTC)


class _StubRepo:
    def __init__(self) -> None:
        self.rows: dict[int, dict[str, Any]] = {}

    async def list_paginated(self, page: int, size: int) -> list[dict[str, Any]]:
        start = (page - 1) * size
        return list(self.rows.values())[start : start + size]

    async def count(self) -> int:
        return len(self.rows)

    async def get(self, item_id: int) -> dict[str, Any] | None:
        return self.rows.get(item_id)

    async def create(self, payload: MenuCreate) -> dict[str, Any]:
        next_id = max(self.rows, default=0) + 1
        row: dict[str, Any] = {
            "id": next_id,
            **payload.model_dump(),
            "created_at": _TS,
            "updated_at": _TS,
        }
        self.rows[next_id] = row
        return row

    async def update(self, item_id: int, payload: MenuUpdate) -> dict[str, Any] | None:
        row = self.rows.get(item_id)
        if row is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            row[key] = value
        return row

    async def delete(self, item_id: int) -> bool:
        return self.rows.pop(item_id, None) is not None

    async def acquire_tree_lock(self) -> None:
        return None

    async def count_children(self, menu_id: int) -> int:
        return sum(1 for r in self.rows.values() if r.get("parent_id") == menu_id)

    async def list_descendant_menu_ids(self, menu_id: int) -> frozenset[int]:
        # BFS 向下收集子孙（含自身），镜像递归 CTE 语义供防环单测。
        found = {menu_id}
        frontier = [menu_id]
        while frontier:
            current = frontier.pop()
            for row in self.rows.values():
                if row.get("parent_id") == current and row["id"] not in found:
                    found.add(row["id"])
                    frontier.append(row["id"])
        return frozenset(found)


@pytest.mark.asyncio
async def test_get_raises_when_missing() -> None:
    svc = MenuService(_StubRepo())  # type: ignore[arg-type]
    with pytest.raises(AppError) as exc:
        await svc.get(999)
    assert exc.value.code == "menu.NOT_FOUND"
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_returns_read_dto() -> None:
    svc = MenuService(_StubRepo())  # type: ignore[arg-type]
    out = await svc.create(MenuCreate(name="x", menu_type="C"))
    assert out.id == 1
    assert out.name == "x"


@pytest.mark.asyncio
async def test_delete_missing_raises() -> None:
    svc = MenuService(_StubRepo())  # type: ignore[arg-type]
    with pytest.raises(AppError) as exc:
        await svc.delete(999)
    assert exc.value.code == "menu.NOT_FOUND"


@pytest.mark.asyncio
async def test_list_returns_pagination_envelope() -> None:
    repo = _StubRepo()
    svc = MenuService(repo)  # type: ignore[arg-type]
    # seed 23 个，让 total_pages != size 边界。
    for i in range(23):
        await repo.create(MenuCreate(name=f"item-{i}", menu_type="C"))
    page = await svc.list_(page=2, size=10)
    assert page.page == 2
    assert page.size == 10
    assert page.total == 23
    assert page.total_pages == 3
    assert len(page.items) == 10
    assert page.items[0].id == 11


@pytest.mark.asyncio
async def test_list_empty_returns_zero_total_pages() -> None:
    svc = MenuService(_StubRepo())  # type: ignore[arg-type]
    page = await svc.list_(page=1, size=20)
    assert page.items == []
    assert page.total == 0
    assert page.total_pages == 0


@pytest.mark.asyncio
async def test_create_parent_not_found_raises() -> None:
    svc = MenuService(_StubRepo())  # type: ignore[arg-type]
    with pytest.raises(AppError) as exc:
        await svc.create(MenuCreate(name="x", menu_type="C", parent_id=999))
    assert exc.value.code == "menu.PARENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_missing_raises() -> None:
    svc = MenuService(_StubRepo())  # type: ignore[arg-type]
    with pytest.raises(AppError) as exc:
        await svc.update(999, MenuUpdate(name="x"))
    assert exc.value.code == "menu.NOT_FOUND"


@pytest.mark.asyncio
async def test_update_parent_not_found_raises() -> None:
    repo = _StubRepo()
    svc = MenuService(repo)  # type: ignore[arg-type]
    a = (await svc.create(MenuCreate(name="A", menu_type="C"))).id
    with pytest.raises(AppError) as exc:
        await svc.update(a, MenuUpdate(parent_id=999))
    assert exc.value.code == "menu.PARENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_into_self_raises_cycle() -> None:
    repo = _StubRepo()
    svc = MenuService(repo)  # type: ignore[arg-type]
    a = (await svc.create(MenuCreate(name="A", menu_type="M"))).id
    with pytest.raises(AppError) as exc:
        await svc.update(a, MenuUpdate(parent_id=a))
    assert exc.value.code == "menu.CYCLE"


@pytest.mark.asyncio
async def test_update_into_descendant_raises_cycle() -> None:
    repo = _StubRepo()
    svc = MenuService(repo)  # type: ignore[arg-type]
    a = (await svc.create(MenuCreate(name="A", menu_type="M"))).id
    b = (await svc.create(MenuCreate(name="B", menu_type="C", parent_id=a))).id
    # 把 A 移到其子 B 之下 → 成环。
    with pytest.raises(AppError) as exc:
        await svc.update(a, MenuUpdate(parent_id=b))
    assert exc.value.code == "menu.CYCLE"


@pytest.mark.asyncio
async def test_delete_with_children_raises() -> None:
    repo = _StubRepo()
    svc = MenuService(repo)  # type: ignore[arg-type]
    a = (await svc.create(MenuCreate(name="A", menu_type="M"))).id
    await svc.create(MenuCreate(name="B", menu_type="C", parent_id=a))
    with pytest.raises(AppError) as exc:
        await svc.delete(a)
    assert exc.value.code == "menu.HAS_CHILDREN"
