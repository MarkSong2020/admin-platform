"""User repository —— SQLAlchemy 2.x async 数据访问。返回 ORM 行 / None / bool，不抛业务异常。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import ClassVar

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.authz.data_scope import apply_data_scope
from admin_platform.authz.scope import DataScope
from admin_platform.core.pagination import SortColumn, SortExpr, ilike_contains
from admin_platform.domains.user.models import User
from admin_platform.domains.user.schemas import UserCreate, UserListQuery, UserUpdate


def _user_filters(query: UserListQuery) -> list[ColumnElement[bool]]:
    """把过滤 DTO 翻成 WHERE 条件列表（参数化，无字符串拼接）。

    关键字走 ``ilike_contains``（bind param 参数化 + 转义 ``%`` / ``_`` 元字符，字面安全）；状态/部门
    精确；created_at 范围闭区间。list 与 count 共用此函数 → 两者 WHERE 一致，total 反映过滤后数量。
    """
    conds: list[ColumnElement[bool]] = []
    if query.username:
        conds.append(ilike_contains(User.username, query.username))
    if query.status is not None:
        conds.append(User.status == query.status)
    if query.dept_id is not None:
        conds.append(User.dept_id == query.dept_id)
    if query.created_at_begin is not None:
        conds.append(User.created_at >= query.created_at_begin)
    if query.created_at_end is not None:
        conds.append(User.created_at <= query.created_at_end)
    return conds


class UserRepository:
    # 排序 allowlist（防注入红线）：order_by 字符串只用作此字典 key 查 ORM Column，命中才排序。
    # 不在表内 → service 的 resolve_sort 抛 422，绝不把客户端字符串拼进 SQL。仅暴露可安全排序的列
    # （不含 password_hash 等敏感列）。SORT_DEFAULT 含 id tiebreaker，保 offset 分页跨页稳定。
    SORT_ALLOWED: ClassVar[Mapping[str, SortColumn]] = {
        "id": User.id,
        "username": User.username,
        "created_at": User.created_at,
    }
    SORT_DEFAULT: ClassVar[Sequence[SortExpr]] = [User.id]
    # 显式 order_by 命中非唯一列时追加的稳定 tie-breaker（pk，唯一）——保 OFFSET 深分页不跨页跳行。
    SORT_TIE_BREAK: ClassVar[SortColumn] = User.id

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _scoped_filtered(
        self, query: UserListQuery, *, scope: DataScope | None
    ) -> Select[tuple[User]]:
        """data_scope（数据权限）+ 过滤条件 AND 叠加的基础 select（list / count 共用）。

        data_scope 先于过滤注入：新过滤是 ``AND`` 叠加在数据权限之上（不替换），非超管仍只能
        看见 / 过滤其可见范围内的用户——过滤绕不过数据权限。
        """
        stmt = select(User)
        if scope is not None:
            # 用户按所属部门过滤；SELF 段 = 本人记录（owner_col=User.id，即 row.id==当前用户）。
            stmt = apply_data_scope(stmt, scope, dept_col=User.dept_id, owner_col=User.id)
        return stmt.where(*_user_filters(query))

    async def list_paginated(
        self,
        query: UserListQuery,
        page: int,
        size: int,
        *,
        order_by: Sequence[SortExpr],
        scope: DataScope | None = None,
    ) -> list[User]:
        offset = (page - 1) * size
        stmt = (
            self._scoped_filtered(query, scope=scope).order_by(*order_by).offset(offset).limit(size)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, query: UserListQuery, *, scope: DataScope | None = None) -> int:
        inner = self._scoped_filtered(query, scope=scope).subquery()
        result = await self._session.execute(select(func.count()).select_from(inner))
        return int(result.scalar_one())

    async def count_super_admins(self) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(User).where(User.is_super_admin.is_(True))
        )
        return int(result.scalar_one())

    async def get(self, user_id: int) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def find_by_username(self, username: str) -> User | None:
        """按 username 查找（唯一性预检用）。"""
        result = await self._session.execute(select(User).where(User.username == username).limit(1))
        return result.scalar_one_or_none()

    async def create(self, payload: UserCreate, *, password_hash: str) -> User:
        obj = User(
            username=payload.username,
            password_hash=password_hash,
            nickname=payload.nickname,
            dept_id=payload.dept_id,
        )
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(
        self, user_id: int, payload: UserUpdate, *, password_hash: str | None
    ) -> User | None:
        obj = await self.get(user_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True, exclude={"password"}).items():
            setattr(obj, key, value)
        if password_hash is not None:
            obj.password_hash = password_hash
        await self._session.flush()
        return obj

    async def delete(self, user_id: int) -> bool:
        obj = await self.get(user_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True
