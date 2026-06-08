"""role 角色域 CRUD + O2 数据范围归一 集成测试（需本地 DB）—— 端到端验收。

覆盖（spec §5 / §11 O2 / §9 DoD）：
  * **CRUD 端到端**：超管 stub 越过权限守卫（``get_permission_provider`` + ``require_current_user``
    override 模拟登录），create / list / get / patch / delete + code 重复 409 + NOT_FOUND 404。
  * **权限矩阵 5 端点 403**：非超管、无权限 → list/query/add/edit/remove 全 403（默认 deny）。
  * **O2 归一（真 DB）**：user 绑多角色后 ``DbPermissionProvider.a_get_effective_data_scope``
    返回正确归一范围（部门并集 = 本部门及以下子孙 ∪ 自定义部门；任一 ALL → ALL；SELF → include_self）。
  * **sync→async 桥（真 HTTP 路径）**：把真实 ``DbPermissionProvider`` 接进
    ``get_permission_provider``，经 FastAPI 同步依赖（threadpool worker 线程）命中
    ``get_is_super_admin`` 的 DB 查询 —— 验证 ``anyio.from_thread.run`` 桥接在生产路径可用。

自引用 / 跨表 FK：清表用 ``TRUNCATE ... CASCADE``（一并清子表绑定）。
"""

from __future__ import annotations

import asyncio
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
from admin_platform.domains.dept.models import Dept
from admin_platform.domains.menu.models import Menu
from admin_platform.domains.menu.repository import MenuRepository
from admin_platform.domains.role.api import router as role_router
from admin_platform.domains.role.models import Role
from admin_platform.domains.role.provider import DbPermissionProvider
from admin_platform.domains.role.repository import RoleRepository
from admin_platform.domains.user.models import User

pytestmark = pytest.mark.integration


# ---- 权限 stub（CRUD / 矩阵用，不查 DB）------------------------------------


class _SuperAdminProvider(PermissionProvider):
    """超管 stub：短路放行所有 role 权限点（spec §2.3）。"""

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
    """非超管、无权限 stub：5 端点全默认 deny（403）。"""

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
    """建一个 role app 的 AsyncClient（override 登录 + provider）。"""
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(role_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(
        user_id=user_id, sub=user_id
    )
    app.dependency_overrides[get_permission_provider] = lambda: provider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE role_menus, menus, user_roles, role_depts, roles, users, depts"
                " CASCADE"
            )
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


async def _create(client: AsyncClient, *, code: str, name: str, data_scope: str = "self") -> int:
    res = await client.post(
        "/api/v1/roles", json={"name": name, "code": code, "data_scope": data_scope}
    )
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


# ---- CRUD 端到端 -----------------------------------------------------------


async def test_crud_end_to_end(client: AsyncClient) -> None:
    role_id = await _create(client, code="admin", name="管理员", data_scope="all")

    listing = (await client.get("/api/v1/roles")).json()
    assert {r["code"] for r in listing["items"]} == {"admin"}
    assert listing["total"] == 1

    got = await client.get(f"/api/v1/roles/{role_id}")
    assert got.status_code == 200
    assert got.json()["data_scope"] == "all"

    patched = await client.patch(
        f"/api/v1/roles/{role_id}", json={"name": "超级管理员", "data_scope": "self_dept_and_below"}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "超级管理员"
    assert patched.json()["data_scope"] == "self_dept_and_below"

    # code 重复 → 409 role.CODE_DUPLICATE
    dup = await client.post("/api/v1/roles", json={"name": "山寨", "code": "admin"})
    assert dup.status_code == 409
    assert dup.json()["type"] == "role.CODE_DUPLICATE"

    # 删除 → 204；再 get → 404 role.NOT_FOUND
    deleted = await client.delete(f"/api/v1/roles/{role_id}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/roles/{role_id}")
    assert missing.status_code == 404
    assert missing.json()["type"] == "role.NOT_FOUND"


async def test_get_missing_returns_404(client: AsyncClient) -> None:
    res = await client.get("/api/v1/roles/999999")
    assert res.status_code == 404
    assert res.json()["type"] == "role.NOT_FOUND"


# ---- 权限矩阵 5 端点 403（非超管、无权限）----------------------------------


async def test_permission_matrix_all_endpoints_403() -> None:
    async with _build_client(_NoPermProvider(), user_id="2") as c:
        assert (await c.get("/api/v1/roles")).status_code == 403
        assert (await c.get("/api/v1/roles/1")).status_code == 403
        assert (await c.post("/api/v1/roles", json={"name": "x", "code": "X"})).status_code == 403
        assert (await c.patch("/api/v1/roles/1", json={"name": "x"})).status_code == 403
        assert (await c.delete("/api/v1/roles/1")).status_code == 403
    await dispose_engine()


# ---- O2 归一（真 DB）：绑定后 get_effective_data_scope 正确归一 ------------


async def _seed_user_with_roles(
    *, dept_id: int | None, role_scopes: list[str], custom_depts: dict[int, list[int]] | None = None
) -> int:
    """建 user（指定 dept_id）+ 若干角色（各 data_scope），绑定后返回 user_id（已提交）。

    ``custom_depts`` 形如 ``{角色下标: [部门id...]}``，为对应 ``CUSTOM_DEPT`` 角色挂 role_depts。
    """
    async with db_session() as session:
        user = User(username=f"u-scope-{dept_id}-{len(role_scopes)}", password_hash="x")
        user.dept_id = dept_id
        session.add(user)
        repo = RoleRepository(session)
        role_ids: list[int] = []
        for idx, scope in enumerate(role_scopes):
            role = Role(name=f"r{idx}", code=f"scope-{dept_id}-{idx}", data_scope=scope)
            session.add(role)
            await session.flush()
            role_ids.append(role.id)
            if custom_depts and idx in custom_depts:
                await repo.set_role_depts(role.id, custom_depts[idx])
        await session.flush()
        await repo.set_user_roles(user.id, role_ids)
        return user.id


async def _make_dept(*, code: str, parent_id: int | None = None) -> int:
    async with db_session() as session:
        dept = Dept(name=code, code=code, parent_id=parent_id)
        session.add(dept)
        await session.flush()
        return dept.id


async def _effective_scope(user_id: int) -> DataScope:
    """走真实 ``DbPermissionProvider`` 的异步内核（开自有 session 读已提交数据）做 O2 归一。"""
    return await DbPermissionProvider().a_get_effective_data_scope(user_id)


async def test_effective_scope_union_of_below_and_custom(client: AsyncClient) -> None:
    # 部门树：R → X（X 是 R 的子）；另有独立部门 C。
    r = await _make_dept(code="R")
    x = await _make_dept(code="X", parent_id=r)
    c = await _make_dept(code="C")
    # user.dept_id=R，绑两角色：self_dept_and_below（→ {R,X}）+ custom_dept（role_depts={C}）。
    user_id = await _seed_user_with_roles(
        dept_id=r,
        role_scopes=["self_dept_and_below", "custom_dept"],
        custom_depts={1: [c]},
    )
    scope = await _effective_scope(user_id)
    assert scope.scope_type is ScopeType.CUSTOM_DEPT
    assert scope.visible_dept_ids == frozenset({r, x, c})
    assert scope.include_self is False


async def test_effective_scope_any_all_yields_all(client: AsyncClient) -> None:
    user_id = await _seed_user_with_roles(dept_id=None, role_scopes=["self", "all"])
    scope = await _effective_scope(user_id)
    assert scope.scope_type is ScopeType.ALL


async def test_effective_scope_self_sets_include_self(client: AsyncClient) -> None:
    user_id = await _seed_user_with_roles(dept_id=None, role_scopes=["self"])
    scope = await _effective_scope(user_id)
    assert scope.include_self is True
    assert scope.visible_dept_ids == frozenset()


# ---- sync→async 桥（真 HTTP 路径，真实 DbPermissionProvider）----------------


async def _seed_user(*, username: str, is_super_admin: bool, status: str = "active") -> int:
    async with db_session() as session:
        user = User(
            username=username,
            password_hash="x",
            is_super_admin=is_super_admin,
            status=status,
        )
        session.add(user)
        await session.flush()
        return user.id


def _build_real_provider_client(user_id: int) -> AsyncClient:
    """role app + 真实 DbPermissionProvider（经同步桥查 DB），override 登录为 user_id。"""
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(role_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(
        user_id=str(user_id), sub=str(user_id)
    )
    app.dependency_overrides[get_permission_provider] = DbPermissionProvider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_real_provider_superadmin_bridge_allows() -> None:
    # 真实 provider：get_is_super_admin 经 anyio.from_thread.run 桥查 DB → True → 短路放行 200。
    admin_id = await _seed_user(username="root", is_super_admin=True)
    async with _build_real_provider_client(admin_id) as c:
        res = await c.get("/api/v1/roles")
    assert res.status_code == 200, res.text
    await dispose_engine()


async def test_real_provider_non_superadmin_bridge_denies() -> None:
    # 真实 provider：非超管经桥查 DB → False；无任何角色 → 派生空权限集 → 默认 deny 403。
    uid = await _seed_user(username="plain", is_super_admin=False)
    async with _build_real_provider_client(uid) as c:
        res = await c.get("/api/v1/roles")
    assert res.status_code == 403
    assert res.json()["type"] == "auth.FORBIDDEN_BY_ROLE"
    await dispose_engine()


async def test_real_provider_perms_derived_from_role_menus() -> None:
    # ME1 接线核心：非超管经 角色→role_menus→menu.perms 派生出 system:role:list →
    # 经真实 get_user_permissions（桥查 DB）放行受守卫的 GET /api/v1/roles → 200。
    async with db_session() as session:
        user = User(username="rbac-user", password_hash="x")
        session.add(user)
        menu = Menu(name="角色查询", menu_type="C", perms="system:role:list")
        session.add(menu)
        role = Role(name="r", code="rbac-role", data_scope="self", status="active")
        session.add(role)
        await session.flush()
        await MenuRepository(session).set_role_menus(role.id, [menu.id])
        await RoleRepository(session).set_user_roles(user.id, [role.id])
        uid = user.id
    async with _build_real_provider_client(uid) as c:
        res = await c.get("/api/v1/roles")
    assert res.status_code == 200, res.text
    await dispose_engine()


async def test_real_provider_disabled_superadmin_denied() -> None:
    # Codex 深审 F4 / spec §2.3：停用账号即使 is_super_admin=True 也不享超管短路 → 403。
    # 走真实 DbPermissionProvider.get_is_active 桥（请求期查 DB status）→ ACCOUNT_DISABLED。
    uid = await _seed_user(username="root-disabled", is_super_admin=True, status="disabled")
    async with _build_real_provider_client(uid) as c:
        res = await c.get("/api/v1/roles")
    assert res.status_code == 403
    assert res.json()["type"] == "auth.ACCOUNT_DISABLED"
    await dispose_engine()


# ---- Codex 深审 F1：停用角色不参与授权（O2 归一前已被排除）-------------------


async def test_effective_scope_excludes_disabled_role(client: AsyncClient) -> None:
    # 一个 disabled 且 data_scope=all 的角色不得触发整体 ALL（停用即撤权，不留后门）。
    async with db_session() as session:
        user = User(username="u-disabled-role", password_hash="x")
        session.add(user)
        disabled_all = Role(name="da", code="da", data_scope="all", status="disabled")
        session.add(disabled_all)
        await session.flush()
        uid, rid = user.id, disabled_all.id
        await RoleRepository(session).set_user_roles(uid, [rid])
    scope = await _effective_scope(uid)
    assert scope.scope_type is not ScopeType.ALL
    assert scope.visible_dept_ids == frozenset()
    assert scope.include_self is False


# ---- Codex 深审 F3：绑定全量替换并发 last-writer-wins（advisory lock 串行化）---


async def test_set_user_roles_concurrent_last_writer_wins(client: AsyncClient) -> None:
    # 两请求并发把同一 user 的角色分别替换为 [r1] / [r2]：advisory lock 串行化后最终恰好
    # 一个角色（last-writer-wins），而非并集 [r1, r2]，也不撞 uq_user_roles。
    async with db_session() as session:
        user = User(username="u-concurrent", password_hash="x")
        session.add(user)
        r1 = Role(name="r1", code="cc1", data_scope="self")
        r2 = Role(name="r2", code="cc2", data_scope="self")
        session.add_all([r1, r2])
        await session.flush()
        uid, rid1, rid2 = user.id, r1.id, r2.id

    async def _replace(role_id: int) -> None:
        async with db_session() as session:
            await RoleRepository(session).set_user_roles(uid, [role_id])

    await asyncio.gather(_replace(rid1), _replace(rid2))

    async with db_session() as session:
        roles = await RoleRepository(session).list_roles_for_user(uid)
    assert len(roles) == 1
    assert roles[0].id in {rid1, rid2}
