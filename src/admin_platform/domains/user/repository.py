"""User repository —— SQLAlchemy 2.x async 数据访问。返回 ORM 行 / None / bool，不抛业务异常。

多租户隔离正确性（经 Codex PK，关键）：

  * **读全程显式 ``select(User).where(...)`` + execute**，不用 ``session.get``——后者命中 identity
    map 时跳过 SQL、不触发 ``do_orm_execute``，``with_loader_criteria`` 租户过滤会被绕过。
  * **写走 ORM unit-of-work**（``add`` / ``session.delete``），不用 bulk ``update()`` / ``delete()``——
    bulk DML 是非 SELECT，``do_orm_execute`` 早 return、``before_flush`` 也看不到逐对象，二者都会
    绕过租户隔离（A 租户可按 id 删 B 租户行）。
  * ``count`` 用 ``select(func.count()).select_from(User)``（ORM 实体，**非** ``User.__table__``）——
    实体形式才会被注入 ``WHERE tenant_id=``，``__table__`` / raw SQL 不受保护。

故跨租户 id 在 get/update/delete 会被追加 tenant 过滤 → 查不到 → service 抛 404（隔离即 404）。
"""

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

    async def get(self, user_id: int) -> User | None:
        # 显式 select（非 session.get）：保证经 do_orm_execute → 租户过滤生效。
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def find_by_username(self, username: str) -> User | None:
        """按 username 查找（唯一性预检用）。租户上下文下天然租户内 scoped。"""
        result = await self._session.execute(select(User).where(User.username == username).limit(1))
        return result.scalar_one_or_none()

    async def create(self, payload: UserCreate, *, password_hash: str) -> User:
        # 不设 tenant_id —— before_flush 按当前租户上下文自动填。
        obj = User(
            username=payload.username,
            password_hash=password_hash,
            nickname=payload.nickname,
        )
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(
        self, user_id: int, payload: UserUpdate, *, password_hash: str | None
    ) -> User | None:
        obj = await self.get(user_id)  # 租户过滤的 select；跨租户 → None
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True, exclude={"password"}).items():
            setattr(obj, key, value)
        if password_hash is not None:
            obj.password_hash = password_hash
        await self._session.flush()
        return obj

    async def delete(self, user_id: int) -> bool:
        obj = await self.get(user_id)  # 租户过滤的 select；跨租户 → None → False
        if obj is None:
            return False
        await self._session.delete(obj)  # ORM unit-of-work（非 bulk delete）→ 经 before_flush
        return True
