"""真实 DB 版 PermissionProvider —— RBAC 权限 / 数据范围的来源（spec §5.2 + O2 归一）。

本模块在 domains 层（可 import user/dept/role repository）。``authz`` 抽象是叶子基座（C8 禁
import domains），但 domains 的**实现**可以反向依赖 authz 抽象 —— 这里就是把抽象落到 DB。

**sync→async 桥**（关键约束）：``PermissionProvider`` 抽象方法是**同步**的，``require_permission``
依赖（``core/permissions.py``，红线不可改）也同步调用它们；而本仓 DB 栈是纯 async（asyncpg）。
FastAPI 把同步依赖跑在 threadpool worker 线程，故同步方法用 ``anyio.from_thread.run`` 桥回宿主
事件循环执行协程（worker 线程由 ``anyio.to_thread.run_sync`` 派生，支持 ``from_thread``）。
异步内核（``a_*`` 方法 + 纯函数 ``compute_effective_data_scope``）可在 pytest-asyncio 里直接
``await`` 单测，桥只在生产 HTTP 路径生效。

**O2 多角色 data_scope 归一**（spec §11 O2）：把用户多个角色的 data_scope 折叠成一个归一
``DataScope`` —— 任一角色 ``ALL`` → 整体 ALL；否则部门范围取**并集**（本部门 / 及以下 / 自定义），
任一角色 ``SELF`` → ``include_self``。无角色 / 无有效部门 → 空可见集（``apply_data_scope`` 落 deny）。

**R1 边界**：``get_user_permissions`` 先返回 ``frozenset()`` —— 权限标识来自 ``menu.perms``（ME1
实现）；R1 不做 permissions（故非超管经 ``require_permission`` 一律 deny，符合默认 deny 倾向）。
"""

from __future__ import annotations

from anyio.from_thread import run as run_in_host_loop

from admin_platform.authz.providers import AuthzContext, PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.db.session import db_session
from admin_platform.domains.dept.repository import DeptRepository
from admin_platform.domains.menu.repository import MenuRepository
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.user.repository import UserRepository


async def compute_effective_data_scope(
    user_id: int,
    *,
    user_repo: UserRepository,
    role_repo: RoleRepository,
    dept_repo: DeptRepository,
) -> DataScope:
    """把用户多角色的 data_scope 折叠成归一 ``DataScope``（O2，纯函数，可注入 stub repo 单测）。

    归一规则（对标 RuoYi 多角色「取并集」）：
      * 任一角色 ``ALL`` → 直接 ``DataScope(ALL)``（最宽，短路）。
      * 否则按角色累加可见部门并集：``SELF_DEPT`` → {user.dept_id}；``SELF_DEPT_AND_BELOW`` →
        ``list_descendant_dept_ids(user.dept_id)``（含自身）；``CUSTOM_DEPT`` →
        ``list_custom_dept_ids_for_role(role.id)``。
      * 任一角色 ``SELF`` → ``include_self=True``（``apply_data_scope`` 追加 owner==user）。
      * 用户无 ``dept_id`` 时 ``SELF_DEPT`` / ``SELF_DEPT_AND_BELOW`` 贡献空集（安全 deny，不报错）。
      * 无任何角色 → 空可见集 + ``include_self=False`` → ``apply_data_scope`` 落 ``false()`` deny。

    返回的 ``scope_type`` 取 ``CUSTOM_DEPT``（非 ALL 即可，``apply_data_scope`` 只看
    ``visible_dept_ids`` + ``include_self``，不再分本部门 / 及以下 / 自定义）。
    """
    user = await user_repo.get(user_id)
    user_dept_id = user.dept_id if user is not None else None

    roles = await role_repo.list_roles_for_user(user_id)
    visible_dept_ids: set[int] = set()
    include_self = False
    for role in roles:
        scope_type = ScopeType(role.data_scope)
        if scope_type is ScopeType.ALL:
            return DataScope(ScopeType.ALL, user_id=user_id)
        if scope_type is ScopeType.SELF:
            include_self = True
        elif scope_type is ScopeType.SELF_DEPT:
            if user_dept_id is not None:
                visible_dept_ids.add(user_dept_id)
        elif scope_type is ScopeType.SELF_DEPT_AND_BELOW:
            if user_dept_id is not None:
                visible_dept_ids |= await dept_repo.list_descendant_dept_ids(user_dept_id)
        elif scope_type is ScopeType.CUSTOM_DEPT:
            visible_dept_ids |= await role_repo.list_custom_dept_ids_for_role(role.id)

    return DataScope(
        ScopeType.CUSTOM_DEPT,
        user_id=user_id,
        dept_id=user_dept_id,
        visible_dept_ids=frozenset(visible_dept_ids),
        include_self=include_self,
    )


class DbPermissionProvider(PermissionProvider):
    """直查 DB 的 PermissionProvider（P1 不缓存，每次请求查 DB；Q8）。

    同步接口经 ``anyio.from_thread.run`` 桥到异步内核；只能在 FastAPI 同步依赖
    （threadpool worker 线程）上下文调用（见模块 docstring）。单测请直接 ``await`` ``a_*`` 内核。
    """

    # ---- 同步接口（require_permission 依赖在 threadpool worker 线程调用）----

    def get_is_active(self, user_id: int) -> bool:
        return run_in_host_loop(self.a_get_is_active, user_id)

    def get_user_role_codes(self, user_id: int) -> frozenset[str]:
        return run_in_host_loop(self.a_get_user_role_codes, user_id)

    def get_is_super_admin(self, user_id: int) -> bool:
        return run_in_host_loop(self.a_get_is_super_admin, user_id)

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return run_in_host_loop(self.a_get_user_permissions, user_id)

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return run_in_host_loop(self.a_get_effective_data_scope, user_id)

    # ---- 异步内核（可直接 await 单测）----

    async def a_get_is_active(self, user_id: int) -> bool:
        """查 ``users.status == "active"``（请求期账号状态校验）；用户不存在视作停用（安全 deny）。"""
        async with db_session() as session:
            user = await UserRepository(session).get(user_id)
            return bool(user is not None and user.status == "active")

    async def a_get_is_super_admin(self, user_id: int) -> bool:
        """查 ``users.is_super_admin``（信任根布尔）；用户不存在视作非超管（安全 deny）。

        额外校验账号状态（Codex 深审 F4 + spec §2.3「超管短路不绕过账号状态」）：停用账号
        （``status != "active"``）即使 ``is_super_admin=True`` 也**不**短路 —— 否则被停用的超管
        在 token 过期前仍能凭旧 token 走短路通过所有权限校验。
        """
        async with db_session() as session:
            user = await UserRepository(session).get(user_id)
            return bool(user is not None and user.is_super_admin and user.status == "active")

    async def a_get_effective_data_scope(self, user_id: int) -> DataScope:
        """开 session 装配三个 repository，调 ``compute_effective_data_scope`` 做 O2 归一。"""
        async with db_session() as session:
            return await compute_effective_data_scope(
                user_id,
                user_repo=UserRepository(session),
                role_repo=RoleRepository(session),
                dept_repo=DeptRepository(session),
            )

    async def a_get_user_permissions(self, user_id: int) -> frozenset[str]:
        """从用户生效角色的 ``role_menus`` → ``menus.perms`` 派生权限标识集（ME1 接线）。

        权限真相源仍是端点的 ``require_permission`` 声明（spec §13.2，DB 菜单不反推保护）；
        本方法只回答「该用户经角色被授予了哪些权限标识」。停用角色 / 停用菜单不贡献
        （``MenuRepository.list_perms_for_user`` 内 JOIN 已滤 ``status=active``）。
        """
        async with db_session() as session:
            return await MenuRepository(session).list_perms_for_user(user_id)

    async def a_get_user_role_codes(self, user_id: int) -> frozenset[str]:
        """用户生效角色的 code 集（getInfo 展示，§6.1）；停用角色不计（list_roles_for_user 已滤）。"""
        async with db_session() as session:
            roles = await RoleRepository(session).list_roles_for_user(user_id)
            return frozenset(r.code for r in roles)

    async def a_load_authz_context(self, user_id: int) -> AuthzContext:
        """单 session 合并加载授权快照（对抗审查 P1-A 根治）：替代 ``_dep`` 原先逐个调 4 个 ``a_*``、
        每个 from_thread 桥 + 独立 ``db_session()`` 的每请求 2-4 连接借用。

        按短路顺序复用同一 session（核心目标：每请求仅 **1** 连接 checkout，替代改前最多 4 连接）：
        停用 / 用户不存在 → 直接 deny 快照；超管 → 不查 permissions/scope（ALL 范围）；普通用户才查
        ``menu.perms`` 权限集 + O2 归一 data_scope。账号状态校验与 ``a_get_is_super_admin`` 同源
        （停用超管不短路，spec §2.3）。注（对抗审查 skeptic）：普通路径 ``user.get`` 发**两次** users
        SELECT —— repository 用 ``select().where()`` 不走 ``session.get()`` 的 identity-map 短路；但
        同连接同事务、对象实例复用无 stale，真正零往返需 repo 切 ``session.get()``（排期，非安全项）。
        """
        async with db_session() as session:
            user = await UserRepository(session).get(user_id)
            if user is None or user.status != "active":
                return AuthzContext(
                    False, False, frozenset(), DataScope(ScopeType.SELF, user_id=user_id)
                )
            if user.is_super_admin:
                return AuthzContext(
                    True, True, frozenset(), DataScope(ScopeType.ALL, user_id=user_id)
                )
            permissions = await MenuRepository(session).list_perms_for_user(user_id)
            data_scope = await compute_effective_data_scope(
                user_id,
                user_repo=UserRepository(session),
                role_repo=RoleRepository(session),
                dept_repo=DeptRepository(session),
            )
            return AuthzContext(True, False, permissions, data_scope)

    # ---- 失效语义（P1 无缓存，no-op；接口先冻结，P2 接 Redis 时实现）----

    def invalidate_user(self, user_id: int) -> None:
        pass

    def invalidate_role(self, role_id: int) -> None:
        pass

    def invalidate_all(self) -> None:
        pass
