"""Task 6 登录 API 集成测试（需本地 DB：make compose-up + make migrate）。

覆盖 spec 验收（成功拿 token / 错密码 401 / 错租户 401）+ Codex PK 收紧的两条安全行为：
suspended 用户拒登、is_platform 必须绑定 PLATFORM 哨兵租户（脏 is_platform_admin 不签平台 token）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from admin_platform.core.config import get_settings
from admin_platform.core.security import decode_token, hash_password
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import system_session
from admin_platform.domains.tenant.models import Tenant
from admin_platform.domains.user.models import User
from admin_platform.main import create_app

pytestmark = pytest.mark.integration

_SECRET = "integration-login-secret-" + "x" * 32
_PASSWORD = "correct-horse-battery-staple"


async def _wipe() -> None:
    """清空 users + tenants（FK 顺序：先 users 后 tenants）。system bypass 过滤。"""
    async with system_session() as session:
        await session.execute(delete(User))
        await session.execute(delete(Tenant))


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()


@pytest_asyncio.fixture
async def login_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("APP_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_AUTH_JWT_SECRET", _SECRET)
    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await dispose_engine()
    get_settings.cache_clear()


async def _seed(  # noqa: PLR0913
    tenant_code: str,
    username: str,
    *,
    password: str = _PASSWORD,
    tenant_status: str = "active",
    user_status: str = "active",
    is_platform_admin: bool = False,
) -> tuple[int, int]:
    """system_session 种一个租户 + 用户（显式带 tenant_id）。返回 (tenant_id, user_id)。"""
    async with system_session() as session:
        tenant = Tenant(code=tenant_code, name=tenant_code.title(), status=tenant_status)
        session.add(tenant)
        await session.flush()
        user = User(
            tenant_id=tenant.id,
            username=username,
            password_hash=hash_password(password),
            status=user_status,
            is_platform_admin=is_platform_admin,
        )
        session.add(user)
        await session.flush()
        return tenant.id, user.id


async def _login(client: AsyncClient, tenant_code: str, username: str, password: str):
    return await client.post(
        "/api/v1/auth/login",
        json={"tenant_code": tenant_code, "username": username, "password": password},
    )


async def test_login_success_returns_token(login_client: AsyncClient) -> None:
    tenant_id, user_id = await _seed("ACME", "alice")
    resp = await _login(login_client, "ACME", "alice", _PASSWORD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    payload = decode_token(body["access_token"])
    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == tenant_id
    assert payload["is_platform"] is False


async def test_login_wrong_password_401(login_client: AsyncClient) -> None:
    await _seed("ACME", "alice")
    resp = await _login(login_client, "ACME", "alice", "wrong-password")
    assert resp.status_code == 401
    assert resp.json()["type"] == "auth.LOGIN_FAILED"


async def test_login_wrong_tenant_401(login_client: AsyncClient) -> None:
    await _seed("ACME", "alice")
    resp = await _login(login_client, "OTHER", "alice", _PASSWORD)
    assert resp.status_code == 401
    assert resp.json()["type"] == "auth.LOGIN_FAILED"


async def test_login_unknown_user_401(login_client: AsyncClient) -> None:
    await _seed("ACME", "alice")
    resp = await _login(login_client, "ACME", "nobody", _PASSWORD)
    assert resp.status_code == 401
    assert resp.json()["type"] == "auth.LOGIN_FAILED"


async def test_login_suspended_user_401(login_client: AsyncClient) -> None:
    # Codex PK d1：用户停用必须和密码错同桶拒登（正确密码也不放行）。
    await _seed("ACME", "bob", user_status="disabled")
    resp = await _login(login_client, "ACME", "bob", _PASSWORD)
    assert resp.status_code == 401
    assert resp.json()["type"] == "auth.LOGIN_FAILED"


async def test_login_suspended_tenant_401(login_client: AsyncClient) -> None:
    await _seed("FROZEN", "carol", tenant_status="suspended")
    resp = await _login(login_client, "FROZEN", "carol", _PASSWORD)
    assert resp.status_code == 401
    assert resp.json()["type"] == "auth.LOGIN_FAILED"


async def test_platform_admin_in_platform_tenant_gets_platform_token(
    login_client: AsyncClient,
) -> None:
    await _seed("PLATFORM", "root", is_platform_admin=True)
    resp = await _login(login_client, "PLATFORM", "root", _PASSWORD)
    assert resp.status_code == 200, resp.text
    assert decode_token(resp.json()["access_token"])["is_platform"] is True


async def test_dirty_platform_flag_outside_platform_tenant_not_elevated(
    login_client: AsyncClient,
) -> None:
    # Codex PK d2：非 PLATFORM 租户里一条脏 is_platform_admin=True 不得签出平台 token。
    await _seed("ACME", "imposter", is_platform_admin=True)
    resp = await _login(login_client, "ACME", "imposter", _PASSWORD)
    assert resp.status_code == 200, resp.text
    assert decode_token(resp.json()["access_token"])["is_platform"] is False
