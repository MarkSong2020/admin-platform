"""menu 菜单域 CRUD + 菜单树 / role_menus 派生 集成测试（需本地 DB）—— 端到端验收。

覆盖（spec §6 getRouters 数据源 / §12.4 / §13.2 权限派生）：
  * **CRUD 端到端**：超管 stub 越过守卫，create / list / get / patch / delete + NOT_FOUND 404 +
    PARENT_NOT_FOUND 404 + 移动成环 409 + 有子禁删 409。
  * **权限矩阵 5 端点 403**：非超管、无权限 → 全 403（默认 deny）。
  * **DbMenuProvider 树（真 DB）**：超管见全部 active 菜单；非超管经 role_menus 见授予子集；
    停用菜单不下发；停用角色不贡献（Codex 深审 F1 同款）。
  * **权限派生（真 DB）**：``list_perms_for_user`` / ``list_menu_ids_for_user`` 经 role_menus 正确，
    供人值守把 ``get_user_permissions`` 改真实派生。

自引用 / 跨表 FK：清表用 ``TRUNCATE ... CASCADE``（一并清子表绑定）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.menu.api import router as menu_router
from admin_platform.domains.menu.models import Menu
from admin_platform.domains.menu.provider import DbMenuProvider
from admin_platform.domains.menu.repository import MenuRepository
from admin_platform.domains.role.models import Role
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.user.models import User

pytestmark = pytest.mark.integration


class _SuperAdminProvider(PermissionProvider):
    def get_is_super_admin(self, user_id: int) -> bool:
        return True

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.ALL, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


class _NoPermProvider(PermissionProvider):
    def get_is_super_admin(self, user_id: int) -> bool:
        return False

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.SELF, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


def _build_client(provider: PermissionProvider, *, user_id: str = "1") -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(menu_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(
        user_id=user_id, sub=user_id
    )
    app.dependency_overrides[get_permission_provider] = lambda: provider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(
            text("TRUNCATE TABLE role_menus, menus, user_roles, role_depts, roles, users CASCADE")
        )


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with _build_client(_SuperAdminProvider()) as c:
        yield c
    await dispose_engine()


async def _create(
    client: AsyncClient, *, name: str, menu_type: str = "C", parent_id: int | None = None
) -> int:
    payload: dict[str, object] = {"name": name, "menu_type": menu_type}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    res = await client.post("/api/v1/menus", json=payload)
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


# ---- CRUD 端到端 -----------------------------------------------------------


async def test_crud_end_to_end(client: AsyncClient) -> None:
    cat = await _create(client, name="系统管理", menu_type="M")
    leaf = await _create(client, name="用户管理", menu_type="C", parent_id=cat)

    listing = (await client.get("/api/v1/menus")).json()
    assert {m["name"] for m in listing["items"]} == {"系统管理", "用户管理"}
    assert listing["total"] == 2

    got = await client.get(f"/api/v1/menus/{leaf}")
    assert got.status_code == 200
    assert got.json()["parent_id"] == cat

    patched = await client.patch(f"/api/v1/menus/{leaf}", json={"name": "用户列表"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "用户列表"

    # 有子菜单 → 删父被拒（409 menu.HAS_CHILDREN）
    blocked = await client.delete(f"/api/v1/menus/{cat}")
    assert blocked.status_code == 409
    assert blocked.json()["type"] == "menu.HAS_CHILDREN"

    # 删叶 → 204；再 get → 404 menu.NOT_FOUND
    deleted = await client.delete(f"/api/v1/menus/{leaf}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/menus/{leaf}")
    assert missing.status_code == 404
    assert missing.json()["type"] == "menu.NOT_FOUND"


async def test_get_missing_returns_404(client: AsyncClient) -> None:
    res = await client.get("/api/v1/menus/999999")
    assert res.status_code == 404
    assert res.json()["type"] == "menu.NOT_FOUND"


async def test_create_nonexistent_parent_returns_404(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/menus", json={"name": "x", "menu_type": "C", "parent_id": 999999}
    )
    assert res.status_code == 404
    assert res.json()["type"] == "menu.PARENT_NOT_FOUND"


async def test_move_into_descendant_rejected(client: AsyncClient) -> None:
    a = await _create(client, name="A", menu_type="M")
    b = await _create(client, name="B", menu_type="M", parent_id=a)
    c = await _create(client, name="C", menu_type="C", parent_id=b)
    # 把 A 移到其子孙 C 之下 → 成环，拒绝。
    res = await client.patch(f"/api/v1/menus/{a}", json={"parent_id": c})
    assert res.status_code == 409
    assert res.json()["type"] == "menu.CYCLE"


# ---- 权限矩阵 5 端点 403（非超管、无权限）----------------------------------


async def test_permission_matrix_all_endpoints_403() -> None:
    async with _build_client(_NoPermProvider(), user_id="2") as c:
        assert (await c.get("/api/v1/menus")).status_code == 403
        assert (await c.get("/api/v1/menus/1")).status_code == 403
        assert (
            await c.post("/api/v1/menus", json={"name": "x", "menu_type": "C"})
        ).status_code == 403
        assert (await c.patch("/api/v1/menus/1", json={"name": "x"})).status_code == 403
        assert (await c.delete("/api/v1/menus/1")).status_code == 403


# ---- DbMenuProvider 树 + 权限派生（真 DB）----------------------------------


async def _seed_menu(
    *,
    name: str,
    menu_type: str = "C",
    parent_id: int | None = None,
    perms: str | None = None,
    status: str = "active",
) -> int:
    async with db_session() as session:
        menu = Menu(
            name=name,
            menu_type=menu_type,
            parent_id=parent_id,
            perms=perms,
            status=status,
        )
        session.add(menu)
        await session.flush()
        return menu.id


async def _seed_user_role_menus(
    *,
    role_status: str = "active",
    menu_ids: list[int],
) -> int:
    """建 user + 一个角色（绑这些菜单）+ user_roles 绑定，返回 user_id（已提交）。"""
    async with db_session() as session:
        user = User(username=f"u-menu-{role_status}-{len(menu_ids)}", password_hash="x")
        session.add(user)
        role = Role(
            name="r", code=f"menu-role-{role_status}", data_scope="self", status=role_status
        )
        session.add(role)
        await session.flush()
        repo = MenuRepository(session)
        await repo.set_role_menus(role.id, menu_ids)
        await RoleRepository(session).set_user_roles(user.id, [role.id])
        return user.id


async def test_superadmin_tree_sees_all_active_excludes_disabled(client: AsyncClient) -> None:
    cat = await _seed_menu(name="系统", menu_type="M")
    await _seed_menu(name="用户", menu_type="C", parent_id=cat, perms="system:user:list")
    await _seed_menu(name="停用页", menu_type="C", parent_id=cat, status="disabled")
    admin_id = await _seed_user_role_menus(menu_ids=[])  # 超管不靠 role_menus
    # 把该 user 设为超管
    async with db_session() as session:
        user = await session.get(User, admin_id)
        assert user is not None
        user.is_super_admin = True
    tree = await DbMenuProvider().a_get_user_menu_tree(admin_id)
    # 顶层只有「系统」目录，其下只有 active 的「用户」（停用页被排除）。
    assert [n.name for n in tree] == ["系统"]
    assert [c.name for c in tree[0].children] == ["用户"]


async def test_non_super_tree_limited_by_role_menus() -> None:
    cat = await _seed_menu(name="系统", menu_type="M")
    granted = await _seed_menu(name="用户", menu_type="C", parent_id=cat, perms="system:user:list")
    await _seed_menu(name="未授权", menu_type="C", parent_id=cat, perms="system:role:list")
    # 角色只绑 cat + granted（不绑「未授权」）。
    uid = await _seed_user_role_menus(menu_ids=[cat, granted])
    tree = await DbMenuProvider().a_get_user_menu_tree(uid)
    assert [n.name for n in tree] == ["系统"]
    assert [c.name for c in tree[0].children] == ["用户"]


async def test_perms_derivation_excludes_disabled_role() -> None:
    m1 = await _seed_menu(name="用户列表", perms="system:user:list")
    m2 = await _seed_menu(name="用户新增", perms="system:user:add")
    # 生效角色 → 两个 perms 都派生。
    uid_active = await _seed_user_role_menus(role_status="active", menu_ids=[m1, m2])
    async with db_session() as session:
        perms = await MenuRepository(session).list_perms_for_user(uid_active)
    assert perms == frozenset({"system:user:list", "system:user:add"})
    # 停用角色 → 不贡献任何 perms（Codex F1 同款）。
    uid_disabled = await _seed_user_role_menus(role_status="disabled", menu_ids=[m1, m2])
    async with db_session() as session:
        perms2 = await MenuRepository(session).list_perms_for_user(uid_disabled)
    assert perms2 == frozenset()
