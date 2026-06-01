"""TodoService 单元测试。

stub repo 覆盖 service 自己拥有的业务规则分支：NOT_FOUND (404)、
TITLE_DUPLICATE (409)、TAG_NOT_FOUND (422)、分页数学、以及 tag 解析
语义（None / [] / [int]）。DB 侧约束由 ``tests/integration/test_todo_db.py``
守门。

v0.5.1 — TodoService 现在还需要 ``TagRepository`` 来做多对多关联管理；
两个 stub 都遵循相同的内存形状。
"""

from __future__ import annotations

from typing import Any

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.tag.schemas import TagCreate
from admin_platform.domains.todo.models import TodoStatus
from admin_platform.domains.todo.schemas import TodoCreate, TodoUpdate
from admin_platform.domains.todo.service import TodoService


class _StubTagRepo:
    def __init__(self) -> None:
        self.rows: dict[int, dict[str, Any]] = {}

    async def create(self, payload: TagCreate) -> dict[str, Any]:
        next_id = max(self.rows, default=0) + 1
        row: dict[str, Any] = {"id": next_id, **payload.model_dump()}
        self.rows[next_id] = row
        return row

    async def get_many_by_ids(self, ids: list[int]) -> list[Any]:
        # service 比较 ``tag.id``，所以返回类对象 proxy（TagRead 通过
        # from_attributes=True 从这个对象构造）。
        return [type("_Row", (), self.rows[i])() for i in ids if i in self.rows]


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

    async def find_by_title(self, title: str) -> Any | None:
        for row in self.rows.values():
            if row["title"] == title:
                return type("_Row", (), row)
        return None

    async def create(self, payload: TodoCreate, *, tags: list[Any] | None = None) -> dict[str, Any]:
        next_id = max(self.rows, default=0) + 1
        row: dict[str, Any] = {
            "id": next_id,
            "status": TodoStatus.OPEN,
            "tags": [_tag_to_dict(t) for t in (tags or [])],
            **payload.model_dump(exclude={"tag_ids"}),
        }
        self.rows[next_id] = row
        return row

    async def update(
        self, item_id: int, payload: TodoUpdate, *, tags: list[Any] | None = None
    ) -> dict[str, Any] | None:
        row = self.rows.get(item_id)
        if row is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True, exclude={"tag_ids"}).items():
            row[key] = value
        if tags is not None:
            row["tags"] = [_tag_to_dict(t) for t in tags]
        return row

    async def delete(self, item_id: int) -> bool:
        return self.rows.pop(item_id, None) is not None


def _tag_to_dict(tag: Any) -> dict[str, Any]:
    return {"id": tag.id, "name": tag.name}


def _make_svc() -> TodoService:
    return TodoService(_StubRepo(), _StubTagRepo())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_raises_when_missing() -> None:
    svc = _make_svc()
    with pytest.raises(AppError) as exc:
        await svc.get(999)
    assert exc.value.code == "admin_platform.TODO_NOT_FOUND"
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_returns_read_dto_with_empty_tags() -> None:
    svc = _make_svc()
    out = await svc.create(TodoCreate(title="buy milk"))
    assert out.id == 1
    assert out.title == "buy milk"
    assert out.status == TodoStatus.OPEN
    assert out.tags == []


@pytest.mark.asyncio
async def test_create_with_tag_ids_associates_tags() -> None:
    tag_repo = _StubTagRepo()
    await tag_repo.create(TagCreate(name="urgent"))
    await tag_repo.create(TagCreate(name="home"))
    svc = TodoService(_StubRepo(), tag_repo)  # type: ignore[arg-type]

    out = await svc.create(TodoCreate(title="buy milk", tag_ids=[1, 2]))
    assert {t.name for t in out.tags} == {"urgent", "home"}


@pytest.mark.asyncio
async def test_create_with_missing_tag_id_raises_422() -> None:
    tag_repo = _StubTagRepo()
    await tag_repo.create(TagCreate(name="urgent"))
    svc = TodoService(_StubRepo(), tag_repo)  # type: ignore[arg-type]

    with pytest.raises(AppError) as exc:
        await svc.create(TodoCreate(title="buy milk", tag_ids=[1, 999]))
    assert exc.value.code == "admin_platform.TODO_TAG_NOT_FOUND"
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_with_duplicate_tag_ids_deduplicates() -> None:
    tag_repo = _StubTagRepo()
    await tag_repo.create(TagCreate(name="urgent"))
    svc = TodoService(_StubRepo(), tag_repo)  # type: ignore[arg-type]

    out = await svc.create(TodoCreate(title="buy milk", tag_ids=[1, 1, 1]))
    assert len(out.tags) == 1


@pytest.mark.asyncio
async def test_update_with_empty_tag_ids_clears_tags() -> None:
    tag_repo = _StubTagRepo()
    await tag_repo.create(TagCreate(name="urgent"))
    svc = TodoService(_StubRepo(), tag_repo)  # type: ignore[arg-type]

    created = await svc.create(TodoCreate(title="buy milk", tag_ids=[1]))
    assert len(created.tags) == 1
    cleared = await svc.update(created.id, TodoUpdate(tag_ids=[]))
    assert cleared.tags == []


@pytest.mark.asyncio
async def test_update_with_none_tag_ids_leaves_tags_untouched() -> None:
    tag_repo = _StubTagRepo()
    await tag_repo.create(TagCreate(name="urgent"))
    svc = TodoService(_StubRepo(), tag_repo)  # type: ignore[arg-type]

    created = await svc.create(TodoCreate(title="buy milk", tag_ids=[1]))
    # PATCH 一个非 tag 字段 —— tag_ids 缺省 ⇒ tag 关联必须保留。
    updated = await svc.update(created.id, TodoUpdate(status=TodoStatus.DONE))
    assert updated.status == TodoStatus.DONE
    assert len(updated.tags) == 1


@pytest.mark.asyncio
async def test_create_with_duplicate_title_raises_409() -> None:
    svc = _make_svc()
    await svc.create(TodoCreate(title="buy milk"))
    with pytest.raises(AppError) as exc:
        await svc.create(TodoCreate(title="buy milk"))
    assert exc.value.code == "admin_platform.TODO_TITLE_DUPLICATE"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_to_existing_other_title_raises_409() -> None:
    svc = _make_svc()
    await svc.create(TodoCreate(title="alpha"))
    second = await svc.create(TodoCreate(title="beta"))
    with pytest.raises(AppError) as exc:
        await svc.update(second.id, TodoUpdate(title="alpha"))
    assert exc.value.code == "admin_platform.TODO_TITLE_DUPLICATE"


@pytest.mark.asyncio
async def test_update_with_same_title_on_same_id_is_allowed() -> None:
    svc = _make_svc()
    created = await svc.create(TodoCreate(title="alpha"))
    updated = await svc.update(created.id, TodoUpdate(title="alpha", status=TodoStatus.DONE))
    assert updated.title == "alpha"
    assert updated.status == TodoStatus.DONE


@pytest.mark.asyncio
async def test_delete_missing_raises() -> None:
    svc = _make_svc()
    with pytest.raises(AppError) as exc:
        await svc.delete(999)
    assert exc.value.code == "admin_platform.TODO_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_returns_pagination_envelope() -> None:
    svc = _make_svc()
    for i in range(23):
        await svc.create(TodoCreate(title=f"item-{i}"))
    page = await svc.list_(page=2, size=10)
    assert page.page == 2
    assert page.size == 10
    assert page.total == 23
    assert page.total_pages == 3
    assert len(page.items) == 10
    assert page.items[0].id == 11


@pytest.mark.asyncio
async def test_list_empty_returns_zero_total_pages() -> None:
    svc = _make_svc()
    page = await svc.list_(page=1, size=20)
    assert page.items == []
    assert page.total == 0
    assert page.total_pages == 0
