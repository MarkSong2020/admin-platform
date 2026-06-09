"""NoticeService 单元测试 —— stub repository 覆盖业务分支（DB-free）。

service 用 ``NoticeRead.model_validate`` 把 ORM 行转 DTO，故 stub 返回预置全字段的 transient
``Notice``（``default=`` 只在 flush 生效，transient 需手工补齐）。覆盖：分页 envelope / 过滤透传 /
get|update|delete 的 404。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.notice.models import Notice
from admin_platform.domains.notice.schemas import NoticeCreate, NoticeUpdate
from admin_platform.domains.notice.service import NoticeService

_TS = datetime(2026, 6, 9, tzinfo=UTC)


def _notice(nid: int, *, title: str = "公告", notice_type: str = "notification") -> Notice:
    obj = Notice(title=title, notice_type=notice_type, content="正文")
    obj.id = nid
    obj.status = "active"
    obj.remark = None
    obj.created_at = _TS
    obj.updated_at = _TS
    return obj


class _StubRepo:
    """最小 stub —— 记录过滤入参供断言，按预置行返回。"""

    def __init__(self, *, rows: list[Notice] | None = None) -> None:
        self._rows = {row.id: row for row in (rows or [])}
        self.last_filters: dict[str, object] = {}

    async def list_paginated(
        self, *, notice_type: str | None, status: str | None, page: int, size: int
    ) -> list[Notice]:
        self.last_filters = {"notice_type": notice_type, "status": status}
        return list(self._rows.values())

    async def count(self, *, notice_type: str | None, status: str | None) -> int:
        return len(self._rows)

    async def get(self, item_id: int) -> Notice | None:
        return self._rows.get(item_id)

    async def create(self, payload: NoticeCreate) -> Notice:
        return _notice(1, title=payload.title, notice_type=payload.notice_type)

    async def update(self, item_id: int, payload: NoticeUpdate) -> Notice | None:
        row = self._rows.get(item_id)
        if row is None:
            return None
        if payload.title is not None:
            row.title = payload.title
        return row

    async def delete(self, item_id: int) -> bool:
        return self._rows.pop(item_id, None) is not None


def _svc(repo: _StubRepo) -> NoticeService:
    return NoticeService(repo)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_pagination_envelope() -> None:
    repo = _StubRepo(rows=[_notice(i) for i in range(1, 4)])
    page = await _svc(repo).list_(notice_type=None, status=None, page=1, size=10)
    assert page.total == 3
    assert page.total_pages == 1
    assert len(page.items) == 3


@pytest.mark.asyncio
async def test_list_passes_filters_through() -> None:
    repo = _StubRepo(rows=[])
    await _svc(repo).list_(notice_type="announcement", status="active", page=1, size=20)
    assert repo.last_filters == {"notice_type": "announcement", "status": "active"}


@pytest.mark.asyncio
async def test_get_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).get(999)
    assert exc.value.code == "notice.NOT_FOUND"
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_returns_read_dto() -> None:
    out = await _svc(_StubRepo()).create(
        NoticeCreate(title="发布", notice_type="announcement", content="x")
    )
    assert out.id == 1
    assert out.title == "发布"


@pytest.mark.asyncio
async def test_update_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).update(999, NoticeUpdate(title="改"))
    assert exc.value.code == "notice.NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).delete(999)
    assert exc.value.code == "notice.NOT_FOUND"
