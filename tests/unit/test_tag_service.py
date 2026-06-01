"""TagService 单元测试。

stub repo 覆盖 service 自己拥有的业务规则分支：NOT_FOUND (404) 和
NAME_DUPLICATE (409)。DB 侧的约束（``UniqueConstraint`` 竞态兜底）由
集成测试守门。
"""

from __future__ import annotations

from typing import Any

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.tag.schemas import TagCreate, TagUpdate
from admin_platform.domains.tag.service import TagService


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

    async def find_by_name(self, name: str) -> Any | None:
        for row in self.rows.values():
            if row["name"] == name:
                return type("_Row", (), row)
        return None

    async def create(self, payload: TagCreate) -> dict[str, Any]:
        next_id = max(self.rows, default=0) + 1
        row: dict[str, Any] = {"id": next_id, **payload.model_dump()}
        self.rows[next_id] = row
        return row

    async def update(self, item_id: int, payload: TagUpdate) -> dict[str, Any] | None:
        row = self.rows.get(item_id)
        if row is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            row[key] = value
        return row

    async def delete(self, item_id: int) -> bool:
        return self.rows.pop(item_id, None) is not None


@pytest.mark.asyncio
async def test_get_raises_when_missing() -> None:
    svc = TagService(_StubRepo())  # type: ignore[arg-type]
    with pytest.raises(AppError) as exc:
        await svc.get(999)
    assert exc.value.code == "admin_platform.TAG_NOT_FOUND"
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_returns_read_dto() -> None:
    svc = TagService(_StubRepo())  # type: ignore[arg-type]
    out = await svc.create(TagCreate(name="urgent"))
    assert out.id == 1
    assert out.name == "urgent"


@pytest.mark.asyncio
async def test_create_with_duplicate_name_raises_409() -> None:
    svc = TagService(_StubRepo())  # type: ignore[arg-type]
    await svc.create(TagCreate(name="urgent"))
    with pytest.raises(AppError) as exc:
        await svc.create(TagCreate(name="urgent"))
    assert exc.value.code == "admin_platform.TAG_NAME_DUPLICATE"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_to_other_existing_name_raises_409() -> None:
    svc = TagService(_StubRepo())  # type: ignore[arg-type]
    await svc.create(TagCreate(name="alpha"))
    second = await svc.create(TagCreate(name="beta"))
    with pytest.raises(AppError) as exc:
        await svc.update(second.id, TagUpdate(name="alpha"))
    assert exc.value.code == "admin_platform.TAG_NAME_DUPLICATE"


@pytest.mark.asyncio
async def test_update_with_same_name_on_same_id_allowed() -> None:
    svc = TagService(_StubRepo())  # type: ignore[arg-type]
    created = await svc.create(TagCreate(name="alpha"))
    updated = await svc.update(created.id, TagUpdate(name="alpha"))
    assert updated.name == "alpha"


@pytest.mark.asyncio
async def test_delete_missing_raises() -> None:
    svc = TagService(_StubRepo())  # type: ignore[arg-type]
    with pytest.raises(AppError) as exc:
        await svc.delete(999)
    assert exc.value.code == "admin_platform.TAG_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_returns_pagination_envelope() -> None:
    repo = _StubRepo()
    svc = TagService(repo)  # type: ignore[arg-type]
    for i in range(23):
        await repo.create(TagCreate(name=f"tag-{i}"))
    page = await svc.list_(page=2, size=10)
    assert page.page == 2
    assert page.total == 23
    assert page.total_pages == 3
    assert len(page.items) == 10
    assert page.items[0].id == 11


@pytest.mark.asyncio
async def test_list_empty_returns_zero_total_pages() -> None:
    svc = TagService(_StubRepo())  # type: ignore[arg-type]
    page = await svc.list_(page=1, size=20)
    assert page.items == []
    assert page.total == 0
    assert page.total_pages == 0
