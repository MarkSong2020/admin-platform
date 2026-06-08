"""真实 DB 版 MenuProvider —— 用户可见菜单树的来源（spec §5.2，getRouters 数据源）。

本模块在 domains 层（可 import menu/user repository）。``authz`` 抽象是叶子基座（C8 禁 import
domains），但 domains 的**实现**可以反向依赖 authz 抽象 —— 这里把 ``MenuProvider`` 落到 DB。

**sync→async 桥**（关键约束，镜像 ``domains.role.provider.DbPermissionProvider``）：
``MenuProvider.get_user_menu_tree`` 抽象方法是**同步**的（与 ``require_permission`` 同步依赖
对齐），而本仓 DB 栈是纯 async（asyncpg）。FastAPI 把同步依赖跑在 threadpool worker 线程，故
同步方法用 ``anyio.from_thread.run`` 桥回宿主事件循环执行协程。异步内核 ``a_get_user_menu_tree``
+ 纯函数 ``assemble_menu_forest`` 可在 pytest-asyncio 里直接 ``await`` 单测，桥只在生产 HTTP 路径生效。

**可见性规则**：
  * 超管（``users.is_super_admin AND status=active``，复用 role provider 思路）→ 全部 ``active`` 菜单。
  * 非超管 → 经生效角色（``role_menus``，停用角色不贡献）可见的 ``active`` 菜单子集。
  * 停用菜单（``status!=active``）不下发；``visible=False`` 仍下发（getRouters 标 hidden）。

**P1 不缓存（Q8）**：每次请求查 DB；``invalidate_*`` 为 no-op 占位，接口先冻结，P2 接 Redis 时实现。
"""

from __future__ import annotations

from anyio.from_thread import run as run_in_host_loop

from admin_platform.authz.providers import MenuNode, MenuProvider
from admin_platform.db.session import db_session
from admin_platform.domains.menu.models import Menu
from admin_platform.domains.menu.repository import MenuRepository
from admin_platform.domains.user.repository import UserRepository


def assemble_menu_forest(menus: list[Menu]) -> list[MenuNode]:
    """把扁平菜单列表按 ``parent_id`` 组装成 ``MenuNode`` 森林（纯函数，可注入假行单测）。

    每层按 ``(sort_order, id)`` 排序。父不在集合内的节点（被可见性 / status 过滤掉父）提升为根，
    保证授予的子菜单不因父缺失而丢失（对标若依按 id 集合建树）。数据成环时（FK ck 已防自环、
    service advisory lock 防深环）只下挂能从根可达的节点，不会无限递归。
    """
    by_id = {menu.id: menu for menu in menus}
    children: dict[int | None, list[Menu]] = {}
    for menu in menus:
        parent_key = menu.parent_id if menu.parent_id in by_id else None
        children.setdefault(parent_key, []).append(menu)

    def build(parent_key: int | None) -> list[MenuNode]:
        ordered = sorted(children.get(parent_key, []), key=lambda m: (m.sort_order, m.id))
        return [
            MenuNode(
                id=menu.id,
                name=menu.name,
                path=menu.path,
                menu_type=menu.menu_type,
                component=menu.component,
                perms=menu.perms,
                icon=menu.icon,
                visible=menu.visible,
                children=tuple(build(menu.id)),
            )
            for menu in ordered
        ]

    return build(None)


class DbMenuProvider(MenuProvider):
    """直查 DB 的 MenuProvider（P1 不缓存，每次请求查 DB）。

    同步接口经 ``anyio.from_thread.run`` 桥到异步内核；只能在 FastAPI 同步依赖（threadpool
    worker 线程）上下文调用。单测请直接 ``await`` ``a_get_user_menu_tree`` 内核。
    """

    # ---- 同步接口（getRouters 端点接线后在 threadpool worker 线程调用）----

    def get_user_menu_tree(self, user_id: int) -> list[MenuNode]:
        return run_in_host_loop(self.a_get_user_menu_tree, user_id)

    # ---- 异步内核（可直接 await 单测）----

    async def a_get_user_menu_tree(self, user_id: int) -> list[MenuNode]:
        """超管取全部 active 菜单建树；非超管取经 role_menus 可见的 active 菜单建树。

        账号状态校验（Codex 深审 F1 + spec §2.3 不绕过账号状态）：停用 / 不存在账号不下发
        任何菜单 —— 撤权（停用账号）后旧 token 不应再经 getRouters 看到菜单树。先一次性查
        user，active 校验覆盖超管 + 非超管两条路径。
        """
        async with db_session() as session:
            user = await UserRepository(session).get(user_id)
            if user is None or user.status != "active":
                return []
            menu_repo = MenuRepository(session)
            if user.is_super_admin:
                menus = await menu_repo.list_all_active()
            else:
                visible_ids = await menu_repo.list_menu_ids_for_user(user_id)
                menus = await menu_repo.list_active_by_ids(visible_ids)
            return assemble_menu_forest(menus)

    # ---- 失效语义（P1 无缓存，no-op；接口先冻结，P2 接 Redis 时实现）----

    def invalidate_user(self, user_id: int) -> None:
        pass

    def invalidate_role(self, role_id: int) -> None:
        pass

    def invalidate_all(self) -> None:
        pass
