"""Task 10 ★端到端租户隔离验收门（spec §5）。需本地 DB。

三租户 A/alice、B/bob、PLATFORM/root 各自登录后，断言：
  * A 列出 /api/v1/users 只见 alice、B 只见 bob（租户隔离）；
  * 平台超管 root 跨租户可见 {alice, bob, root}；
  * 跨租户按 id GET → 404（隔离即 not-found，不泄存在性）。

fail-closed（无 tenant 上下文的业务查询抛错）由 Task 3 单测 ``test_tenant_filter`` 覆盖——
不在生产代码加 _debug/leak 端点（工程原则④：不为测试在生产类加专用入口）。
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

_SECRET = "integration-isolation-secret-" + "x" * 32
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


async def _seed(tenant_code: str, username: str, *, is_platform_admin: bool = False) -> int:
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
        return user.id


async def _login(client: AsyncClient, tenant_code: str, username: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"tenant_code": tenant_code, "username": username, "password": _PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _usernames(client: AsyncClient, token: str) -> set[str]:
    resp = await client.get("/api/v1/users", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return {item["username"] for item in resp.json()["items"]}


async def test_tenants_isolated_and_platform_admin_sees_all(client: AsyncClient) -> None:
    await _seed("A", "alice")
    await _seed("B", "bob")
    await _seed("PLATFORM", "root", is_platform_admin=True)

    token_a = await _login(client, "A", "alice")
    token_b = await _login(client, "B", "bob")
    token_p = await _login(client, "PLATFORM", "root")

    assert await _usernames(client, token_a) == {"alice"}
    assert await _usernames(client, token_b) == {"bob"}
    assert {"alice", "bob", "root"} <= await _usernames(client, token_p)


async def test_cross_tenant_get_by_id_returns_404(client: AsyncClient) -> None:
    await _seed("A", "alice")
    bob_id = await _seed("B", "bob")
    token_a = await _login(client, "A", "alice")
    resp = await client.get(f"/api/v1/users/{bob_id}", headers=_auth(token_a))
    assert resp.status_code == 404
