"""Todo repository — SQLAlchemy 2.x async 数据访问层。

repository 契约：返回 ORM 行 / ``None`` / ``bool``。**不抛业务异常** ——
那是 service 层的事（见 ``doc/standards/AI_CODING_RULES.md`` §「分层硬约束」）。

v0.5.1 — 多对多处理
-------------------
所有读路径都用 ``selectinload(Todo.tags)`` 一次性预加载关联 tag。这是项目
的 N+1 防御模式：``Todo.tags`` 声明为 ``lazy="raise"``，**忘记加 eager
option 会抛 StatementError**，而不是按行发查询。

写路径接受 ``tags`` 关键字参数：
  * ``None`` — 保留现有关联不动（PATCH 语义）
  * ``[]`` — 清空所有关联
  * ``list[Tag]`` — 全量替换（调用方负责把 id 转成 ORM 对象）
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from admin_platform.domains.tag.models import Tag
from admin_platform.domains.todo.models import Todo
from admin_platform.domains.todo.schemas import TodoCreate, TodoUpdate


class TodoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paginated(self, page: int, size: int) -> list[Todo]:
        offset = (page - 1) * size
        stmt = (
            select(Todo)
            .options(selectinload(Todo.tags))
            .offset(offset)
            .limit(size)
            .order_by(Todo.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        stmt = select(func.count()).select_from(Todo)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def get(self, item_id: int) -> Todo | None:
        stmt = select(Todo).where(Todo.id == item_id).options(selectinload(Todo.tags))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_title(self, title: str) -> Todo | None:
        """按业务唯一键 ``title`` 查找。service 层 insert 前唯一性预检用 ——
        让 service 抛干净的领域错误码，而不是泄露 DB ``IntegrityError``。"""
        stmt = select(Todo).where(Todo.title == title).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, payload: TodoCreate, *, tags: list[Tag] | None = None) -> Todo:
        # ``model_dump(exclude={"tag_ids"})`` 把关联 payload 剥掉 —— Todo 列
        # 属性只接 schema 里的列字段。
        obj = Todo(**payload.model_dump(exclude={"tag_ids"}))
        # 即使 tags 为空也显式赋值。relationship 声明 ``lazy="raise"``，
        # 后续读 ``obj.tags``（如 ``TodoRead.model_validate`` 构造响应）
        # 会触发 lazy-raise；直接赋值是**写**不是**读**，绕开了 lazy load。
        obj.tags = tags or []
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(
        self,
        item_id: int,
        payload: TodoUpdate,
        *,
        tags: list[Tag] | None = None,
    ) -> Todo | None:
        # 先把 tags eager-load 进来，下面 ``obj.tags = ...`` 赋值时不会触发
        # lazy="raise"。
        stmt = select(Todo).where(Todo.id == item_id).options(selectinload(Todo.tags))
        result = await self._session.execute(stmt)
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True, exclude={"tag_ids"}).items():
            setattr(obj, key, value)
        if tags is not None:
            obj.tags = tags
        await self._session.flush()
        return obj

    async def delete(self, item_id: int) -> bool:
        obj = await self._session.get(Todo, item_id)
        if obj is None:
            return False
        await self._session.delete(obj)
        return True
