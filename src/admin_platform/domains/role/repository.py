"""Role repository — SQLAlchemy 2.x async 数据访问层。返回 ORM 行 / None / 集合，不抛业务异常。

除标准 CRUD 外，承载 RBAC 关联查询（供 ``provider`` 的 O2 归一）与绑定写：
  * ``list_roles_for_user`` —— JOIN ``user_roles`` 取用户的全部角色（各带 data_scope）。
  * ``list_custom_dept_ids_for_role`` —— ``CUSTOM_DEPT`` 范围的自定义部门集合（``role_depts``）。
  * ``set_user_roles`` / ``set_role_depts`` —— 全量替换绑定（先删后插，幂等）。
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.role.models import Role, RoleDept, UserRole
from admin_platform.domains.role.schemas import RoleCreate, RoleUpdate


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paginated(self, page: int, size: int) -> list[Role]:
        offset = (page - 1) * size
        stmt = select(Role).offset(offset).limit(size).order_by(Role.sort_order, Role.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(Role))
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
        """用户拥有的全部角色（JOIN ``user_roles``，各带 data_scope）。"""
        stmt = (
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
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
        """全量替换用户的角色绑定（去重；空列表 = 解绑所有角色）。"""
        await self._session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        await self._session.flush()
        for role_id in dict.fromkeys(role_ids):
            self._session.add(UserRole(user_id=user_id, role_id=role_id))
        await self._session.flush()

    async def set_role_depts(self, role_id: int, dept_ids: list[int]) -> None:
        """全量替换角色的自定义部门绑定（去重；空列表 = 清空自定义部门）。"""
        await self._session.execute(delete(RoleDept).where(RoleDept.role_id == role_id))
        await self._session.flush()
        for dept_id in dict.fromkeys(dept_ids):
            self._session.add(RoleDept(role_id=role_id, dept_id=dept_id))
        await self._session.flush()
