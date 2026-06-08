"""getInfo / getRouters 端点端到端集成测试（spec §6 打通）—— 真实 DbProvider + seed。

覆盖：未登录 401 / 超管 getInfo 合成 ["superadmin"]+["*:*:*"] / 非超管 getInfo 真实派生 /
超管 getRouters 见全部 seed 菜单树 / 非超管 getRouters 见授予子集 / 停用账号 getRouters 空树。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from admin_platform.api.v1.rbac import router as rbac_router
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_menu_provider, get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.menu.models import Menu
from admin_platform.domains.menu.provider import DbMenuProvider
from admin_platform.domains.menu.repository import MenuRepository
from admin_platform.domains.role.models import Role
from admin_platform.domains.role.provider import DbPermissionProvider
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.user.models import User
from admin_platform.main import create_app
from admin_platform.rbac.seed import seed_rbac

pytestmark = pytest.mark.integration


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(
            text("TRUNCATE TABLE role_menus, user_roles, menus, roles, users CASCADE")
        )


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


def _client(user_id: str | None) -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(rbac_router)
    app.dependency_overrides[get_permission_provider] = DbPermissionProvider
    app.dependency_overrides[get_menu_provider] = DbMenuProvider
    if user_id is not None:
        app.dependency_overrides[require_current_user] = lambda: CurrentUser(
            user_id=user_id, sub=user_id
        )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_user(*, username: str, is_super_admin: bool = False, status: str = "active") -> int:
    async with db_session() as session:
        user = User(
            username=username, password_hash="x", is_super_admin=is_super_admin, status=status
        )
        session.add(user)
        await session.flush()
        return user.id


def test_endpoints_mounted_in_create_app() -> None:
    # Codex 风险5：回归验证 getInfo/getRouters 真挂进生产 create_app() + MenuProvider override。
    app = create_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v1/auth/user-info" in paths
    assert "/api/v1/menus/routers" in paths
    assert app.dependency_overrides.get(get_menu_provider) is DbMenuProvider


async def test_user_info_requires_auth() -> None:
    async with _client(None) as c:
        assert (await c.get("/api/v1/auth/user-info")).status_code == 401
    await dispose_engine()


async def test_routers_requires_auth() -> None:
    async with _client(None) as c:
        assert (await c.get("/api/v1/menus/routers")).status_code == 401
    await dispose_engine()


async def test_super_admin_user_info_synthesizes() -> None:
    admin_id = await _seed_user(username="root", is_super_admin=True)
    async with _client(str(admin_id)) as c:
        res = await c.get("/api/v1/auth/user-info")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["user"]["username"] == "root"
    assert body["user"]["is_super_admin"] is True
    assert body["roles"] == ["superadmin"]
    assert body["permissions"] == ["*:*:*"]
    await dispose_engine()


async def test_super_admin_routers_sees_full_seed_tree() -> None:
    async with db_session() as session:
        await seed_rbac(session)
    admin_id = await _seed_user(username="root", is_super_admin=True)
    async with _client(str(admin_id)) as c:
        res = await c.get("/api/v1/menus/routers")
    assert res.status_code == 200, res.text
    routers = res.json()
    # seed 顶层 1 个「系统管理」目录（M），其下 5 个资源菜单（C，按钮 F 不进路由树）。
    assert len(routers) == 1
    assert routers[0]["component"] == "Layout"
    assert len(routers[0]["children"]) == 5
    await dispose_engine()


async def test_non_super_user_info_derives_real() -> None:
    # 非超管：经 role→role_menus→menus.perms 派生权限 + 角色 code。
    async with db_session() as session:
        await seed_rbac(session)
        user = User(username="staff", password_hash="x")
        session.add(user)
        role = Role(name="运维", code="ops", data_scope="self", status="active")
        session.add(role)
        await session.flush()
        # 给角色绑「用户查询」菜单（perms=system:user:query）。
        menu = await session.scalar(select(Menu).where(Menu.seed_key == "system:user:query"))
        assert menu is not None
        await MenuRepository(session).set_role_menus(role.id, [menu.id])
        await RoleRepository(session).set_user_roles(user.id, [role.id])
        uid = user.id
    async with _client(str(uid)) as c:
        res = await c.get("/api/v1/auth/user-info")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["roles"] == ["ops"]
    assert body["permissions"] == ["system:user:query"]
    assert body["user"]["is_super_admin"] is False
    await dispose_engine()


async def test_disabled_account_user_info_forbidden() -> None:
    # 停用账号 getInfo → 403（与 getRouters 空树 / require_permission 同口径，spec §2.3）。
    admin_id = await _seed_user(username="root", is_super_admin=True, status="disabled")
    async with _client(str(admin_id)) as c:
        res = await c.get("/api/v1/auth/user-info")
    assert res.status_code == 403
    assert res.json()["type"] == "auth.ACCOUNT_DISABLED"
    await dispose_engine()


async def test_disabled_account_routers_empty() -> None:
    async with db_session() as session:
        await seed_rbac(session)
    admin_id = await _seed_user(username="root", is_super_admin=True, status="disabled")
    async with _client(str(admin_id)) as c:
        res = await c.get("/api/v1/menus/routers")
    assert res.status_code == 200
    assert res.json() == []  # 停用账号不下发菜单（spec §2.3 / Codex F1）
    await dispose_engine()
