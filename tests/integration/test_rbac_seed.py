"""RBAC seed 集成测试（spec §13.1）—— 幂等建树 + 不碰用户自建 + 角色 upsert。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.menu.models import Menu
from admin_platform.domains.role.models import Role
from admin_platform.rbac.seed import MENU_TREE, SeedMenu, seed_rbac

pytestmark = pytest.mark.integration


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE menus, roles CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


def _count(nodes: tuple[SeedMenu, ...]) -> int:
    return sum(1 + _count(n.children) for n in nodes)


_EXPECTED = _count(MENU_TREE)  # 1 系统目录 + 5 菜单 + 20 按钮 = 26


async def test_seed_creates_tree_and_role() -> None:
    async with db_session() as session:
        result = await seed_rbac(session)
    assert result.menus_upserted == _EXPECTED
    assert result.menus_pruned == 0
    async with db_session() as session:
        menu_count = await session.scalar(select(func.count()).select_from(Menu))
        role = await session.scalar(select(Role).where(Role.code == "superadmin"))
        btn = await session.scalar(select(Menu).where(Menu.seed_key == "system:user:add"))
        cat = await session.scalar(select(Menu).where(Menu.seed_key == "system"))
    assert menu_count == _EXPECTED
    assert role is not None and role.data_scope == "all"
    assert btn is not None and btn.menu_type == "F" and btn.perms == "system:user:add"
    assert cat is not None and cat.menu_type == "M" and cat.parent_id is None


async def test_seed_idempotent_preserves_ids() -> None:
    async with db_session() as session:
        await seed_rbac(session)
    async with db_session() as session:
        first = {m.seed_key: m.id for m in (await session.scalars(select(Menu))).all()}
        roles1 = await session.scalar(select(func.count()).select_from(Role))
    async with db_session() as session:
        result2 = await seed_rbac(session)
    async with db_session() as session:
        second = {m.seed_key: m.id for m in (await session.scalars(select(Menu))).all()}
        roles2 = await session.scalar(select(func.count()).select_from(Role))
    # update-in-place 保留 id（不破坏 role_menus 绑定）；重跑无新增/无 prune。
    assert first == second
    assert roles1 == roles2 == 1
    assert result2.menus_pruned == 0
    assert result2.menus_upserted == _EXPECTED


async def test_seed_preserves_user_menus() -> None:
    # 用户自建菜单（seed_key=None）→ seed 不碰。
    async with db_session() as session:
        user_menu = Menu(name="我的自定义", menu_type="C", path="custom")
        session.add(user_menu)
        await session.flush()
        user_menu_id = user_menu.id
    async with db_session() as session:
        await seed_rbac(session)
    async with db_session() as session:
        still_there = await session.get(Menu, user_menu_id)
        seeded = await session.scalar(
            select(func.count()).select_from(Menu).where(Menu.seed_key.is_not(None))
        )
    assert still_there is not None
    assert seeded == _EXPECTED
