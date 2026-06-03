"""Task 8 user service 单测 —— username 租户内唯一(409) / 缺失(404)。

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


class _StubRepo:
    """最小 stub —— 只实现各用例会调到的方法。"""

    def __init__(self, existing: User | None = None) -> None:
        self.existing = existing

    async def find_by_username(self, username: str) -> User | None:
        if self.existing is not None and self.existing.username == username:
            return self.existing
        return None

    async def create(self, payload: UserCreate, *, password_hash: str) -> User:
        obj = User(
            username=payload.username, nickname=payload.nickname, password_hash=password_hash
        )
        obj.id = 2
        obj.tenant_id = 1
        obj.status = "active"
        obj.is_platform_admin = False
        return obj

    async def get(self, user_id: int) -> User | None:
        return None

    async def update(self, user_id: int, payload: UserUpdate, *, password_hash: str | None) -> None:
        return None

    async def delete(self, user_id: int) -> bool:
        return False


def _svc(repo: _StubRepo) -> UserService:
    return UserService(cast("UserRepository", repo))


@pytest.mark.asyncio
async def test_create_duplicate_username_raises_409() -> None:
    existing = User(username="alice", tenant_id=1, password_hash="x", nickname="")
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo(existing=existing)).create(UserCreate(username="alice", password="pw"))
    assert exc.value.status_code == 409
    assert exc.value.code == "admin_platform.USERNAME_DUPLICATE"


@pytest.mark.asyncio
async def test_create_new_username_ok() -> None:
    out = await _svc(_StubRepo()).create(UserCreate(username="bob", password="pw", nickname="Bob"))
    assert out.username == "bob"
    assert out.is_platform_admin is False


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
