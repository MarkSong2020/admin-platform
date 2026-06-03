"""Task 8 user CRUD 集成测试（需本地 DB）—— 受租户隔离的端到端验收。

覆盖：登录拿 token 后 CRUD、租户隔离（A 只见自己）、平台超管跨租户可见、同租户 username 409、
以及 Codex 隔离 PK 的关键安全行为：**A 不能按 id 删/取 B 的 user（隔离即 404，非越权）**。
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
from admin_platform.db.session import system_session
from admin_platform.domains.tenant.models import Tenant
from admin_platform.domains.user.models import User
from admin_platform.main import create_app

pytestmark = pytest.mark.integration

_SECRET = "integration-user-crud-secret-" + "x" * 32
_PASSWORD = "correct-horse-battery-staple"


async def _wipe() -> None:
    async with system_session() as session:
        await session.execute(delete(User))
        await session.execute(delete(Tenant))


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


async def _seed(
    tenant_code: str, username: str, *, is_platform_admin: bool = False
) -> tuple[int, int]:
    async with system_session() as session:
        tenant = Tenant(code=tenant_code, name=tenant_code.title(), status="active")
        session.add(tenant)
        await session.flush()
        user = User(
            tenant_id=tenant.id,
            username=username,
            password_hash=hash_password(_PASSWORD),
            status="active",
            is_platform_admin=is_platform_admin,
        )
        session.add(user)
        await session.flush()
        return tenant.id, user.id


async def _login(client: AsyncClient, tenant_code: str, username: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"tenant_code": tenant_code, "username": username, "password": _PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_create_and_list_is_tenant_scoped(client: AsyncClient) -> None:
    await _seed("A", "alice")
    await _seed("B", "bob")
    ta = await _login(client, "A", "alice")
    tb = await _login(client, "B", "bob")

    created = await client.post(
        "/api/v1/users", headers=_auth(ta), json={"username": "u1", "password": "pw"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["tenant_id"] > 0
    assert "password_hash" not in created.json()  # 绝不回显口令哈希

    list_a = (await client.get("/api/v1/users", headers=_auth(ta))).json()
    assert {u["username"] for u in list_a["items"]} == {"alice", "u1"}
    assert list_a["total"] == 2  # count 也被租户过滤

    list_b = (await client.get("/api/v1/users", headers=_auth(tb))).json()
    assert {u["username"] for u in list_b["items"]} == {"bob"}


async def test_cross_tenant_get_returns_404(client: AsyncClient) -> None:
    await _seed("A", "alice")
    _, bob_id = await _seed("B", "bob")
    ta = await _login(client, "A", "alice")
    resp = await client.get(f"/api/v1/users/{bob_id}", headers=_auth(ta))
    assert resp.status_code == 404


async def test_cross_tenant_delete_returns_404_and_keeps_row(client: AsyncClient) -> None:
    # Codex 隔离 PK 关键用例：A 不能按 id 删 B 的 user —— 隔离过滤让它查不到 → 404，不越权删除。
    await _seed("A", "alice")
    _, bob_id = await _seed("B", "bob")
    ta = await _login(client, "A", "alice")
    resp = await client.delete(f"/api/v1/users/{bob_id}", headers=_auth(ta))
    assert resp.status_code == 404
    # bob 仍能登录 = 没被跨租户删掉
    assert await _login(client, "B", "bob")


async def test_same_tenant_username_duplicate_409(client: AsyncClient) -> None:
    await _seed("A", "alice")
    ta = await _login(client, "A", "alice")
    resp = await client.post(
        "/api/v1/users", headers=_auth(ta), json={"username": "alice", "password": "pw"}
    )
    assert resp.status_code == 409
    assert resp.json()["type"] == "admin_platform.USERNAME_DUPLICATE"


async def test_platform_admin_lists_cross_tenant(client: AsyncClient) -> None:
    await _seed("A", "alice")
    await _seed("B", "bob")
    await _seed("PLATFORM", "root", is_platform_admin=True)
    tp = await _login(client, "PLATFORM", "root")
    listing = (await client.get("/api/v1/users", headers=_auth(tp))).json()
    assert {"alice", "bob", "root"} <= {u["username"] for u in listing["items"]}


async def test_update_and_delete_own_user(client: AsyncClient) -> None:
    await _seed("A", "alice")
    ta = await _login(client, "A", "alice")
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
