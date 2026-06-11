"""权限 / 菜单 Provider 抽象（spec §5.2）。

P1 不缓存（Q8）：直查实现每次查 DB；``invalidate_*`` 是 no-op 占位，接口先冻结，
P2 接 Redis 缓存时再填充失效逻辑（届时不破坏本接口）。MenuProvider 产出动态菜单树，
是前端 getRouters payload 的数据源（spec §6.1）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from admin_platform.authz.scope import DataScope, ScopeType


@dataclass(frozen=True)
class AuthzContext:
    """``require_permission`` 单次加载的授权快照——合并 is_active / is_super_admin / permissions /
    data_scope，让每请求只借**一个** DB 连接（对抗审查 P1-A 根治）。

    原 ``_dep`` 是同步依赖（跑 anyio 线程池），逐个调 4 个 ``a_*`` 方法、每个经 ``from_thread`` 桥回
    宿主 loop 且各开独立 ``db_session()`` → 每请求 2-4 连接借用 + 线程池(默认 40) > 连接池(15) 时
    高并发耗尽 / 级联阻塞。改为 ``_dep`` async 一次 ``await a_load_authz_context`` → 单 session
    合并查询、零线程桥。``_dep`` 据本快照做短路决策与审计（审计留在 core 层，不下沉 provider）。
    """

    is_active: bool
    is_super_admin: bool
    permissions: frozenset[str]
    data_scope: DataScope


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

    # ---- 异步内核（H5 DI seam）----
    # 默认 = 调对应同步方法（内存 stub 用此默认把同步内存读包成 async）；真实 DB 版 Provider 覆盖
    # 做真正的异步 DB 查询，其同步方法反过来经线程桥调 a_*。rbac.py 的异步端点直接 ``await a_*``
    # （不再 cast 具体类），故 a_* 必须在抽象上声明——替换 Provider / P2 接缓存版才不破契约（H5）。

    async def a_get_is_active(self, user_id: int) -> bool:
        return self.get_is_active(user_id)

    async def a_get_is_super_admin(self, user_id: int) -> bool:
        return self.get_is_super_admin(user_id)

    async def a_get_user_role_codes(self, user_id: int) -> frozenset[str]:
        return self.get_user_role_codes(user_id)

    async def a_get_user_permissions(self, user_id: int) -> frozenset[str]:
        return self.get_user_permissions(user_id)

    async def a_get_effective_data_scope(self, user_id: int) -> DataScope:
        return self.get_effective_data_scope(user_id)

    async def a_load_authz_context(self, user_id: int) -> AuthzContext:
        """单次加载授权快照（``require_permission`` 用）。默认组合 ``a_*`` 方法——内存 stub 走此，无需
        单 session 优化；``DbPermissionProvider`` 覆盖做单 session 合并查询。按短路顺序：停用 → 直接
        返回（不查 permissions/scope）；超管 → 不查 permissions/scope（短路用 ALL 范围）。
        """
        if not await self.a_get_is_active(user_id):
            return AuthzContext(
                False, False, frozenset(), DataScope(ScopeType.SELF, user_id=user_id)
            )
        if await self.a_get_is_super_admin(user_id):
            return AuthzContext(True, True, frozenset(), DataScope(ScopeType.ALL, user_id=user_id))
        permissions = await self.a_get_user_permissions(user_id)
        data_scope = await self.a_get_effective_data_scope(user_id)
        return AuthzContext(True, False, permissions, data_scope)

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

    async def a_get_user_menu_tree(self, user_id: int) -> list[MenuNode]:
        """异步内核（H5 DI seam）：默认调同步方法；DbMenuProvider 覆盖做真正异步 DB 查询。"""
        return self.get_user_menu_tree(user_id)

    @abstractmethod
    def invalidate_user(self, user_id: int) -> None:
        """失效单个用户的菜单缓存。P1 为 no-op。"""

    @abstractmethod
    def invalidate_role(self, role_id: int) -> None:
        """失效某角色关联用户的菜单缓存。P1 为 no-op。"""

    @abstractmethod
    def invalidate_all(self) -> None:
        """失效全部菜单缓存。P1 为 no-op。"""
