"""RBAC seed 集成测试（spec §13.1）—— 幂等建树 + 不碰用户自建 + 角色 upsert。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.menu.models import Menu, RoleMenu
from admin_platform.domains.menu.repository import MenuRepository
from admin_platform.domains.role.models import Role
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.user.models import User
from admin_platform.rbac.seed import MENU_TREE, SeedMenu, seed_rbac
from tests.integration.db_cleanup import truncate_tables

pytestmark = pytest.mark.integration


async def _wipe() -> None:
    await truncate_tables("role_menus", "user_roles", "menus", "roles", "users")


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
    assert role is not None and role.data_scope == "self"  # 展示角色，最小范围（PK 修复）
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


async def test_superadmin_role_data_scope_is_self() -> None:
    # Codex 系统级 PK：superadmin 展示角色 data_scope=self（非 all）——误绑普通用户不扩数据权限。
    async with db_session() as session:
        await seed_rbac(session)
    async with db_session() as session:
        role = await session.scalar(select(Role).where(Role.code == "superadmin"))
    assert role is not None
    assert role.data_scope == "self"


async def test_seed_rerun_preserves_role_menus_binding() -> None:
    # Codex 建议：menu update-in-place 保 id → seed 重跑后用户对内置菜单的 role_menus 绑定不丢。
    async with db_session() as session:
        await seed_rbac(session)
        menu = await session.scalar(select(Menu).where(Menu.seed_key == "system:user:add"))
        assert menu is not None
        role = Role(name="r", code="custom-ops", data_scope="self", status="active")
        session.add(role)
        user = User(username="u-bind", password_hash="x")
        session.add(user)
        await session.flush()
        await MenuRepository(session).set_role_menus(role.id, [menu.id])
        await RoleRepository(session).set_user_roles(user.id, [role.id])
        role_id, menu_id = role.id, menu.id
    # 重跑 seed
    async with db_session() as session:
        await seed_rbac(session)
    async with db_session() as session:
        binding = await session.scalar(
            select(RoleMenu).where(RoleMenu.role_id == role_id, RoleMenu.menu_id == menu_id)
        )
        same_menu = await session.scalar(select(Menu).where(Menu.seed_key == "system:user:add"))
    assert binding is not None, "seed 重跑后 role_menus 绑定丢失（菜单 id 变了）"
    assert same_menu is not None and same_menu.id == menu_id


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
