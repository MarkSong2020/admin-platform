"""权限 / 菜单 Provider 抽象（spec §5.2）。

P1 不缓存（Q8）：直查实现每次查 DB；``invalidate_*`` 是 no-op 占位，接口先冻结，
P2 接 Redis 缓存时再填充失效逻辑（届时不破坏本接口）。MenuProvider 产出动态菜单树，
是前端 getRouters payload 的数据源（spec §6.1）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from admin_platform.authz.scope import DataScope


@dataclass(frozen=True)
class MenuNode:
    """动态菜单节点（菜单树最小形态，供前端动态路由 / 按钮权限渲染）。

    ``perms`` 为该节点对应的权限标识（按钮 / 菜单级），目录类节点可为 None。
    """

    id: int
    name: str
    path: str
    perms: str | None = None
    children: tuple[MenuNode, ...] = ()


class PermissionProvider(ABC):
    """用户权限标识与数据范围的来源。P1 每次直查 DB，不缓存（Q8）。"""

    @abstractmethod
    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        """用户拥有的权限标识集合（如 ``{"system:user:list"}``）。

        超管由上层（require_permission 依赖）短路放行，不依赖本方法返回全集。
        """

    @abstractmethod
    def get_effective_data_scope(self, user_id: int) -> DataScope:
        """用户生效的数据权限范围（多角色合并语义见 spec §11 O2）。"""

    @abstractmethod
    def invalidate_user(self, user_id: int) -> None:
        """失效单个用户的权限缓存。P1 为 no-op（不缓存），P2 接缓存时实现。"""

    @abstractmethod
    def invalidate_role(self, role_id: int) -> None:
        """失效某角色关联用户的权限缓存。P1 为 no-op。"""

    @abstractmethod
    def invalidate_all(self) -> None:
        """失效全部权限缓存。P1 为 no-op。"""


class MenuProvider(ABC):
    """用户可见菜单树的来源。"""

    @abstractmethod
    def get_user_menu_tree(self, user_id: int) -> list[MenuNode]:
        """用户可见的菜单树（动态路由 + 按钮权限数据源）。"""

    @abstractmethod
    def invalidate_user(self, user_id: int) -> None:
        """失效单个用户的菜单缓存。P1 为 no-op。"""

    @abstractmethod
    def invalidate_role(self, role_id: int) -> None:
        """失效某角色关联用户的菜单缓存。P1 为 no-op。"""

    @abstractmethod
    def invalidate_all(self) -> None:
        """失效全部菜单缓存。P1 为 no-op。"""
