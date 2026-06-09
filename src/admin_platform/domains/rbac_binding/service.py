"""RBAC 绑定用例 —— 跨域组合（user-role / user-post / role-menu / role-dept 全量替换）。

补 P1 缺口（review 🔴）：repository 已有 ``set_*`` 但无 service/API 出口 → 管理端不可配 RBAC。
经 deps 注入各域 repository（共享一请求 session），统一：
  ① 主体存在 + 数据权限可见性校验；② 绑定 ids all-or-nothing 存在性校验（缺失 422）；
  ③ 调既有 ``set_*``（全量替换，advisory lock 串行化）；④ emit ``rbac_write``（成功/失败都记）。

分层：抛 ``AppError``（不抛 HTTPException）；不 import fastapi / CurrentUser —— actor 由 api 层
传 ``AuditActor``。跨域 repository 仅构造注入（deps.py 组装）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from admin_platform.audit.emit import emit_rbac_write
from admin_platform.audit.events import AuditActor, AuditTarget
from admin_platform.authz.data_scope import is_dept_visible
from admin_platform.authz.scope import DataScope
from admin_platform.core.errors import AUTH_FORBIDDEN_BY_ROLE, AUTH_FORBIDDEN_BY_SCOPE, AppError
from admin_platform.domains.dept.repository import DeptRepository
from admin_platform.domains.menu.repository import MenuRepository
from admin_platform.domains.post.repository import PostRepository
from admin_platform.domains.role.models import Role
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.user.models import User
from admin_platform.domains.user.repository import UserRepository

USER_NOT_FOUND = "admin_platform.USER_NOT_FOUND"
ROLE_NOT_FOUND = "role.NOT_FOUND"
ROLE_IDS_INVALID = "admin_platform.ROLE_IDS_INVALID"
POST_IDS_INVALID = "admin_platform.POST_IDS_INVALID"
MENU_IDS_INVALID = "role.MENU_IDS_INVALID"
DEPT_IDS_INVALID = "role.DEPT_IDS_INVALID"


def _user_visible(user: User, scope: DataScope) -> bool:
    """用户行是否在数据范围内（镜像 ``user.service._user_visible``：所属部门可见 / SELF 本人）。"""
    return is_dept_visible(scope, user.dept_id) or (scope.include_self and user.id == scope.user_id)


class RbacBindingService:
    def __init__(
        self,
        *,
        user_repo: UserRepository,
        role_repo: RoleRepository,
        menu_repo: MenuRepository,
        post_repo: PostRepository,
        dept_repo: DeptRepository,
    ) -> None:
        self._user_repo = user_repo
        self._role_repo = role_repo
        self._menu_repo = menu_repo
        self._post_repo = post_repo
        self._dept_repo = dept_repo

    # ---- user-role ----------------------------------------------------------

    async def set_user_roles(
        self,
        user_id: int,
        role_ids: list[int],
        *,
        operator: AuditActor,
        scope: DataScope | None = None,
    ) -> list[int]:
        action = "system:user:bind_roles"
        try:
            # 提权防护（Codex 🔴-1，用户拍板「超管专属角色分配」2026-06-09）：user-role 直接改变
            # 被绑用户的后端权限集（role_menus→menus.perms），非超管持 system:user:edit 即可给
            # 可见用户/自己绑高权限角色自我提权 → 收紧为仅 is_super_admin 可写（保守 + 可逆）。
            self._require_super_admin(operator)
            user = await self._require_visible_user(user_id, scope)
            deduped = list(dict.fromkeys(role_ids))
            await self._require_ids_exist(
                self._role_repo.list_existing_ids, deduped, ROLE_IDS_INVALID, "role"
            )
            await self._role_repo.set_user_roles(user_id, deduped)
        except AppError as exc:
            await self._audit_fail(operator, action, "user", user_id, exc)
            raise
        await self._audit_ok(
            operator, action, "user", user_id, user.username, {"role_ids": deduped}
        )
        return deduped

    async def get_user_roles(self, user_id: int, *, scope: DataScope | None = None) -> list[int]:
        await self._require_visible_user(user_id, scope)
        return await self._role_repo.list_role_ids_for_user(user_id)

    # ---- user-post ----------------------------------------------------------

    async def set_user_posts(
        self,
        user_id: int,
        post_ids: list[int],
        *,
        operator: AuditActor,
        scope: DataScope | None = None,
    ) -> list[int]:
        action = "system:user:bind_posts"
        try:
            user = await self._require_visible_user(user_id, scope)
            deduped = list(dict.fromkeys(post_ids))
            await self._require_ids_exist(
                self._post_repo.list_existing_ids, deduped, POST_IDS_INVALID, "post"
            )
            await self._post_repo.set_user_posts(user_id, deduped)
        except AppError as exc:
            await self._audit_fail(operator, action, "user", user_id, exc)
            raise
        await self._audit_ok(
            operator, action, "user", user_id, user.username, {"post_ids": deduped}
        )
        return deduped

    async def get_user_posts(self, user_id: int, *, scope: DataScope | None = None) -> list[int]:
        await self._require_visible_user(user_id, scope)
        return await self._post_repo.list_post_ids_for_user(user_id)

    # ---- role-menu ----------------------------------------------------------

    async def set_role_menus(
        self, role_id: int, menu_ids: list[int], *, operator: AuditActor
    ) -> list[int]:
        # role-menu 无 data_scope 语义（menu/role 均全局配置资源）。提权防护（Codex 🔴-1）：
        # role-menu 直接改角色的权限图谱（加高权限菜单到自己持有的角色即自我提权），与 user-role
        # 同属权限图谱写 → 收紧为仅 is_super_admin（用户拍板「超管专属」2026-06-09）。
        action = "system:role:bind_menus"
        try:
            self._require_super_admin(operator)
            role = await self._require_role(role_id)
            deduped = list(dict.fromkeys(menu_ids))
            await self._require_ids_exist(
                self._menu_repo.list_existing_ids, deduped, MENU_IDS_INVALID, "menu"
            )
            await self._menu_repo.set_role_menus(role_id, deduped)
        except AppError as exc:
            await self._audit_fail(operator, action, "role", role_id, exc)
            raise
        await self._audit_ok(operator, action, "role", role_id, role.code, {"menu_ids": deduped})
        return deduped

    async def get_role_menus(self, role_id: int) -> list[int]:
        await self._require_role(role_id)
        return await self._menu_repo.list_menu_ids_for_role(role_id)

    # ---- role-dept ----------------------------------------------------------

    async def set_role_depts(
        self,
        role_id: int,
        dept_ids: list[int],
        *,
        operator: AuditActor,
        scope: DataScope | None = None,
    ) -> list[int]:
        action = "system:role:bind_depts"
        try:
            role = await self._require_role(role_id)
            deduped = list(dict.fromkeys(dept_ids))
            await self._require_ids_exist(
                self._dept_repo.list_existing_ids, deduped, DEPT_IDS_INVALID, "dept"
            )
            # 数据权限写侧（Codex 风险 #2 + Round-3 写侧对称）：set_role_depts 是先全删后插的全量
            # 替换。非超管操作时，① 新增 ids 必须可见；② 既有绑定也必须全部可见——否则全删会
            # 静默清除范围外（不可见）部门绑定（scoped operator 篡改了范围外数据），与读侧 403
            # 对称，强制此类角色由超管操作。超管 scope=ALL → is_dept_visible 恒 True，不受限。
            if scope is not None:
                existing = await self._role_repo.list_custom_dept_ids_for_role(role_id)
                for dept_id in (*deduped, *existing):
                    if not is_dept_visible(scope, dept_id):
                        raise self._forbidden_scope()
            await self._role_repo.set_role_depts(role_id, deduped)
        except AppError as exc:
            await self._audit_fail(operator, action, "role", role_id, exc)
            raise
        await self._audit_ok(operator, action, "role", role_id, role.code, {"dept_ids": deduped})
        return deduped

    async def get_role_depts(self, role_id: int, *, scope: DataScope | None = None) -> list[int]:
        await self._require_role(role_id)
        dept_ids = sorted(await self._role_repo.list_custom_dept_ids_for_role(role_id))
        # 数据权限读侧对称（Codex 深审 🟡-3）：非超管若绑定集含不可见部门则 403，与
        # set_role_depts 写侧一致——既不泄露范围外部门 id，也避免"读到却无法安全全量 PUT 回"
        # 的管理端陷阱（读子集 → PUT 会误删范围外绑定）。
        if scope is not None:
            for dept_id in dept_ids:
                if not is_dept_visible(scope, dept_id):
                    raise self._forbidden_scope()
        return dept_ids

    # ---- helpers ------------------------------------------------------------

    async def _require_visible_user(self, user_id: int, scope: DataScope | None) -> User:
        user = await self._user_repo.get(user_id)
        if user is None or (scope is not None and not _user_visible(user, scope)):
            # 不可见 = 当作不存在（不泄露存在性，与 user/dept get 同口径）。
            raise AppError(
                code=USER_NOT_FOUND, title="User not found", detail=f"id={user_id}", status_code=404
            )
        return user

    async def _require_role(self, role_id: int) -> Role:
        role = await self._role_repo.get(role_id)
        if role is None:
            raise AppError(
                code=ROLE_NOT_FOUND, title="Role not found", detail=f"id={role_id}", status_code=404
            )
        return role

    @staticmethod
    async def _require_ids_exist(
        lookup: Callable[[list[int]], Awaitable[set[int]]],
        ids: list[int],
        code: str,
        label: str,
    ) -> None:
        """all-or-nothing：``ids`` 必须全部存在，否则 422（先查齐再 set，不靠 FK 退化成 409）。"""
        if not ids:
            return
        existing = await lookup(ids)
        missing = [i for i in ids if i not in existing]
        if missing:
            raise AppError(
                code=code,
                title=f"{label} ids invalid",
                detail=f"不存在的 {label} id: {sorted(missing)}",
                status_code=422,
            )

    @staticmethod
    def _require_super_admin(operator: AuditActor) -> None:
        """权限图谱写（user-role / role-menu）超管专属（Codex 🔴-1，用户拍板 2026-06-09）。
        非超管即使持 system:user:edit / system:role:edit 也不得改权限图谱，杜绝自我提权。
        """
        if not operator.is_super_admin:
            raise AppError(
                code=AUTH_FORBIDDEN_BY_ROLE,
                title="Forbidden",
                detail="角色/权限图谱分配仅超级管理员可操作",
                status_code=403,
            )

    @staticmethod
    def _forbidden_scope() -> AppError:
        return AppError(
            code=AUTH_FORBIDDEN_BY_SCOPE,
            title="Forbidden by data scope",
            detail="目标部门不在你的数据权限范围内",
            status_code=403,
        )

    @staticmethod
    async def _audit_ok(  # noqa: PLR0913 —— 审计字段多（target 三段 + metadata），全命名参数可放宽
        operator: AuditActor,
        action: str,
        target_type: str,
        target_id: int,
        display: str | None,
        metadata: dict[str, object],
    ) -> None:
        # 成功绑定审计走 in-tx（review F1 方案 B：emit_rbac_write success → 写业务 session）。
        await emit_rbac_write(
            actor=operator,
            action=action,
            target=AuditTarget(type=target_type, id=str(target_id), display=display),
            status="success",
            http_status=200,
            metadata=metadata,
        )

    @staticmethod
    async def _audit_fail(
        operator: AuditActor, action: str, target_type: str, target_id: int, exc: AppError
    ) -> None:
        await emit_rbac_write(
            actor=operator,
            action=action,
            target=AuditTarget(type=target_type, id=str(target_id), display=None),
            status="failure",
            http_status=exc.status_code,
            error_code=exc.code,
        )
