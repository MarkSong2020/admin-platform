"""User repository —— SQLAlchemy 2.x async 数据访问。返回 ORM 行 / None / bool，不抛业务异常。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.user.models import User
from admin_platform.domains.user.schemas import UserCreate, UserUpdate


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paginated(self, page: int, size: int) -> list[User]:
        offset = (page - 1) * size
        stmt = select(User).offset(offset).limit(size).order_by(User.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(User))
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
