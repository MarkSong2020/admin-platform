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
    """动态菜单节点（菜单树，供前端动态路由 / 按钮权限渲染），是 ``getRouters`` payload 的数据源。

    字段为 ``getRouters`` 映射（``routers.build_routers``）所需的全部菜单元数据：
      * ``menu_type`` —— ``M`` 目录 / ``C`` 菜单 / ``F`` 按钮；按钮不进路由树（只承载 ``perms``）。
      * ``component`` —— 前端组件路径（目录无 component → ``Layout``，由映射层补默认）。
      * ``perms`` —— 该节点对应的权限标识（按钮 / 菜单级），目录类节点可为 None。
      * ``icon`` —— 菜单图标（映射到 ``meta.icon``）。
      * ``visible`` —— 是否在侧边栏显示（``getRouters`` 的 ``hidden = not visible``）。

    可选字段都带默认值，纯展示型调用（如测试）只填 ``id/name/path`` 即可构造。
    """

    id: int
    name: str
    path: str
    menu_type: str = "C"
    component: str | None = None
    perms: str | None = None
    icon: str = ""
    visible: bool = True
    children: tuple[MenuNode, ...] = ()


class PermissionProvider(ABC):
    """用户权限标识与数据范围的来源。P1 每次直查 DB，不缓存（Q8）。"""

    def get_is_active(self, user_id: int) -> bool:
        """账号是否可用（``users.status == "active"``），供 ``require_permission`` 请求期校验。

        **非抽象**：默认返回 True —— 内存 stub（测试）建模的就是活跃用户，无需逐个实现。
        真实 DB 版 Provider **必须覆盖**做 DB 查询：停用账号即使持有效 token / 角色也应被
        拒绝（Codex 深审 + spec §2.3「不绕过账号状态」）。
        """
        return True

    def get_user_role_codes(self, user_id: int) -> frozenset[str]:
        """用户经**生效角色**拥有的角色 code 集（getInfo 展示用，§6.1）。

        **非抽象**：默认空集（内存 stub 不建模角色）；真实 DB 版 Provider 覆盖查 user_roles→roles。
        非安全判定（只用于前端展示）——后端授权只认 permissions + is_super_admin。
        """
        return frozenset()

    @abstractmethod
    def get_is_super_admin(self, user_id: int) -> bool:
        """用户是否超级管理员（信任根布尔，对应 ``users.is_super_admin``）。

        超管短路只认这个布尔（spec §2.1/§2.3），**不**靠 permissions 含 ``*:*:*``
        通配判定（通配是 §6.1 的展示语义，非安全判定）。
        """

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
