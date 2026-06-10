"""单测：stub Provider（机制层单测的权限/菜单数据源）。"""

from __future__ import annotations

import pytest

from admin_platform.authz.providers import MenuNode
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.authz.stub_providers import StubMenuProvider, StubPermissionProvider


def test_permission_provider_returns_preset() -> None:
    """预置权限按 user_id 返回。"""
    provider = StubPermissionProvider(permissions={7: frozenset({"system:user:list"})})
    assert provider.get_user_permissions(7) == frozenset({"system:user:list"})


def test_permission_provider_unknown_user_empty() -> None:
    """未知用户：空权限集（默认 deny 友好）。"""
    assert StubPermissionProvider().get_user_permissions(999) == frozenset()


def test_effective_scope_preset_and_default() -> None:
    """预置范围按 user_id 返回；未预置退化为 SELF（最小可见）。"""
    scope = DataScope(ScopeType.ALL, user_id=7)
    provider = StubPermissionProvider(scopes={7: scope})
    assert provider.get_effective_data_scope(7) is scope
    assert provider.get_effective_data_scope(8).scope_type is ScopeType.SELF


def test_is_super_admin_trust_root() -> None:
    """信任根布尔：预置 super_admins 的 user_id 返回 True，其余 False。"""
    provider = StubPermissionProvider(super_admins=frozenset({1}))
    assert provider.get_is_super_admin(1) is True
    assert provider.get_is_super_admin(2) is False


def test_menu_provider_returns_preset_tree() -> None:
    """预置菜单树按 user_id 返回。"""
    node = MenuNode(id=1, name="System", path="/system")
    provider = StubMenuProvider(menus={7: [node]})
    assert provider.get_user_menu_tree(7) == [node]


def test_menu_provider_unknown_user_empty() -> None:
    """未知用户：空菜单树。"""
    assert StubMenuProvider().get_user_menu_tree(999) == []


def test_invalidate_is_noop() -> None:
    """P1 invalidate_* 为 no-op，调用不报错（接口先冻结，P2 接缓存时实现）。"""
    perm = StubPermissionProvider()
    perm.invalidate_user(1)
    perm.invalidate_role(2)
    perm.invalidate_all()
    menu = StubMenuProvider()
    menu.invalidate_user(1)
    menu.invalidate_role(2)
    menu.invalidate_all()


# ---- H5 DI seam：stub 经 ABC 默认 a_* 与同步方法一致（rbac.py 端点直接 await a_*，注入非
#      DbProvider 也必须可驱动，不 AttributeError、不递归）----


@pytest.mark.anyio
async def test_permission_provider_async_kernel_mirrors_sync() -> None:
    """H5：rbac.py getInfo 端点 await 的 a_* 在 stub 上经 ABC 默认实现 = 调同步方法，结果一致。
    （DI seam 真实化的回归网：替换 Provider / P2 缓存版注入 rbac.py 不破契约。）"""
    provider = StubPermissionProvider(
        permissions={7: frozenset({"system:user:list"})},
        super_admins=frozenset({1}),
        inactive_users=frozenset({9}),
    )
    assert await provider.a_get_is_active(7) is True
    assert await provider.a_get_is_active(9) is False
    assert await provider.a_get_is_super_admin(1) is True
    assert await provider.a_get_is_super_admin(7) is False
    assert await provider.a_get_user_permissions(7) == frozenset({"system:user:list"})
    assert await provider.a_get_user_role_codes(7) == provider.get_user_role_codes(7)
    assert (await provider.a_get_effective_data_scope(8)).scope_type is ScopeType.SELF


@pytest.mark.anyio
async def test_menu_provider_async_kernel_mirrors_sync() -> None:
    """H5：rbac.py getRouters 端点 await 的 a_get_user_menu_tree 在 stub 上 = 同步方法结果。"""
    node = MenuNode(id=1, name="System", path="/system")
    provider = StubMenuProvider(menus={7: [node]})
    assert await provider.a_get_user_menu_tree(7) == [node]
    assert await provider.a_get_user_menu_tree(999) == []
