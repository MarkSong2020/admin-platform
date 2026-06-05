"""内存 stub Provider，供机制层单测使用（不依赖 DB / RBAC 表）。

真实 DB 版 Provider 在 RBAC 域（role/menu）落地后实现；机制层（require_permission）
的单测用这里的 stub 注入预置权限/范围/菜单，与持久层解耦。
"""

from __future__ import annotations

from admin_platform.authz.providers import MenuNode, MenuProvider, PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType


class StubPermissionProvider(PermissionProvider):
    """内存权限 Provider：预置 ``user_id -> (permissions, data_scope)``。invalidate_* 为 no-op。"""

    def __init__(
        self,
        permissions: dict[int, frozenset[str]] | None = None,
        scopes: dict[int, DataScope] | None = None,
    ) -> None:
        self._permissions = permissions or {}
        self._scopes = scopes or {}

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return self._permissions.get(user_id, frozenset())

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        # 未预置时退化为「仅本人」——最小可见范围，符合默认 deny 倾向。
        return self._scopes.get(user_id, DataScope(ScopeType.SELF, user_id=user_id))

    def invalidate_user(self, user_id: int) -> None:
        pass

    def invalidate_role(self, role_id: int) -> None:
        pass

    def invalidate_all(self) -> None:
        pass


class StubMenuProvider(MenuProvider):
    """内存菜单 Provider：预置 ``user_id -> menu tree``。invalidate_* 为 no-op。"""

    def __init__(self, menus: dict[int, list[MenuNode]] | None = None) -> None:
        self._menus = menus or {}

    def get_user_menu_tree(self, user_id: int) -> list[MenuNode]:
        return self._menus.get(user_id, [])

    def invalidate_user(self, user_id: int) -> None:
        pass

    def invalidate_role(self, role_id: int) -> None:
        pass

    def invalidate_all(self) -> None:
        pass
