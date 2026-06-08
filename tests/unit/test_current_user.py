"""单测：CurrentUser RBAC 上下文扩展（spec §3.1）。"""

from __future__ import annotations

import dataclasses

import pytest

from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser


def test_basic_construction_defaults_rbac_empty() -> None:
    """只传基础字段时，RBAC 上下文为安全默认空值（未填充 = 无权限、无范围）。"""
    user = CurrentUser(user_id="7", sub="7", scope="")
    assert user.is_super_admin is False
    assert user.roles == frozenset()
    assert user.permissions == frozenset()
    assert user.dept_id is None
    assert user.data_scope is None


def test_full_rbac_context_construction() -> None:
    """可构造带完整 RBAC 上下文的 CurrentUser（权限依赖填充后的形态）。"""
    scope = DataScope(ScopeType.SELF_DEPT, user_id=7, dept_id=10)
    user = CurrentUser(
        user_id="7",
        sub="7",
        scope="",
        is_super_admin=False,
        roles=frozenset({"admin"}),
        permissions=frozenset({"system:user:list"}),
        dept_id=10,
        data_scope=scope,
    )
    assert user.permissions == frozenset({"system:user:list"})
    assert user.dept_id == 10
    assert user.data_scope is scope


def test_super_admin_flag() -> None:
    """超管标记可设（短路放行由 require_permission 依赖消费）。"""
    user = CurrentUser(user_id="1", sub="1", is_super_admin=True)
    assert user.is_super_admin is True


def test_current_user_frozen() -> None:
    """frozen：权限上下文一旦构造不可被篡改。"""
    user = CurrentUser(user_id="7", sub="7")
    with pytest.raises(dataclasses.FrozenInstanceError):
        user.is_super_admin = True  # type: ignore[misc]
