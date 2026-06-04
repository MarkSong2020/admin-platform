"""User 组合根（Composition Root）。

把 ``UserService`` 的依赖（repository + AsyncSession）在此组装，使 ``api.py`` 只依赖 service、
不直接 import repository（分层契约 C2）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db.session import get_session
from admin_platform.domains.user.repository import UserRepository
from admin_platform.domains.user.service import UserService


async def get_user_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserService:
    return UserService(UserRepository(session))
