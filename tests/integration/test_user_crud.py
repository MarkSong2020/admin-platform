"""user CRUD 集成测试（需本地 DB）—— 端到端验收（单租户）。

覆盖：登录拿 token 后 CRUD、列表、username 重复 409、get/delete 不存在 id 返 404、更新+删除。
actor「alice」建为**超管**：F2 给 user API 加了 require_permission(system:user:*) 守卫后，
普通用户无权限点会 403；超管短路放行。另含非超管 → 403 的守卫回归（Codex 深审 F2）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from admin_platform.core.config import get_settings
from admin_platform.core.security import hash_password
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.user.models import User
from admin_platform.main import create_app

pytestmark = pytest.mark.integration

_SECRET = "integration-user-crud-secret-" + "x" * 32
_PASSWORD = "correct-horse-battery-staple"


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(delete(User))


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
    assert resp.json()["type"] == "admin_platform.USERNAME_DUPLICATE"


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
