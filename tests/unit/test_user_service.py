"""user service 单测 —— username 全局唯一(409) / 缺失(404)。

用 stub repository 隔离 service 业务逻辑（DI 缝，DB-free）；不是 mock 行为断言：测的是
service 在"repo 说已存在/不存在"时**自己**抛什么领域错误码，repo 只提供前置条件。
"""

from __future__ import annotations

from typing import cast

import pytest

from admin_platform.core.errors import AppError
from admin_platform.domains.user.models import User
from admin_platform.domains.user.repository import UserRepository
from admin_platform.domains.user.schemas import UserCreate, UserUpdate
from admin_platform.domains.user.service import UserService


def _user(uid: int, username: str, *, nickname: str = "", is_super_admin: bool = False) -> User:
    """构造 transient User，预置 UserRead 需要的全部字段（不入库）。"""
    obj = User(username=username, nickname=nickname, password_hash="x")
    obj.id = uid
    obj.status = "active"
    obj.is_super_admin = is_super_admin
    return obj


class _StubRepo:
    """最小 stub —— 只实现各用例会调到的方法。"""

    def __init__(
        self,
        existing: User | None = None,
        rows: list[User] | None = None,
        updated: User | None = None,
        get_row: User | None = None,
        super_admin_count: int = 0,
    ) -> None:
        self.existing = existing
        self.rows = rows if rows is not None else []
        self.updated = updated
        self.get_row = get_row
        self.super_admin_count = super_admin_count

    async def find_by_username(self, username: str) -> User | None:
        if self.existing is not None and self.existing.username == username:
            return self.existing
        return None

    async def create(self, payload: UserCreate, *, password_hash: str) -> User:
        return _user(2, payload.username, nickname=payload.nickname)

    async def get(self, user_id: int) -> User | None:
        return self.get_row

    async def list_paginated(self, page: int, size: int) -> list[User]:
        return self.rows

    async def count(self) -> int:
        return len(self.rows)

    async def count_super_admins(self) -> int:
        return self.super_admin_count

    async def update(
        self, user_id: int, payload: UserUpdate, *, password_hash: str | None
    ) -> User | None:
        return self.updated

    async def delete(self, user_id: int) -> bool:
        return self.get_row is not None


def _svc(repo: _StubRepo) -> UserService:
    return UserService(cast("UserRepository", repo))


@pytest.mark.asyncio
async def test_create_duplicate_username_raises_409() -> None:
    existing = User(username="alice", password_hash="x", nickname="")
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(existing=existing)).create(UserCreate(username="alice", password="pw"))
    assert exc.value.status_code == 409
    assert exc.value.code == "admin_platform.USERNAME_DUPLICATE"


@pytest.mark.asyncio
async def test_create_new_username_ok() -> None:
    out = await _svc(_StubRepo()).create(UserCreate(username="bob", password="pw", nickname="Bob"))
    assert out.username == "bob"
    assert out.is_super_admin is False


@pytest.mark.asyncio
async def test_get_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).get(999)
    assert exc.value.status_code == 404
    assert exc.value.code == "admin_platform.USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).delete(999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_returns_page() -> None:
    rows = [_user(1, "alice"), _user(2, "bob")]
    page = await _svc(_StubRepo(rows=rows)).list_(page=1, size=20)
    assert {u.username for u in page.items} == {"alice", "bob"}
    assert page.total == 2
    assert page.total_pages == 1


@pytest.mark.asyncio
async def test_update_existing_returns_user() -> None:
    out = await _svc(_StubRepo(updated=_user(5, "carol", nickname="Carol"))).update(
        5, UserUpdate(nickname="Carol")
    )
    assert out.id == 5
    assert out.nickname == "Carol"


@pytest.mark.asyncio
async def test_update_with_password_rehashes() -> None:
    # 覆盖 update 里 payload.password 非 None → hash_password 分支。
    out = await _svc(_StubRepo(updated=_user(5, "carol"))).update(
        5, UserUpdate(password="new-strong-password")
    )
    assert out.id == 5


@pytest.mark.asyncio
async def test_update_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(updated=None)).update(999, UserUpdate(nickname="x"))
    assert exc.value.status_code == 404


# ---- 最后一个超管保护（P0.9 review C：保证系统至少一个超管入口）----


@pytest.mark.asyncio
async def test_delete_last_super_admin_raises_409() -> None:
    admin = _user(1, "root", is_super_admin=True)
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(get_row=admin, super_admin_count=1)).delete(1)
    assert exc.value.status_code == 409
    assert exc.value.code == "admin_platform.LAST_SUPER_ADMIN"


@pytest.mark.asyncio
async def test_delete_super_admin_when_others_exist_ok() -> None:
    # 还有其他超管（count=2）→ 删一个不抛。
    admin = _user(1, "root", is_super_admin=True)
    await _svc(_StubRepo(get_row=admin, super_admin_count=2)).delete(1)


@pytest.mark.asyncio
async def test_disable_last_super_admin_raises_409() -> None:
    admin = _user(1, "root", is_super_admin=True)
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(get_row=admin, super_admin_count=1)).update(
            1, UserUpdate(status="disabled")
        )
    assert exc.value.status_code == 409
    assert exc.value.code == "admin_platform.LAST_SUPER_ADMIN"
