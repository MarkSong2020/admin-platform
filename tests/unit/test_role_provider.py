"""DbPermissionProvider O2 归一单元测试 —— stub repository 隔离折叠逻辑（DB-free）。

测的是 ``compute_effective_data_scope`` 把多角色 data_scope 折叠成归一 ``DataScope`` 的纯逻辑
（spec §11 O2）：任一 ALL → ALL / 部门并集 / SELF → include_self / 无角色 / 无 dept → deny。
stub repo 只提供前置数据（用户 dept_id、角色列表、子孙集、自定义部门集），不测 DB / 桥接。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import pytest

import admin_platform.domains.role.provider as provider_module
from admin_platform.authz.scope import ScopeType
from admin_platform.db.session import _request_session_var
from admin_platform.domains.dept.repository import DeptRepository
from admin_platform.domains.role.provider import (
    DbPermissionProvider,
    compute_effective_data_scope,
)
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.user.repository import UserRepository


@dataclass
class _FakeUser:
    dept_id: int | None


@dataclass
class _FakeRole:
    id: int
    data_scope: str


class _StubUserRepo:
    def __init__(self, dept_id: int | None) -> None:
        self._user = _FakeUser(dept_id=dept_id)

    async def get(self, user_id: int) -> _FakeUser:
        return self._user


class _StubRoleRepo:
    def __init__(
        self,
        roles: list[_FakeRole],
        custom_depts: dict[int, frozenset[int]] | None = None,
    ) -> None:
        self._roles = roles
        self._custom = custom_depts or {}

    async def list_roles_for_user(self, user_id: int) -> list[_FakeRole]:
        return self._roles

    async def list_custom_dept_ids_for_role(self, role_id: int) -> frozenset[int]:
        return self._custom.get(role_id, frozenset())


class _StubDeptRepo:
    def __init__(self, descendants: dict[int, frozenset[int]] | None = None) -> None:
        self._descendants = descendants or {}

    async def list_descendant_dept_ids(self, dept_id: int) -> frozenset[int]:
        return self._descendants.get(dept_id, frozenset({dept_id}))


async def _compute(
    *,
    user_id: int = 1,
    dept_id: int | None = None,
    roles: list[_FakeRole],
    custom_depts: dict[int, frozenset[int]] | None = None,
    descendants: dict[int, frozenset[int]] | None = None,
):
    return await compute_effective_data_scope(
        user_id,
        user_repo=cast("UserRepository", _StubUserRepo(dept_id)),
        role_repo=cast("RoleRepository", _StubRoleRepo(roles, custom_depts)),
        dept_repo=cast("DeptRepository", _StubDeptRepo(descendants)),
    )


# ---- 任一 ALL → 整体 ALL（短路最宽）---------------------------------------


@pytest.mark.asyncio
async def test_any_all_role_yields_all() -> None:
    scope = await _compute(
        dept_id=10,
        roles=[_FakeRole(1, "self_dept"), _FakeRole(2, "all")],
    )
    assert scope.scope_type is ScopeType.ALL


# ---- 部门并集（本部门 + 自定义）-------------------------------------------


@pytest.mark.asyncio
async def test_dept_union_across_roles() -> None:
    scope = await _compute(
        dept_id=10,
        roles=[_FakeRole(1, "self_dept"), _FakeRole(2, "custom_dept")],
        custom_depts={2: frozenset({20, 21})},
    )
    assert scope.scope_type is ScopeType.CUSTOM_DEPT
    assert scope.visible_dept_ids == frozenset({10, 20, 21})
    assert scope.include_self is False


# ---- 本部门及以下 → 用子孙集合 --------------------------------------------


@pytest.mark.asyncio
async def test_self_dept_and_below_uses_descendants() -> None:
    scope = await _compute(
        dept_id=10,
        roles=[_FakeRole(1, "self_dept_and_below")],
        descendants={10: frozenset({10, 11, 12})},
    )
    assert scope.visible_dept_ids == frozenset({10, 11, 12})


class _CountingDeptRepo:
    """记录 ``list_descendant_dept_ids`` 调用次数的 stub——验证 N+1 hoist 后递归 CTE 只查一次。"""

    def __init__(self, descendants: dict[int, frozenset[int]]) -> None:
        self._descendants = descendants
        self.call_count = 0

    async def list_descendant_dept_ids(self, dept_id: int) -> frozenset[int]:
        self.call_count += 1
        return self._descendants.get(dept_id, frozenset({dept_id}))


@pytest.mark.asyncio
async def test_multiple_self_dept_and_below_roles_query_descendants_once() -> None:
    # 用户有 2 个 SELF_DEPT_AND_BELOW 角色：后代部门集只依赖 loop-invariant 的 user_dept_id，
    # hoist + memo 后递归 CTE 只查一次（call_count == 1），且结果集仍正确。
    dept_repo = _CountingDeptRepo({10: frozenset({10, 11, 12})})
    scope = await compute_effective_data_scope(
        1,
        user_repo=cast("UserRepository", _StubUserRepo(dept_id=10)),
        role_repo=cast(
            "RoleRepository",
            _StubRoleRepo(
                [_FakeRole(1, "self_dept_and_below"), _FakeRole(2, "self_dept_and_below")]
            ),
        ),
        dept_repo=cast("DeptRepository", dept_repo),
    )
    assert dept_repo.call_count == 1
    assert scope.visible_dept_ids == frozenset({10, 11, 12})


# ---- SELF → include_self（无部门段）---------------------------------------


@pytest.mark.asyncio
async def test_self_sets_include_self() -> None:
    scope = await _compute(dept_id=10, roles=[_FakeRole(1, "self")])
    assert scope.visible_dept_ids == frozenset()
    assert scope.include_self is True


@pytest.mark.asyncio
async def test_self_plus_dept_combines() -> None:
    # SELF + SELF_DEPT：可见部门 {10} 且 include_self（两段 OR）。
    scope = await _compute(
        dept_id=10,
        roles=[_FakeRole(1, "self"), _FakeRole(2, "self_dept")],
    )
    assert scope.visible_dept_ids == frozenset({10})
    assert scope.include_self is True


# ---- 无角色 / 无 dept → 安全 deny ------------------------------------------


@pytest.mark.asyncio
async def test_no_roles_yields_empty_deny() -> None:
    scope = await _compute(dept_id=10, roles=[])
    assert scope.scope_type is ScopeType.CUSTOM_DEPT
    assert scope.visible_dept_ids == frozenset()
    assert scope.include_self is False


@pytest.mark.asyncio
async def test_self_dept_without_dept_id_contributes_empty() -> None:
    # 用户无 dept_id：SELF_DEPT / AND_BELOW 贡献空集（安全 deny，不报错）。
    scope = await _compute(
        dept_id=None,
        roles=[_FakeRole(1, "self_dept"), _FakeRole(2, "self_dept_and_below")],
    )
    assert scope.visible_dept_ids == frozenset()
    assert scope.include_self is False


# ---- _acquire_session：复用请求 session vs 回退自开（P1 架构修复）------------
#
# 核心修复语义：HTTP 请求上下文里 ``current_request_session()`` 非空 → 授权读复用该业务 session
# （同连接 / 同事务 / 同快照，消连接翻倍 + 跨快照 TOCTOU）；非 HTTP（ContextVar 未设）→ 回退
# ``db_session()`` 自开。两分支都用手写 stub 验证，不连 DB、不用 MagicMock（项目红线）。


@pytest.mark.asyncio
async def test_acquire_session_reuses_request_session() -> None:
    # ContextVar 设了 sentinel（模拟 get_session 已建立请求业务 session）→ _acquire_session 必须
    # yield 出**同一个** sentinel，不自开新 session（不碰 db_session）。
    sentinel = cast("Any", object())
    token = _request_session_var.set(sentinel)
    try:
        async with DbPermissionProvider()._acquire_session() as acquired:
            assert acquired is sentinel
    finally:
        _request_session_var.reset(token)


@pytest.mark.asyncio
async def test_acquire_session_falls_back_to_db_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ContextVar 未设（非 HTTP：CLI / 后台任务）→ 走 db_session() 回退。把 provider 模块里的
    # db_session 换成 yield 另一个 sentinel 的假 CM，断言拿到的是回退 session，证明落入 else 分支。
    fallback = cast("Any", object())

    @asynccontextmanager
    async def _fake_db_session() -> AsyncIterator[Any]:
        yield fallback

    monkeypatch.setattr(provider_module, "db_session", _fake_db_session)

    # 确保此刻 ContextVar 确为空（前序测试若泄漏会污染本断言）。
    assert _request_session_var.get() is None
    async with DbPermissionProvider()._acquire_session() as acquired:
        assert acquired is fallback
