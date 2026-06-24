"""user CRUD 集成测试（需本地 DB）—— 端到端验收（单租户）。

覆盖：登录拿 token 后 CRUD、列表、username 重复 409、get/delete 不存在 id 返 404、更新+删除。
actor「alice」建为**超管**：F2 给 user API 加了 require_permission(system:user:*) 守卫后，
普通用户无权限点会 403；超管短路放行。另含非超管 → 403 的守卫回归（Codex 深审 F2）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.config import get_settings
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.core.security import hash_password
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.dept.models import Dept
from admin_platform.domains.user.api import router as user_router
from admin_platform.domains.user.models import User
from admin_platform.main import create_app
from tests.integration.db_cleanup import truncate_tables

pytestmark = pytest.mark.integration

_SECRET = "integration-user-crud-secret-" + "x" * 32
_PASSWORD = "correct-horse-battery-staple"


async def _wipe() -> None:
    await truncate_tables("users", "depts")


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("APP_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_AUTH_JWT_SECRET", _SECRET)
    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_engine()
    get_settings.cache_clear()


async def _seed(username: str, *, is_super_admin: bool = False) -> int:
    async with db_session() as session:
        user = User(
            username=username,
            password_hash=hash_password(_PASSWORD),
            status="active",
            is_super_admin=is_super_admin,
        )
        session.add(user)
        await session.flush()
        return user.id


async def _login(client: AsyncClient, username: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": _PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_create_and_list(client: AsyncClient) -> None:
    await _seed("alice", is_super_admin=True)
    ta = await _login(client, "alice")

    created = await client.post(
        "/api/v1/users", headers=_auth(ta), json={"username": "u1", "password": "pw"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["id"] > 0
    assert "password_hash" not in created.json()  # 绝不回显口令哈希

    listing = (await client.get("/api/v1/users", headers=_auth(ta))).json()
    assert {u["username"] for u in listing["items"]} == {"alice", "u1"}
    assert listing["total"] == 2


async def test_get_nonexistent_returns_404(client: AsyncClient) -> None:
    await _seed("alice", is_super_admin=True)
    ta = await _login(client, "alice")
    resp = await client.get("/api/v1/users/999999", headers=_auth(ta))
    assert resp.status_code == 404


async def test_username_duplicate_409(client: AsyncClient) -> None:
    await _seed("alice", is_super_admin=True)
    ta = await _login(client, "alice")
    resp = await client.post(
        "/api/v1/users", headers=_auth(ta), json={"username": "alice", "password": "pw"}
    )
    assert resp.status_code == 409
    assert resp.json()["type"] == "user.USERNAME_DUPLICATE"


async def test_update_and_delete_user(client: AsyncClient) -> None:
    await _seed("alice", is_super_admin=True)
    ta = await _login(client, "alice")
    created = await client.post(
        "/api/v1/users", headers=_auth(ta), json={"username": "u1", "password": "pw"}
    )
    u1_id = created.json()["id"]

    patched = await client.patch(
        f"/api/v1/users/{u1_id}", headers=_auth(ta), json={"nickname": "User One"}
    )
    assert patched.status_code == 200
    assert patched.json()["nickname"] == "User One"

    deleted = await client.delete(f"/api/v1/users/{u1_id}", headers=_auth(ta))
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/users/{u1_id}", headers=_auth(ta))).status_code == 404


async def test_non_super_user_forbidden(client: AsyncClient) -> None:
    # F2 守卫回归：普通用户（非超管、R1 无权限点）调 user API → 403（默认 deny）。
    await _seed("bob")  # 非超管
    tb = await _login(client, "bob")
    assert (await client.get("/api/v1/users", headers=_auth(tb))).status_code == 403
    created = await client.post(
        "/api/v1/users", headers=_auth(tb), json={"username": "x", "password": "pw"}
    )
    assert created.status_code == 403


async def test_update_invalid_status_rejected_422(client: AsyncClient) -> None:
    # Codex 系统级 PK #3：user.status 现为 Literal active/disabled，非法值 → 422（与其余域同源）。
    await _seed("alice", is_super_admin=True)
    ta = await _login(client, "alice")
    created = await client.post(
        "/api/v1/users", headers=_auth(ta), json={"username": "u1", "password": "pw"}
    )
    u1 = created.json()["id"]
    res = await client.patch(f"/api/v1/users/{u1}", headers=_auth(ta), json={"status": "bogus"})
    assert res.status_code == 422


# ---- 数据权限（data_scope）：非超管按部门可见用户（Codex 系统级 PK）------------


class _ScopedProvider(PermissionProvider):
    """非超管 stub：有 system:user:* 权限点，CUSTOM_DEPT data_scope 限可见部门。"""

    def __init__(self, *, visible: frozenset[int]) -> None:
        self._visible = visible

    def get_is_super_admin(self, user_id: int) -> bool:
        return False

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset(
            {
                "system:user:list",
                "system:user:query",
                "system:user:add",
                "system:user:edit",
                "system:user:remove",
            }
        )

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.CUSTOM_DEPT, user_id=user_id, visible_dept_ids=self._visible)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


def _scoped_client(provider: PermissionProvider, *, user_id: str = "9") -> AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(user_router)
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(
        user_id=user_id, sub=user_id
    )
    app.dependency_overrides[get_permission_provider] = lambda: provider
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_dept(code: str) -> int:
    async with db_session() as session:
        dept = Dept(name=code, code=code)
        session.add(dept)
        await session.flush()
        return dept.id


async def _make_user(username: str, dept_id: int | None) -> int:
    async with db_session() as session:
        user = User(username=username, password_hash="x", dept_id=dept_id)
        session.add(user)
        await session.flush()
        return user.id


async def test_user_data_scope_read_and_write() -> None:
    dept_a = await _make_dept("DA")
    dept_b = await _make_dept("DB")
    await _make_user("u-a", dept_a)
    u_b = await _make_user("u-b", dept_b)
    async with _scoped_client(_ScopedProvider(visible=frozenset({dept_a}))) as c:
        # list：只见可见部门 A 的用户
        listing = (await c.get("/api/v1/users")).json()
        assert {u["username"] for u in listing["items"]} == {"u-a"}
        # get：可见部门用户的 get 200，不可见 404（不泄露存在性）
        ua_id = listing["items"][0]["id"]
        assert (await c.get(f"/api/v1/users/{ua_id}")).status_code == 200
        assert (await c.get(f"/api/v1/users/{u_b}")).status_code == 404
        # create：建到可见部门 A → 201；建到不可见部门 B → 403 auth.FORBIDDEN_BY_SCOPE
        ok = await c.post(
            "/api/v1/users", json={"username": "n1", "password": "pw", "dept_id": dept_a}
        )
        assert ok.status_code == 201, ok.text
        forbidden = await c.post(
            "/api/v1/users", json={"username": "n2", "password": "pw", "dept_id": dept_b}
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["type"] == "auth.FORBIDDEN_BY_SCOPE"
        # update / delete 不可见用户 u_b → 404
        assert (await c.patch(f"/api/v1/users/{u_b}", json={"nickname": "x"})).status_code == 404
        assert (await c.delete(f"/api/v1/users/{u_b}")).status_code == 404
    await dispose_engine()


async def test_user_list_filter_cannot_bypass_data_scope() -> None:
    """P1 关键安全回归：列表过滤是 AND 叠加在 data_scope 之上，绝不绕过数据权限。

    非超管仅可见部门 A：即使显式按 username 过滤命中部门 B 的用户、或按 dept_id=B 过滤，
    结果仍被 data_scope 收窄到部门 A（看不见 B），count 也一致（total 不含 B）。
    """
    dept_a = await _make_dept("FA")
    dept_b = await _make_dept("FB")
    await _make_user("alpha-a", dept_a)  # 部门 A：可见
    await _make_user("alpha-b", dept_b)  # 部门 B：不可见（同前缀，验证过滤不放大范围）
    async with _scoped_client(_ScopedProvider(visible=frozenset({dept_a}))) as c:
        # 关键字 "alpha" 在全库命中 2 条，但 data_scope 只放行 A → 仅 alpha-a。
        kw = (await c.get("/api/v1/users", params={"username": "alpha"})).json()
        assert {u["username"] for u in kw["items"]} == {"alpha-a"}
        assert kw["total"] == 1  # count 与过滤+scope 一致（不含 B）
        # 显式按不可见部门 B 过滤 → 空集（过滤 AND data_scope 后无交集），不泄露 B。
        scoped_out = (await c.get("/api/v1/users", params={"dept_id": dept_b})).json()
        assert scoped_out["items"] == []
        assert scoped_out["total"] == 0
        # 排序在 data_scope 范围内生效（仅 1 条，验证不报错且仍受限）。
        sorted_res = (
            await c.get("/api/v1/users", params={"order_by": "username", "order": "asc"})
        ).json()
        assert {u["username"] for u in sorted_res["items"]} == {"alpha-a"}
    await dispose_engine()
