"""单测：stub Provider（机制层单测的权限/菜单数据源）。"""

from __future__ import annotations

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
