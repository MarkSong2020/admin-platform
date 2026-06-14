"""user service 单测 —— username 全局唯一(409) / 缺失(404)。

用 stub repository 隔离 service 业务逻辑（DI 缝，DB-free）；不是 mock 行为断言：测的是
service 在"repo 说已存在/不存在"时**自己**抛什么领域错误码，repo 只提供前置条件。
"""

from __future__ import annotations

from typing import cast

import pytest

from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.errors import AppError
from admin_platform.domains.user.models import User
from admin_platform.domains.user.repository import UserRepository
from admin_platform.domains.user.schemas import UserCreate, UserListQuery, UserUpdate
from admin_platform.domains.user.service import UserService

_Q = UserListQuery()  # 默认空过滤 + order=desc + order_by=None（用默认序）


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
        # 记录最近一次 list/count 收到的过滤 + 排序 + scope，供 pass-through 断言。
        self.last_query: object | None = None
        self.last_order_by: object | None = None
        self.last_scope: object | None = None

    async def find_by_username(self, username: str) -> User | None:
        if self.existing is not None and self.existing.username == username:
            return self.existing
        return None

    async def create(self, payload: UserCreate, *, password_hash: str) -> User:
        return _user(2, payload.username, nickname=payload.nickname)

    async def get(self, user_id: int) -> User | None:
        return self.get_row

    async def list_paginated(
        self,
        query: object,
        page: int,
        size: int,
        *,
        order_by: object,
        scope: object | None = None,
    ) -> list[User]:
        self.last_query = query
        self.last_order_by = order_by
        self.last_scope = scope
        return self.rows

    async def count(self, query: object, *, scope: object | None = None) -> int:
        # count 也收到同一 query + scope（断言 WHERE 与 list 一致 → total 反映过滤后数量）。
        self.last_query = query
        self.last_scope = scope
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
    assert exc.value.code == "user.USERNAME_DUPLICATE"


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
    assert exc.value.code == "user.NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_missing_raises_404() -> None:
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).delete(999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_returns_page() -> None:
    rows = [_user(1, "alice"), _user(2, "bob")]
    page = await _svc(_StubRepo(rows=rows)).list_(_Q, page=1, size=20)
    assert {u.username for u in page.items} == {"alice", "bob"}
    assert page.total == 2
    assert page.total_pages == 1


# ---- 过滤 / 排序 / data_scope 叠加（P1 列表增强）------------------------------


@pytest.mark.asyncio
async def test_list_invalid_order_by_raises_422() -> None:
    """防注入守门：order_by 非 allowlist 字段（如 password_hash）→ service 抛 422，绝不进 repo。"""
    repo = _StubRepo(rows=[_user(1, "alice")])
    with pytest.raises(AppError) as exc:
        await _svc(repo).list_(UserListQuery(order_by="password_hash"), page=1, size=20)
    assert exc.value.status_code == 422
    assert exc.value.code == "framework.SORT_FIELD_INVALID"
    # 校验在 repo 之前就拦下 → repo 未被调用（last_query 仍为初始 None）。
    assert repo.last_query is None


@pytest.mark.asyncio
async def test_list_injection_order_by_raises_422() -> None:
    """红线：经典注入串 order_by → 422，不拼进 SQL。"""
    with pytest.raises(AppError) as exc:
        await _svc(_StubRepo()).list_(
            UserListQuery(order_by="id; DROP TABLE users"), page=1, size=20
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_list_filters_and_scope_passed_through() -> None:
    """过滤 DTO + data_scope 都透传到 repository 的 list 与 count（WHERE 一致 → total 正确）。

    data_scope 不被新过滤吞掉：非超管 scope（SELF_DEPT，可见部门 {7}）原样传给 list 和 count，
    过滤是 AND 叠加在数据权限之上（apply_data_scope 在 repo 内先注入，再 .where 过滤）。
    """
    repo = _StubRepo(rows=[_user(1, "alice")])
    query = UserListQuery(username="ali", status="active", dept_id=7)
    scope = DataScope(scope_type=ScopeType.SELF_DEPT, user_id=1, visible_dept_ids=frozenset({7}))
    await _svc(repo).list_(query, page=1, size=20, scope=scope)
    assert repo.last_query is query  # list 收到原过滤 DTO
    assert repo.last_scope is scope  # count 也收到同一 scope（最后一次调用是 count），不被丢弃


@pytest.mark.asyncio
async def test_update_existing_returns_user() -> None:
    # update 现在总是先 get（数据权限可见性校验），故 stub 需提供 get_row（现有行）。
    carol = _user(5, "carol", nickname="Carol")
    out = await _svc(_StubRepo(get_row=carol, updated=carol)).update(
        5, UserUpdate(nickname="Carol")
    )
    assert out.id == 5
    assert out.nickname == "Carol"


@pytest.mark.asyncio
async def test_update_with_password_rehashes() -> None:
    # 覆盖 update 里 payload.password 非 None → hash_password 分支。
    carol = _user(5, "carol")
    out = await _svc(_StubRepo(get_row=carol, updated=carol)).update(
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
    assert exc.value.code == "user.LAST_SUPER_ADMIN"


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
    assert exc.value.code == "user.LAST_SUPER_ADMIN"
