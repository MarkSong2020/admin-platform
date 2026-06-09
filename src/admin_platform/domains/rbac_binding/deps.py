"""RBAC 绑定组合根 —— 注入跨域 repository（共享一请求 session），api 只依赖 service。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db.session import get_session
from admin_platform.domains.dept.repository import DeptRepository
from admin_platform.domains.menu.repository import MenuRepository
from admin_platform.domains.post.repository import PostRepository
from admin_platform.domains.rbac_binding.service import RbacBindingService
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.user.repository import UserRepository


async def get_rbac_binding_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RbacBindingService:
    return RbacBindingService(
        user_repo=UserRepository(session),
        role_repo=RoleRepository(session),
        menu_repo=MenuRepository(session),
        post_repo=PostRepository(session),
        dept_repo=DeptRepository(session),
    )
