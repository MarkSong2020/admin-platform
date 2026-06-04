"""User service —— 业务用例层。事务边界由 ``get_session`` 拥有（一请求 = 一事务）。

业务不变式：

  * **username 全局唯一** —— create/update 前用 ``find_by_username`` 预检，违反抛 409
    ``admin_platform.USERNAME_DUPLICATE``。DB 的 ``uq_users_username`` 是竞态兜底：并发预检
    都通过时第二个 INSERT 撞约束 → ``IntegrityError`` handler 按 ``models.py`` 注册的映射
    翻成同一个 409 业务码。

分层：service 抛 ``AppError``（不抛 HTTPException），持有注入的 repository（单测可 stub）。
"""

from __future__ import annotations

from admin_platform.core.errors import AppError
from admin_platform.core.security import hash_password
from admin_platform.domains.user.repository import UserRepository
from admin_platform.domains.user.schemas import UserCreate, UserPage, UserRead, UserUpdate

NOT_FOUND_CODE = "admin_platform.USER_NOT_FOUND"
USERNAME_DUPLICATE_CODE = "admin_platform.USERNAME_DUPLICATE"


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self._repo = repository

    async def list_(self, *, page: int, size: int) -> UserPage:
        rows = await self._repo.list_paginated(page, size)
        total = await self._repo.count()
        total_pages = (total + size - 1) // size if size > 0 else 0
        return UserPage(
            items=[UserRead.model_validate(row) for row in rows],
            page=page,
            size=size,
            total=total,
            total_pages=total_pages,
        )

    async def get(self, user_id: int) -> UserRead:
        row = await self._repo.get(user_id)
        if row is None:
            raise self._not_found(user_id)
        return UserRead.model_validate(row)

    async def create(self, payload: UserCreate) -> UserRead:
        if await self._repo.find_by_username(payload.username) is not None:
            raise self._duplicate(payload.username)
        row = await self._repo.create(payload, password_hash=hash_password(payload.password))
        return UserRead.model_validate(row)

    async def update(self, user_id: int, payload: UserUpdate) -> UserRead:
        password_hash = hash_password(payload.password) if payload.password is not None else None
        row = await self._repo.update(user_id, payload, password_hash=password_hash)
        if row is None:
            raise self._not_found(user_id)
        return UserRead.model_validate(row)

    async def delete(self, user_id: int) -> None:
        if not await self._repo.delete(user_id):
            raise self._not_found(user_id)

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
