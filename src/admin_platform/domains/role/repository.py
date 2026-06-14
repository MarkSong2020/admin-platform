"""Role repository — SQLAlchemy 2.x async 数据访问层。返回 ORM 行 / None / 集合，不抛业务异常。

除标准 CRUD 外，承载 RBAC 关联查询（供 ``provider`` 的 O2 归一）与绑定写：
  * ``list_roles_for_user`` —— JOIN ``user_roles`` 取用户的全部角色（各带 data_scope）。
  * ``list_custom_dept_ids_for_role`` —— ``CUSTOM_DEPT`` 范围的自定义部门集合（``role_depts``）。
  * ``set_user_roles`` / ``set_role_depts`` —— 全量替换绑定（先删后插，幂等）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import ClassVar

from sqlalchemy import ColumnElement, Select, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.core.pagination import SortColumn, SortExpr, ilike_contains
from admin_platform.domains.role.models import Role, RoleDept, UserRole
from admin_platform.domains.role.schemas import RoleCreate, RoleListQuery, RoleUpdate


def _role_filters(query: RoleListQuery) -> list[ColumnElement[bool]]:
    """把过滤 DTO 翻成 WHERE 条件列表（参数化，无字符串拼接）。list / count 共用 → WHERE 一致。"""
    conds: list[ColumnElement[bool]] = []
    if query.name:
        conds.append(ilike_contains(Role.name, query.name))
    if query.code:
        conds.append(ilike_contains(Role.code, query.code))
    if query.status is not None:
        conds.append(Role.status == query.status)
    if query.created_at_begin is not None:
        conds.append(Role.created_at >= query.created_at_begin)
    if query.created_at_end is not None:
        conds.append(Role.created_at <= query.created_at_end)
    return conds


# pg_advisory_xact_lock 的稳定 key —— 串行化绑定表「先删后插」的全量替换（Codex 深审 F3）：
# 并发两请求替换同一目标时，避免最终变成两请求的并集 / 撞 uq。事务级锁，提交/回滚自动释放。
# 与 dept 的 _DEPT_TREE_LOCK_KEY(478221) 取不同值避免跨域互锁。绑定是低频管理写，全局串行可接受。
_USER_ROLES_LOCK_KEY = 478231  # 串行化 user_roles 替换
_ROLE_DEPTS_LOCK_KEY = 478232  # 串行化 role_depts 替换


class RoleRepository:
    # 排序 allowlist（防注入红线）：order_by 字符串只用作此字典 key 查 ORM Column，命中才排序。
    # 不在表内 → service 的 resolve_sort 抛 422，绝不把客户端字符串拼进 SQL。SORT_DEFAULT 沿用
    # 既有默认序（sort_order, id），保 offset 分页跨页稳定。
    SORT_ALLOWED: ClassVar[Mapping[str, SortColumn]] = {
        "id": Role.id,
        "sort_order": Role.sort_order,
        "created_at": Role.created_at,
    }
    SORT_DEFAULT: ClassVar[Sequence[SortExpr]] = [Role.sort_order, Role.id]
    # 显式 order_by 命中非唯一列时追加的稳定 tie-breaker（pk，唯一）——保 OFFSET 深分页不跨页跳行。
    SORT_TIE_BREAK: ClassVar[SortColumn] = Role.id

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _filtered(self, query: RoleListQuery) -> Select[tuple[Role]]:
        return select(Role).where(*_role_filters(query))

    async def list_paginated(
        self, query: RoleListQuery, page: int, size: int, *, order_by: Sequence[SortExpr]
    ) -> list[Role]:
        offset = (page - 1) * size
        stmt = self._filtered(query).order_by(*order_by).offset(offset).limit(size)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, query: RoleListQuery) -> int:
        inner = self._filtered(query).subquery()
        result = await self._session.execute(select(func.count()).select_from(inner))
        return int(result.scalar_one())

    async def get(self, role_id: int) -> Role | None:
        return await self._session.get(Role, role_id)

    async def find_by_code(self, code: str) -> Role | None:
        """按 code 查找（唯一性预检用）。"""
        result = await self._session.execute(select(Role).where(Role.code == code).limit(1))
        return result.scalar_one_or_none()

    async def create(self, payload: RoleCreate) -> Role:
        obj = Role(**payload.model_dump())
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(self, role_id: int, payload: RoleUpdate) -> Role | None:
        obj = await self._session.get(Role, role_id)
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self._session.flush()
        # onupdate=func.now() 让 updated_at 在 UPDATE 后过期；异步 session 下后续序列化
        # （RoleRead 含时间戳）访问过期列会触发隐式刷新报错（Errata #7）。显式 refresh 取回新值。
        await self._session.refresh(obj)
        return obj

    async def delete(self, role_id: int) -> bool:
        obj = await self._session.get(Role, role_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True

    # ---- RBAC 关联查询（供 provider O2 归一）----------------------------------

    async def list_roles_for_user(self, user_id: int) -> list[Role]:
        """用户拥有的**生效**角色（JOIN ``user_roles``，各带 data_scope）。

        只返回 ``status == "active"`` 的角色（Codex 深审 F1）：停用角色不参与授权——
        否则一个 disabled 且 ``data_scope="all"`` 的角色仍会触发 O2 整体 ALL，形成
        「停用即撤权」失效的隐藏后门（对标若依停用角色不授权）。授权读取的唯一入口
        在此过滤，provider / 未来 get_user_permissions 都拿不到停用角色。
        """
        stmt = (
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.status == "active")
            .order_by(Role.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_custom_dept_ids_for_role(self, role_id: int) -> frozenset[int]:
        """角色 ``CUSTOM_DEPT`` 自定义数据范围的部门 id 集合（``role_depts``）。"""
        stmt = select(RoleDept.dept_id).where(RoleDept.role_id == role_id)
        result = await self._session.execute(stmt)
        return frozenset(int(dept_id) for dept_id in result.scalars().all())

    # ---- 绑定写（全量替换，先删后插）----------------------------------------

    async def set_user_roles(self, user_id: int, role_ids: list[int]) -> None:
        """全量替换用户的角色绑定（去重；空列表 = 解绑所有角色）。

        先取事务级 advisory lock 串行化「先删后插」（Codex 深审 F3）：并发两请求替换
        同一/不同用户的绑定时，避免最终落成两请求的并集或撞 ``uq_user_roles``。提交/回滚
        自动释放锁。
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_USER_ROLES_LOCK_KEY)
        )
        await self._session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        await self._session.flush()
        for role_id in dict.fromkeys(role_ids):
            self._session.add(UserRole(user_id=user_id, role_id=role_id))
        await self._session.flush()

    async def set_role_depts(self, role_id: int, dept_ids: list[int]) -> None:
        """全量替换角色的自定义部门绑定（去重；空列表 = 清空自定义部门）。

        同 ``set_user_roles``：事务级 advisory lock 串行化「先删后插」（Codex 深审 F3）。
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_ROLE_DEPTS_LOCK_KEY)
        )
        await self._session.execute(delete(RoleDept).where(RoleDept.role_id == role_id))
        await self._session.flush()
        for dept_id in dict.fromkeys(dept_ids):
            self._session.add(RoleDept(role_id=role_id, dept_id=dept_id))
        await self._session.flush()

    async def list_existing_ids(self, ids: list[int]) -> set[int]:
        """返回 ``ids`` 中实际存在的 role 子集（绑定前 all-or-nothing 校验用；空入参返回空集）。"""
        if not ids:
            return set()
        result = await self._session.execute(select(Role.id).where(Role.id.in_(ids)))
        return {int(i) for i in result.scalars().all()}

    async def list_role_ids_for_user(self, user_id: int) -> list[int]:
        """用户已绑定的角色 id（**不过滤 status**，含 disabled——管理端回显用，区别于授权读取
        的 ``list_roles_for_user`` 只取 active）。按 id 有序。"""
        stmt = (
            select(UserRole.role_id).where(UserRole.user_id == user_id).order_by(UserRole.role_id)
        )
        result = await self._session.execute(stmt)
        return [int(i) for i in result.scalars().all()]
