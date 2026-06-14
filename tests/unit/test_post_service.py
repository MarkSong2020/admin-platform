"""PostService 单元测试 —— stub repository 隔离业务规则（DB-free）。

不是 mock 行为断言：测的是 service 在「repo 说存在/不存在/code 被占」等前置条件下**自己**抛
什么领域错误码（``post.*``）；repo 只提供前置条件（DI 缝）。覆盖：
code 重复 409 / 改 code 撞占用 409 / NOT_FOUND 404 / 正常 CRUD / 分页 envelope。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.post.models import Post
from admin_platform.domains.post.repository import PostRepository
from admin_platform.domains.post.schemas import PostCreate, PostListQuery, PostUpdate
from admin_platform.domains.post.service import PostService

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_Q = PostListQuery()  # 默认空过滤 + order=desc + order_by=None（用默认序）


def _post(pid: int, *, code: str, name: str = "post") -> Post:
    """构造预置全部 ``PostRead`` 字段的 transient Post（不入库）。

    SQLAlchemy 的 ``default=`` 只在 flush 生效，transient 实例需手工补齐，否则
    ``PostRead.model_validate`` 校验缺字段失败。sort_order / status 取固定缺省（用例不变它们）。
    """
    obj = Post(name=name, code=code)
    obj.id = pid
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
        rows: list[Post] | None = None,
        by_code: dict[str, Post] | None = None,
    ) -> None:
        self._rows = {row.id: row for row in (rows or [])}
        self._by_code = by_code or {}

    async def list_paginated(
        self, query: object, page: int, size: int, *, order_by: object
    ) -> list[Post]:
        start = (page - 1) * size
        return list(self._rows.values())[start : start + size]

    async def count(self, query: object) -> int:
        return len(self._rows)

    async def get(self, post_id: int) -> Post | None:
        return self._rows.get(post_id)

    async def find_by_code(self, code: str) -> Post | None:
        return self._by_code.get(code)

    async def create(self, payload: PostCreate) -> Post:
        return _post(1, code=payload.code, name=payload.name)

    async def update(self, post_id: int, payload: PostUpdate) -> Post | None:
        row = self._rows.get(post_id)
        if row is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        return row

    async def delete(self, post_id: int) -> bool:
        return self._rows.pop(post_id, None) is not None


def _svc(repo: _StubRepo) -> PostService:
    return PostService(cast("PostRepository", repo))


# ---- get / create ----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).get(999)
    assert exc.value.code == "post.NOT_FOUND"
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_ok() -> None:
    out = await _svc(_StubRepo()).create(PostCreate(name="项目经理", code="pm"))
    assert out.id == 1
    assert out.code == "pm"


@pytest.mark.asyncio
async def test_create_duplicate_code_raises_409() -> None:
    existing = _post(5, code="pm")
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(by_code={"pm": existing})).create(PostCreate(name="dup", code="pm"))
    assert exc.value.code == "post.CODE_DUPLICATE"
    assert exc.value.status_code == 409


# ---- update：code 唯一 + NOT_FOUND -----------------------------------------


@pytest.mark.asyncio
async def test_update_code_duplicate_raises_409() -> None:
    node = _post(3, code="B")
    taken = _post(7, code="TAKEN")
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(rows=[node], by_code={"TAKEN": taken})).update(
            3, PostUpdate(code="TAKEN")
        )
    assert exc.value.code == "post.CODE_DUPLICATE"


@pytest.mark.asyncio
async def test_update_same_code_ok() -> None:
    # code 改成自身现值 → 不触发唯一冲突（仅改其它字段）。
    node = _post(3, code="B")
    out = await _svc(_StubRepo(rows=[node], by_code={"B": node})).update(
        3, PostUpdate(code="B", name="新名")
    )
    assert out.name == "新名"


@pytest.mark.asyncio
async def test_update_sort_order_ok() -> None:
    node = _post(3, code="B")
    out = await _svc(_StubRepo(rows=[node])).update(3, PostUpdate(sort_order=9))
    assert out.sort_order == 9


@pytest.mark.asyncio
async def test_update_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).update(999, PostUpdate(name="x"))
    assert exc.value.code == "post.NOT_FOUND"
    assert exc.value.status_code == 404


# ---- delete ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_ok() -> None:
    node = _post(4, code="C")
    repo = _StubRepo(rows=[node])
    await _svc(repo).delete(4)
    assert await repo.get(4) is None


@pytest.mark.asyncio
async def test_delete_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).delete(999)
    assert exc.value.code == "post.NOT_FOUND"


# ---- 分页 envelope ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_pagination_envelope() -> None:
    rows = [_post(i, code=f"P{i}") for i in range(1, 24)]  # 23 条 → 边界 total_pages=3
    page = await _svc(_StubRepo(rows=rows)).list_(_Q, page=2, size=10)
    assert page.page == 2
    assert page.size == 10
    assert page.total == 23
    assert page.total_pages == 3
    assert len(page.items) == 10


@pytest.mark.asyncio
async def test_list_empty_returns_zero_total_pages() -> None:
    page = await _svc(_StubRepo()).list_(_Q, page=1, size=20)
    assert page.items == []
    assert page.total == 0
    assert page.total_pages == 0


@pytest.mark.asyncio
async def test_list_invalid_order_by_raises_422() -> None:
    """防注入守门：order_by 非 allowlist 字段 → 422，绝不进 SQL。"""
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).list_(
            PostListQuery(order_by="code'; DROP TABLE posts;--"), page=1, size=20
        )
    assert exc.value.status_code == 422
    assert exc.value.code == "framework.SORT_FIELD_INVALID"


@pytest.mark.asyncio
async def test_list_allowed_order_by_ok() -> None:
    """allowlist 内字段（sort_order）+ asc → 正常返回（不抛）。"""
    rows = [_post(i, code=f"P{i}") for i in range(1, 4)]
    page = await _svc(_StubRepo(rows=rows)).list_(
        PostListQuery(order_by="sort_order", order="asc"), page=1, size=20
    )
    assert page.total == 3
