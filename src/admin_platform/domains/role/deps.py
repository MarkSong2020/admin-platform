"""Role 组合根（Composition Root）。

在此组装 RoleService 的具体依赖，使 api.py 只依赖 service、不直接
import repository（分层契约：``*.api`` 禁 import ``*.repository``）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db.session import get_session
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.role.service import RoleService


async def get_role_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoleService:
    return RoleService(RoleRepository(session))
