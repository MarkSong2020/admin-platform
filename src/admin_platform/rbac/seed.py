"""RBAC 初始数据 seed（spec §13.1 / Q11）—— 版本化 manifest + 幂等 apply。

菜单 / 权限 / 内置角色用**版本化 manifest**（本模块 typed data，复用 §13.2 ``Permissions`` 常量）
作真相源，由幂等 ``rbac seed`` CLI（``cli.py``）upsert：
  * **菜单**按 ``seed_key`` 幂等 upsert（update-in-place 保留 id → 不破坏 role_menus 绑定），
    manifest 移除的内置菜单会被 prune（其 role_menus 绑定 CASCADE 清理）。
  * **角色**按 ``code`` 幂等 upsert（``superadmin`` 展示角色，**不作信任根**——信任根仍是
    ``users.is_super_admin`` 布尔，spec §2.1/§2.4）。
  * **不进 Alembic data migration**（spec：迁移只管 schema + drift）；超管 ``create-super-admin``
    CLI 保持独立（信任根特殊，不并入普通 seed 重跑）。
  * **防覆盖**：只管理 ``seed_key`` 非空的菜单 / manifest 列出的角色 code；用户自建（seed_key
    NULL / 其它 code）不碰。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.authz.permissions import Permissions
from admin_platform.domains.menu.models import Menu
from admin_platform.domains.role.models import Role

# pg_advisory_xact_lock 的稳定 key —— 串行化 seed 全过程（Codex 系统级 PK）：防两个并发
# `rbac seed`（多实例部署初始化）同时从空库启动时撞 roles.code / menus.seed_key 唯一约束。
# 事务级锁，提交/回滚自动释放。取与各域绑定锁（478221-478251）不同的值避免互锁。
_SEED_LOCK_KEY = 478261


@dataclass(frozen=True)
class SeedMenu:
    """内置菜单节点（seed manifest 的 typed 形态）。``perms`` 引用 ``Permissions`` 常量。"""

    seed_key: str
    name: str
    menu_type: str  # M 目录 / C 菜单 / F 按钮
    path: str = ""
    component: str | None = None
    perms: str | None = None
    icon: str = ""
    sort_order: int = 0
    visible: bool = True
    children: tuple[SeedMenu, ...] = ()


@dataclass(frozen=True)
class SeedRole:
    """内置角色（按 ``code`` 幂等）。"""

    code: str
    name: str
    data_scope: str
    sort_order: int = 0


def _resource_menu(  # noqa: PLR0913 —— 显式命名 5 个 perm 常量比位置元组清晰，config builder 可放宽
    *,
    resource: str,
    cn: str,
    sort: int,
    list_perm: str,
    query_perm: str,
    add_perm: str,
    edit_perm: str,
    remove_perm: str,
) -> SeedMenu:
    """一个资源域的「菜单(C) + 增删改查 4 按钮(F)」标准块（对标若依 system:{resource}:*）。"""
    buttons = (
        SeedMenu(query_perm, f"{cn}查询", "F", perms=query_perm, sort_order=1),
        SeedMenu(add_perm, f"{cn}新增", "F", perms=add_perm, sort_order=2),
        SeedMenu(edit_perm, f"{cn}修改", "F", perms=edit_perm, sort_order=3),
        SeedMenu(remove_perm, f"{cn}删除", "F", perms=remove_perm, sort_order=4),
    )
    return SeedMenu(
        seed_key=f"system:{resource}",
        name=f"{cn}管理",
        menu_type="C",
        path=resource,
        component=f"system/{resource}/index",
        perms=list_perm,
        icon=resource,
        sort_order=sort,
        children=buttons,
    )


# ---- manifest（版本化，git 跟踪）------------------------------------------

MENU_TREE: tuple[SeedMenu, ...] = (
    SeedMenu(
        seed_key="system",
        name="系统管理",
        menu_type="M",
        path="system",
        icon="system",
        sort_order=1,
        children=(
            _resource_menu(
                resource="user",
                cn="用户",
                sort=1,
                list_perm=Permissions.SYSTEM_USER_LIST,
                query_perm=Permissions.SYSTEM_USER_QUERY,
                add_perm=Permissions.SYSTEM_USER_ADD,
                edit_perm=Permissions.SYSTEM_USER_EDIT,
                remove_perm=Permissions.SYSTEM_USER_REMOVE,
            ),
            _resource_menu(
                resource="role",
                cn="角色",
                sort=2,
                list_perm=Permissions.SYSTEM_ROLE_LIST,
                query_perm=Permissions.SYSTEM_ROLE_QUERY,
                add_perm=Permissions.SYSTEM_ROLE_ADD,
                edit_perm=Permissions.SYSTEM_ROLE_EDIT,
                remove_perm=Permissions.SYSTEM_ROLE_REMOVE,
            ),
            _resource_menu(
                resource="menu",
                cn="菜单",
                sort=3,
                list_perm=Permissions.SYSTEM_MENU_LIST,
                query_perm=Permissions.SYSTEM_MENU_QUERY,
                add_perm=Permissions.SYSTEM_MENU_ADD,
                edit_perm=Permissions.SYSTEM_MENU_EDIT,
                remove_perm=Permissions.SYSTEM_MENU_REMOVE,
            ),
            _resource_menu(
                resource="dept",
                cn="部门",
                sort=4,
                list_perm=Permissions.SYSTEM_DEPT_LIST,
                query_perm=Permissions.SYSTEM_DEPT_QUERY,
                add_perm=Permissions.SYSTEM_DEPT_ADD,
                edit_perm=Permissions.SYSTEM_DEPT_EDIT,
                remove_perm=Permissions.SYSTEM_DEPT_REMOVE,
            ),
            _resource_menu(
                resource="post",
                cn="岗位",
                sort=5,
                list_perm=Permissions.SYSTEM_POST_LIST,
                query_perm=Permissions.SYSTEM_POST_QUERY,
                add_perm=Permissions.SYSTEM_POST_ADD,
                edit_perm=Permissions.SYSTEM_POST_EDIT,
                remove_perm=Permissions.SYSTEM_POST_REMOVE,
            ),
            _resource_menu(
                resource="dict",
                cn="字典",
                sort=6,
                list_perm=Permissions.SYSTEM_DICT_LIST,
                query_perm=Permissions.SYSTEM_DICT_QUERY,
                add_perm=Permissions.SYSTEM_DICT_ADD,
                edit_perm=Permissions.SYSTEM_DICT_EDIT,
                remove_perm=Permissions.SYSTEM_DICT_REMOVE,
            ),
            _resource_menu(
                resource="config",
                cn="参数",
                sort=7,
                list_perm=Permissions.SYSTEM_CONFIG_LIST,
                query_perm=Permissions.SYSTEM_CONFIG_QUERY,
                add_perm=Permissions.SYSTEM_CONFIG_ADD,
                edit_perm=Permissions.SYSTEM_CONFIG_EDIT,
                remove_perm=Permissions.SYSTEM_CONFIG_REMOVE,
            ),
            _resource_menu(
                resource="notice",
                cn="通知公告",
                sort=8,
                list_perm=Permissions.SYSTEM_NOTICE_LIST,
                query_perm=Permissions.SYSTEM_NOTICE_QUERY,
                add_perm=Permissions.SYSTEM_NOTICE_ADD,
                edit_perm=Permissions.SYSTEM_NOTICE_EDIT,
                remove_perm=Permissions.SYSTEM_NOTICE_REMOVE,
            ),
            # 文件管理（对标 RuoYi sys_oss）：菜单(C) + 查/上传/下载/删 4 按钮(F)。
            # 手写（非 _resource_menu 标准五件）：动作是 upload/download 而非 add/edit。
            SeedMenu(
                seed_key="system:file",
                name="文件管理",
                menu_type="C",
                path="file",
                component="system/file/index",
                perms=Permissions.SYSTEM_FILE_LIST,
                icon="upload",
                sort_order=9,
                children=(
                    SeedMenu(
                        Permissions.SYSTEM_FILE_QUERY,
                        "文件查询",
                        "F",
                        perms=Permissions.SYSTEM_FILE_QUERY,
                        sort_order=1,
                    ),
                    SeedMenu(
                        Permissions.SYSTEM_FILE_UPLOAD,
                        "文件上传",
                        "F",
                        perms=Permissions.SYSTEM_FILE_UPLOAD,
                        sort_order=2,
                    ),
                    SeedMenu(
                        Permissions.SYSTEM_FILE_DOWNLOAD,
                        "文件下载",
                        "F",
                        perms=Permissions.SYSTEM_FILE_DOWNLOAD,
                        sort_order=3,
                    ),
                    SeedMenu(
                        Permissions.SYSTEM_FILE_REMOVE,
                        "文件删除",
                        "F",
                        perms=Permissions.SYSTEM_FILE_REMOVE,
                        sort_order=4,
                    ),
                ),
            ),
        ),
    ),
    SeedMenu(
        seed_key="monitor",
        name="系统监控",
        menu_type="M",
        path="monitor",
        icon="monitor",
        sort_order=2,
        children=(
            SeedMenu(
                seed_key="monitor:operlog",
                name="操作日志",
                menu_type="C",
                path="operlog",
                component="monitor/operlog/index",
                perms=Permissions.SYSTEM_OPERLOG_LIST,
                icon="form",
                sort_order=1,
                children=(
                    SeedMenu(
                        Permissions.SYSTEM_OPERLOG_QUERY,
                        "操作日志查询",
                        "F",
                        perms=Permissions.SYSTEM_OPERLOG_QUERY,
                        sort_order=1,
                    ),
                ),
            ),
            SeedMenu(
                seed_key="monitor:logininfor",
                name="登录日志",
                menu_type="C",
                path="logininfor",
                component="monitor/logininfor/index",
                perms=Permissions.SYSTEM_LOGININFOR_LIST,
                icon="logininfor",
                sort_order=2,
                children=(
                    SeedMenu(
                        Permissions.SYSTEM_LOGININFOR_QUERY,
                        "登录日志查询",
                        "F",
                        perms=Permissions.SYSTEM_LOGININFOR_QUERY,
                        sort_order=1,
                    ),
                ),
            ),
            # P4 服务/缓存监控：只读单视图，无增删改按钮（list perm 即整页授权）。
            SeedMenu(
                seed_key="monitor:server",
                name="服务监控",
                menu_type="C",
                path="server",
                component="monitor/server/index",
                perms=Permissions.SYSTEM_SERVER_LIST,
                icon="server",
                sort_order=3,
            ),
            SeedMenu(
                seed_key="monitor:cache",
                name="缓存监控",
                menu_type="C",
                path="cache",
                component="monitor/cache/index",
                perms=Permissions.SYSTEM_CACHE_LIST,
                icon="redis",
                sort_order=4,
            ),
            # P4 在线用户：列表（list）+ 强制下线按钮（remove）。
            SeedMenu(
                seed_key="monitor:online",
                name="在线用户",
                menu_type="C",
                path="online",
                component="monitor/online/index",
                perms=Permissions.SYSTEM_ONLINE_LIST,
                icon="online",
                sort_order=5,
                children=(
                    SeedMenu(
                        Permissions.SYSTEM_ONLINE_REMOVE,
                        "强制下线",
                        "F",
                        perms=Permissions.SYSTEM_ONLINE_REMOVE,
                        sort_order=1,
                    ),
                ),
            ),
            # P4c 定时任务：列表（list）+ 查/增/改/删/执行 5 按钮。
            SeedMenu(
                seed_key="monitor:job",
                name="定时任务",
                menu_type="C",
                path="job",
                component="monitor/job/index",
                perms=Permissions.SYSTEM_JOB_LIST,
                icon="job",
                sort_order=6,
                children=(
                    SeedMenu(
                        Permissions.SYSTEM_JOB_QUERY,
                        "任务查询",
                        "F",
                        perms=Permissions.SYSTEM_JOB_QUERY,
                        sort_order=1,
                    ),
                    SeedMenu(
                        Permissions.SYSTEM_JOB_ADD,
                        "任务新增",
                        "F",
                        perms=Permissions.SYSTEM_JOB_ADD,
                        sort_order=2,
                    ),
                    SeedMenu(
                        Permissions.SYSTEM_JOB_EDIT,
                        "任务修改",
                        "F",
                        perms=Permissions.SYSTEM_JOB_EDIT,
                        sort_order=3,
                    ),
                    SeedMenu(
                        Permissions.SYSTEM_JOB_REMOVE,
                        "任务删除",
                        "F",
                        perms=Permissions.SYSTEM_JOB_REMOVE,
                        sort_order=4,
                    ),
                    SeedMenu(
                        Permissions.SYSTEM_JOB_RUN,
                        "任务执行",
                        "F",
                        perms=Permissions.SYSTEM_JOB_RUN,
                        sort_order=5,
                    ),
                ),
            ),
        ),
    ),
)

# superadmin 展示角色：解决前端漂移（§2.4），**不作信任根**（信任根 = is_super_admin 布尔）。
# data_scope 取最小 "self"（非 "all"）——它是纯展示对象（getInfo 只读其 code），不该参与
# 授权归一（Codex 系统级 PK）：若普通用户误绑该角色，"all" 会让 compute_effective_data_scope
# 直接放大到全量数据范围；用 "self" 则即使误绑也不扩数据权限。真超管走 is_super_admin 短路。
ROLES: tuple[SeedRole, ...] = (SeedRole(code="superadmin", name="超级管理员", data_scope="self"),)


@dataclass
class SeedResult:
    roles_upserted: int = 0
    menus_upserted: int = 0
    menus_pruned: int = 0


async def seed_rbac(session: AsyncSession) -> SeedResult:
    """幂等 apply manifest（菜单按 seed_key、角色按 code），返回统计。重跑结果一致。"""
    result = SeedResult()

    # 0) advisory lock 串行化整个 seed（并发重跑防撞唯一约束，Codex 系统级 PK）。
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_SEED_LOCK_KEY))

    # 1) 角色：按 code upsert（用户自建角色 code 不同 → 不碰）。
    for sr in ROLES:
        role = await session.scalar(select(Role).where(Role.code == sr.code))
        if role is None:
            session.add(
                Role(
                    code=sr.code,
                    name=sr.name,
                    data_scope=sr.data_scope,
                    sort_order=sr.sort_order,
                    status="active",
                )
            )
        else:
            role.name, role.data_scope, role.sort_order = sr.name, sr.data_scope, sr.sort_order
        result.roles_upserted += 1
    await session.flush()

    # 2) 菜单：按 seed_key upsert（update-in-place 保 id → 不破坏 role_menus 绑定），pre-order
    #    保证父先于子（子的 parent_id 取父已 flush 的 id）。
    existing = {
        m.seed_key: m
        for m in (await session.scalars(select(Menu).where(Menu.seed_key.is_not(None)))).all()
        if m.seed_key is not None
    }
    seen: set[str] = set()

    async def upsert(node: SeedMenu, parent: Menu | None) -> None:
        seen.add(node.seed_key)
        menu = existing.get(node.seed_key)
        if menu is None:
            menu = Menu(seed_key=node.seed_key)
            session.add(menu)
        menu.name = node.name
        menu.menu_type = node.menu_type
        menu.path = node.path
        menu.component = node.component
        menu.perms = node.perms
        menu.icon = node.icon
        menu.sort_order = node.sort_order
        menu.visible = node.visible
        menu.status = "active"
        menu.parent_id = parent.id if parent is not None else None
        await session.flush()  # 取 id 供子节点 parent_id
        result.menus_upserted += 1
        for child in node.children:
            await upsert(child, menu)

    for root in MENU_TREE:
        await upsert(root, None)

    # 3) prune：manifest 已移除的内置菜单删除。FK RESTRICT 要求子先于父删，故迭代「叶子优先」
    #    （不是任何剩余 stale 菜单之父的先删）。若某 stale 菜单挂着用户自建子菜单则 RESTRICT
    #    报错（正确：不孤立用户菜单）。
    stale: dict[int, Menu] = {m.id: m for key, m in existing.items() if key not in seen}
    while stale:
        parent_ids = {m.parent_id for m in stale.values() if m.parent_id in stale}
        leaves = [m for mid, m in stale.items() if mid not in parent_ids]
        if not leaves:
            break  # 防御：理论不可达（树无环）
        for menu in leaves:
            await session.delete(menu)
            del stale[menu.id]
            result.menus_pruned += 1
        await session.flush()
    return result
