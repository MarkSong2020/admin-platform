"""User service —— 业务用例层。事务边界由 ``get_session`` 拥有（一请求 = 一事务）。

业务不变式：

  * **username 全局唯一** —— create/update 前用 ``find_by_username`` 预检，违反抛 409
    ``admin_platform.USERNAME_DUPLICATE``。DB 的 ``uq_users_username`` 是竞态兜底：并发预检
    都通过时第二个 INSERT 撞约束 → ``IntegrityError`` handler 按 ``models.py`` 注册的映射
    翻成同一个 409 业务码。

分层：service 抛 ``AppError``（不抛 HTTPException），持有注入的 repository（单测可 stub）。
"""

from __future__ import annotations

from admin_platform.authz.data_scope import is_dept_visible
from admin_platform.authz.scope import DataScope
from admin_platform.core.errors import AUTH_FORBIDDEN_BY_SCOPE, AppError
from admin_platform.core.security import ahash_password
from admin_platform.domains.user.models import User
from admin_platform.domains.user.repository import UserRepository
from admin_platform.domains.user.schemas import UserCreate, UserPage, UserRead, UserUpdate

NOT_FOUND_CODE = "admin_platform.USER_NOT_FOUND"
USERNAME_DUPLICATE_CODE = "admin_platform.USERNAME_DUPLICATE"
LAST_SUPER_ADMIN_CODE = "admin_platform.LAST_SUPER_ADMIN"

_ACTIVE = "active"


def _user_visible(row: User, scope: DataScope) -> bool:
    """用户行是否在数据范围内：所属部门可见，或（SELF 段）就是本人记录。

    data_scope 的核心对象是用户（对标若依「用户按部门可见」）：非超管只能看 / 改 / 删
    所属部门在 ``visible_dept_ids`` 内的用户；``include_self`` 时额外放行本人记录
    （``row.id == scope.user_id``）。``scope_type == ALL``（含超管短路）不受限。
    """
    return is_dept_visible(scope, row.dept_id) or (scope.include_self and row.id == scope.user_id)


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self._repo = repository

    async def list_(self, *, page: int, size: int, scope: DataScope | None = None) -> UserPage:
        """``scope`` 非空时按数据权限过滤可见用户（非超管必传；超管 api 层传 ALL，不过滤）。"""
        rows = await self._repo.list_paginated(page, size, scope=scope)
        total = await self._repo.count(scope=scope)
        total_pages = (total + size - 1) // size if size > 0 else 0
        return UserPage(
            items=[UserRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=total_pages,
        )

    async def get(self, user_id: int, *, scope: DataScope | None = None) -> UserRead:
        row = await self._repo.get(user_id)
        if row is None or (scope is not None and not _user_visible(row, scope)):
            # 数据权限不可见 = 当作不存在（不泄露存在性，与 dept get 同口径）。
            raise self._not_found(user_id)
        return UserRead.model_validate(row)

    async def create(self, payload: UserCreate, *, scope: DataScope | None = None) -> UserRead:
        # 数据权限写侧：非超管只能把用户建到可见部门（含 dept_id=None 时落不可见 → 403）。
        if scope is not None and not is_dept_visible(scope, payload.dept_id):
            raise self._forbidden_scope()
        if await self._repo.find_by_username(payload.username) is not None:
            raise self._duplicate(payload.username)
        row = await self._repo.create(payload, password_hash=await ahash_password(payload.password))
        return UserRead.model_validate(row)

    async def update(
        self, user_id: int, payload: UserUpdate, *, scope: DataScope | None = None
    ) -> UserRead:
        row = await self._repo.get(user_id)
        if row is None or (scope is not None and not _user_visible(row, scope)):
            raise self._not_found(user_id)
        # 改 dept_id 到不可见部门 → 403（不能把用户挪到数据范围外）。
        if (
            scope is not None
            and "dept_id" in payload.model_fields_set
            and not is_dept_visible(scope, payload.dept_id)
        ):
            raise self._forbidden_scope()
        # 禁用最后一个超管 = 系统失去管理入口，拒之（数据完整性，P0.9 review C）。
        if (
            payload.status is not None
            and payload.status != _ACTIVE
            and row.is_super_admin
            and await self._repo.count_super_admins() <= 1
        ):
            raise self._last_super_admin()
        password_hash = (
            await ahash_password(payload.password) if payload.password is not None else None
        )
        row = await self._repo.update(user_id, payload, password_hash=password_hash)
        if row is None:  # 并发删除兜底
            raise self._not_found(user_id)
        return UserRead.model_validate(row)

    async def delete(self, user_id: int, *, scope: DataScope | None = None) -> None:
        row = await self._repo.get(user_id)
        if row is None or (scope is not None and not _user_visible(row, scope)):
            raise self._not_found(user_id)
        # 删最后一个超管 = 系统失去管理入口，拒之（数据完整性，P0.9 review C）。
        if row.is_super_admin and await self._repo.count_super_admins() <= 1:
            raise self._last_super_admin()
        await self._repo.delete(user_id)

    @staticmethod
    def _not_found(user_id: int) -> AppError:
        return AppError(
            code=NOT_FOUND_CODE,
            title="User not found",
            detail=f"id={user_id}",
            status_code=404,
        )

    @staticmethod
    def _duplicate(username: str) -> AppError:
        return AppError(
            code=USERNAME_DUPLICATE_CODE,
            title="Username already exists",
            detail=f"username={username!r}",
            status_code=409,
        )

    @staticmethod
    def _last_super_admin() -> AppError:
        return AppError(
            code=LAST_SUPER_ADMIN_CODE,
            title="Cannot remove the last super admin",
            detail="系统必须保留至少一个超级管理员",
            status_code=409,
        )

    @staticmethod
    def _forbidden_scope() -> AppError:
        return AppError(
            code=AUTH_FORBIDDEN_BY_SCOPE,
            title="Forbidden by data scope",
            detail="目标部门不在你的数据权限范围内",
            status_code=403,
        )
