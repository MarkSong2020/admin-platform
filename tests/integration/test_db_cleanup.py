"""MySQL 集成测试清表 helper 回归测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text

from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.dept.models import Dept
from admin_platform.domains.role.models import Role, RoleDept, UserRole
from admin_platform.domains.user.models import User
from tests.integration.db_cleanup import truncate_tables

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await truncate_tables("depts", "roles")
    yield
    await truncate_tables("depts", "roles")
    await dispose_engine()


async def _count(table_name: str) -> int:
    async with db_session() as session:
        return int((await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))).scalar_one())


async def test_truncate_tables_expands_fk_child_closure() -> None:
    async with db_session() as session:
        dept = Dept(name="研发部", code="rd")
        role = Role(name="管理员", code="admin")
        session.add_all([dept, role])
        await session.flush()

        user = User(username="alice", password_hash="hash", dept_id=dept.id)
        session.add(user)
        await session.flush()

        session.add_all(
            [
                UserRole(user_id=user.id, role_id=role.id),
                RoleDept(role_id=role.id, dept_id=dept.id),
            ]
        )

    await truncate_tables("depts")

    assert await _count("depts") == 0
    assert await _count("users") == 0
    assert await _count("user_roles") == 0
    assert await _count("role_depts") == 0
    assert await _count("roles") == 1
