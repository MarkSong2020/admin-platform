"""Menu repository — SQLAlchemy 2.x async 数据访问层。返回 ORM 行 / None / 集合，不抛业务异常。

除标准 CRUD（无 ``find_by_code`` —— 菜单无 code）外，承载：
  * 树查询 —— ``list_descendant_menu_ids``（递归 CTE 含自身，删父防有子 + 移动防环复用）、
    ``count_children``、``acquire_tree_lock``（advisory lock 串行化树写，镜像 dept、用不同 key）。
  * 建树数据源 —— ``list_all_active``（超管取全部 active）/ ``list_active_by_ids``（非超管取可见
    id 的 active），供 ``provider.DbMenuProvider`` 组装 ``MenuNode`` 树。
  * RBAC 集成预留（供人值守接线 ``get_user_permissions`` 真实派生 + 后续 getRouters 端点）——
    ``list_menu_ids_for_user`` / ``list_perms_for_user``（JOIN ``user_roles``→``role_menus``，只取
    ``status=active`` 角色）、``set_role_menus``（全量替换绑定，advisory lock + 先删后插）。
"""

from __future__ import annotations

from sqlalchemy import delete, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.menu.models import Menu, RoleMenu
from admin_platform.domains.menu.schemas import MenuCreate, MenuUpdate
from admin_platform.domains.role.models import Role, UserRole

# pg_advisory_xact_lock 的稳定 key —— 串行化菜单树写 / role_menus 全量替换（移动防环 + 先删后插）。
# 与 dept(478221) / role(478231/478232) 取不同值避免跨域互锁。事务级锁，提交/回滚自动释放。
_MENU_TREE_LOCK_KEY = 478241  # 串行化菜单树写（移动/删除防并发成环）
_ROLE_MENUS_LOCK_KEY = 478242  # 串行化 role_menus 全量替换
_MAX_MENU_DEPTH = 64  # recursive CTE 深度兜底（实际深度 <10）；坏数据成环时防死循环


class MenuRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paginated(self, page: int, size: int) -> list[Menu]:
        offset = (page - 1) * size
        stmt = select(Menu).offset(offset).limit(size).order_by(Menu.sort_order, Menu.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(Menu))
        return int(result.scalar_one())

    async def acquire_tree_lock(self) -> None:
        """事务级 advisory lock，串行化菜单树写（移动/删除防并发成环）。

        提交/回滚自动释放。配合锁内重新校验，关掉 ``_check_no_cycle`` 的 TOCTOU 窗口
        （两个并发移动 A→B、B→A 各自校验都过、提交后成环）。镜像 dept，用不同 key。
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_MENU_TREE_LOCK_KEY)
        )

    async def get(self, item_id: int) -> Menu | None:
        return await self._session.get(Menu, item_id)

    async def count_children(self, menu_id: int) -> int:
        """直接子菜单数量（删除 RESTRICT 预检用）。"""
        result = await self._session.execute(
            select(func.count()).select_from(Menu).where(Menu.parent_id == menu_id)
        )
        return int(result.scalar_one())

    async def create(self, payload: MenuCreate) -> Menu:
        obj = Menu(**payload.model_dump())
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(self, item_id: int, payload: MenuUpdate) -> Menu | None:
        obj = await self._session.get(Menu, item_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self._session.flush()
        # onupdate=func.now() 让 updated_at 在 UPDATE 后过期；异步 session 下后续序列化
        # （MenuRead 含时间戳）访问过期列会触发隐式刷新报错（Errata #7）。显式 refresh 取回新值。
        await self._session.refresh(obj)
        return obj

    async def delete(self, item_id: int) -> bool:
        obj = await self._session.get(Menu, item_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True

    async def list_descendant_menu_ids(self, menu_id: int) -> frozenset[int]:
        """递归向下，返回 ``menu_id`` 的全部子孙 id（**含自身**）。

        recursive CTE：base = 自身行；递归段按 ``parent_id == tree.id`` 连下一层。
        只按 ``parent_id`` 展开（不过滤 status）。供移动防环（新父不能落在子孙集合内）。
        """
        tree = (
            select(Menu.id, literal(0).label("depth"))
            .where(Menu.id == menu_id)
            .cte("menu_descendants", recursive=True)
        )
        tree = tree.union_all(
            select(Menu.id, tree.c.depth + 1).where(
                Menu.parent_id == tree.c.id, tree.c.depth < _MAX_MENU_DEPTH
            )
        )
        result = await self._session.execute(select(tree.c.id))
        return frozenset(int(row) for row in result.scalars().all())

    # ---- 建树数据源（供 DbMenuProvider 组装 MenuNode 树）------------------------

    async def list_all_active(self) -> list[Menu]:
        """全部 ``status=active`` 菜单（超管建树用），按 sort_order/id 排序。"""
        stmt = select(Menu).where(Menu.status == "active").order_by(Menu.sort_order, Menu.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active_by_ids(self, menu_ids: frozenset[int]) -> list[Menu]:
        """指定 id 集合内的 ``status=active`` 菜单（非超管建树用），按 sort_order/id 排序。

        空集合直接返回 ``[]``（不发空 ``IN`` 查询）。
        """
        if not menu_ids:
            return []
        stmt = (
            select(Menu)
            .where(Menu.status == "active", Menu.id.in_(menu_ids))
            .order_by(Menu.sort_order, Menu.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ---- RBAC 集成预留（供人值守接线：get_user_permissions 派生 + getRouters）------

    async def list_menu_ids_for_user(self, user_id: int) -> frozenset[int]:
        """用户经**生效角色**可见的菜单 id 集（JOIN ``user_roles``→``roles``→``role_menus``）。

        只取 ``roles.status='active'`` 的角色（镜像 role 域 ``list_roles_for_user`` 的 active 过滤，
        Codex 深审 F1 同款）：停用角色不贡献菜单。返回原始授予 id（不过滤 menu.status，由
        ``list_active_by_ids`` 在建树时再滤 active）。
        """
        stmt = (
            select(RoleMenu.menu_id)
            .join(Role, Role.id == RoleMenu.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.status == "active")
        )
        result = await self._session.execute(stmt)
        return frozenset(int(menu_id) for menu_id in result.scalars().all())

    async def list_perms_for_user(self, user_id: int) -> frozenset[str]:
        """用户经生效角色拥有的权限标识集（``menus.perms`` 非空、``menus.status=active``）。

        供人值守接线把 ``DbPermissionProvider.get_user_permissions`` 改为真实派生（R1 暂返空集）。
        同 ``list_menu_ids_for_user``：只取 ``roles.status='active'`` 角色（停用角色不贡献权限）。
        """
        stmt = (
            select(Menu.perms)
            .join(RoleMenu, RoleMenu.menu_id == Menu.id)
            .join(Role, Role.id == RoleMenu.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                Role.status == "active",
                Menu.status == "active",
                Menu.perms.is_not(None),
            )
        )
        result = await self._session.execute(stmt)
        return frozenset(perm for perm in result.scalars().all() if perm)

    # ---- 绑定写（全量替换，先删后插）------------------------------------------

    async def set_role_menus(self, role_id: int, menu_ids: list[int]) -> None:
        """全量替换角色的菜单绑定（去重；空列表 = 解绑所有菜单）。

        先取事务级 advisory lock 串行化「先删后插」（镜像 role 域 set_user_roles 的 F3 修复）：
        并发两请求替换同一角色的绑定时，避免最终落成两请求的并集或撞 ``uq_role_menus``。
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_ROLE_MENUS_LOCK_KEY)
        )
        await self._session.execute(delete(RoleMenu).where(RoleMenu.role_id == role_id))
        await self._session.flush()
        for menu_id in dict.fromkeys(menu_ids):
            self._session.add(RoleMenu(role_id=role_id, menu_id=menu_id))
        await self._session.flush()
