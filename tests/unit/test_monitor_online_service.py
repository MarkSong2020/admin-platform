"""在线用户 service 单测（P4，DB-free，stub repo）——强制下线分支 + 列表映射。

测真实 service 行为：用 duck-typed fake repo（镜像 MonitorRepository 在线方法契约）驱动
force_logout 的「找到→撤销+返回用户名」与「不存在→404 且不撤销」两分支，及 list 的 DTO 映射。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.monitor.repository import MonitorRepository
from admin_platform.domains.monitor.service import MonitorService

pytestmark = pytest.mark.anyio

_SID = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _FakeRepo:
    """镜像 MonitorRepository 在线方法契约。row 用 SimpleNamespace（service 只按属性读）。"""

    def __init__(self, *, session: SimpleNamespace | None, rows: list[Any] | None = None) -> None:
        self._session = session
        self._rows = rows or []
        self.revoked: list[tuple[uuid.UUID, str]] = []
        self.locked: list[int] = []

    async def get_online_session(self, family_id: uuid.UUID, *, now: datetime) -> Any:
        return self._session

    async def acquire_user_lock(self, user_id: int) -> None:
        self.locked.append(user_id)

    async def revoke_online_session(
        self, family_id: uuid.UUID, *, reason: str, now: datetime
    ) -> int:
        self.revoked.append((family_id, reason))
        return 1

    async def list_online_sessions(self, *, now: datetime, page: int, size: int) -> list[Any]:
        return self._rows

    async def count_online_sessions(self, *, now: datetime) -> int:
        return len(self._rows)


def _row(**kw: Any) -> SimpleNamespace:
    now = datetime.now(UTC)
    base = {
        "session_id": _SID,
        "user_id": 7,
        "username": "bob",
        "login_time": now,
        "last_active_time": now,
        "expires_at": now,
    }
    base.update(kw)
    return SimpleNamespace(**base)


async def test_force_logout_revokes_and_returns_username() -> None:
    fake = _FakeRepo(session=_row(username="bob"))
    svc = MonitorService(cast(MonitorRepository, fake))
    username = await svc.force_logout(_SID)
    assert username == "bob"
    assert fake.revoked == [(_SID, "forced_logout")]


async def test_force_logout_404_when_session_absent() -> None:
    fake = _FakeRepo(session=None)
    svc = MonitorService(cast(MonitorRepository, fake))
    with pytest.raises(AppError) as exc:
        await svc.force_logout(_SID)
    assert exc.value.code == "monitor.ONLINE_SESSION_NOT_FOUND"
    assert exc.value.status_code == 404
    assert fake.revoked == []  # 不存在的会话不触发撤销


async def test_list_online_sessions_maps_rows() -> None:
    fake = _FakeRepo(session=None, rows=[_row(user_id=7, username="bob")])
    svc = MonitorService(cast(MonitorRepository, fake))
    page = await svc.list_online_sessions(page=1, size=20)
    assert page.total == 1
    assert page.total_pages == 1
    item = page.items[0]
    assert item.session_id == str(_SID)  # UUID 转字符串
    assert item.user_id == 7
    assert item.username == "bob"
