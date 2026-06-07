"""单测：require_permission 依赖（默认 deny + 超管短路，spec §3.2）。

直接调依赖函数（绕过 FastAPI Depends 解析）单元测试机制逻辑；HTTP 端到端权限矩阵
（含 401 未登录）在 RBAC 域接入 require_permission 时（D1+）覆盖。
"""

from __future__ import annotations

import pytest

from admin_platform.authz.scope import ScopeType
from admin_platform.authz.stub_providers import StubPermissionProvider
from admin_platform.core.auth import CurrentUser
from admin_platform.core.errors import AUTH_FORBIDDEN_BY_ROLE, AppError
from admin_platform.core.permissions import get_permission_provider, require_permission

PERM = "system:user:list"


def _user(uid: str) -> CurrentUser:
    return CurrentUser(user_id=uid, sub=uid)


def test_super_admin_short_circuits() -> None:
    """超管短路：放行，填充 is_super_admin + data_scope=ALL。"""
    dep = require_permission(PERM)
    provider = StubPermissionProvider(super_admins=frozenset({1}))
    result = dep(base_user=_user("1"), provider=provider)
    assert result.is_super_admin is True
    assert result.data_scope is not None
    assert result.data_scope.scope_type is ScopeType.ALL


def test_super_admin_short_circuits_even_without_permission() -> None:
    """超管短路覆盖 RBAC：即使 permissions 不含该 perm 也放行。"""
    dep = require_permission(PERM)
    provider = StubPermissionProvider(super_admins=frozenset({1}), permissions={1: frozenset()})
    assert dep(base_user=_user("1"), provider=provider).is_super_admin is True


def test_with_permission_passes() -> None:
    """有权限：放行，填充 permissions + data_scope。"""
    dep = require_permission(PERM)
    provider = StubPermissionProvider(permissions={2: frozenset({PERM})})
    result = dep(base_user=_user("2"), provider=provider)
    assert result.is_super_admin is False
    assert PERM in result.permissions


def test_without_permission_raises_403() -> None:
    """无该权限：默认 deny → 403 auth.FORBIDDEN_BY_ROLE。"""
    dep = require_permission(PERM)
    provider = StubPermissionProvider(permissions={3: frozenset({"other:perm"})})
    with pytest.raises(AppError) as exc_info:
        dep(base_user=_user("3"), provider=provider)
    assert exc_info.value.code == AUTH_FORBIDDEN_BY_ROLE
    assert exc_info.value.status_code == 403


def test_empty_permissions_raises_403() -> None:
    """无任何权限的普通用户：403（默认 deny）。"""
    dep = require_permission(PERM)
    with pytest.raises(AppError):
        dep(base_user=_user("4"), provider=StubPermissionProvider())


def test_provider_not_wired_fail_closed() -> None:
    """Provider 未接线：get_permission_provider 抛错（fail-closed，不静默放行）。"""
    with pytest.raises(RuntimeError):
        get_permission_provider()
