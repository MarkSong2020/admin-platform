"""login / refresh / logout 端点端到端（P1.4 slice 2，需本地 DB）。

login 发 access+refresh → refresh 轮换换新对 → 旧 refresh reuse 401 → logout 后失效。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from admin_platform.core.config import get_settings
from admin_platform.core.security import hash_password
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.user.models import User
from admin_platform.main import create_app

pytestmark = pytest.mark.integration

_SECRET = "integration-token-ep-secret-" + "x" * 32
_PEPPER = "integration-token-ep-pepper-" + "p" * 32
_PW = "correct-horse-battery-staple"


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE auth_refresh_tokens, users CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_db() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("APP_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_AUTH_JWT_SECRET", _SECRET)
    monkeypatch.setenv("APP_AUTH_REFRESH_TOKEN_PEPPER", _PEPPER)
    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_engine()
    get_settings.cache_clear()


async def _seed(username: str = "alice") -> None:
    async with db_session() as session:
        session.add(User(username=username, password_hash=hash_password(_PW), status="active"))


async def _login(client: AsyncClient) -> dict:
    res = await client.post("/api/v1/auth/login", json={"username": "alice", "password": _PW})
    assert res.status_code == 200, res.text
    return res.json()


async def test_login_returns_refresh_token(client: AsyncClient) -> None:
    await _seed()
    body = await _login(client)
    assert body["access_token"]
    assert body["refresh_token"].startswith("rt_")
    assert body["refresh_expires_in"] > 0


async def test_refresh_rotates(client: AsyncClient) -> None:
    await _seed()
    first = await _login(client)
    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert res.status_code == 200, res.text
    rotated = res.json()
    assert rotated["access_token"]
    assert rotated["refresh_token"].startswith("rt_")
    assert rotated["refresh_token"] != first["refresh_token"]  # 轮换换新


async def test_reused_old_refresh_rejected(client: AsyncClient) -> None:
    await _seed()
    first = await _login(client)
    await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    # 再用旧 refresh → reuse 检测 401
    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert res.status_code == 401
    assert res.json()["type"] == "auth.REFRESH_TOKEN_REUSED"


async def test_logout_invalidates_refresh(client: AsyncClient) -> None:
    await _seed()
    body = await _login(client)
    out = await client.post("/api/v1/auth/logout", json={"refresh_token": body["refresh_token"]})
    assert out.status_code == 204
    # logout 后该 family 失效，refresh 401
    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert res.status_code == 401


async def test_invalid_refresh_rejected(client: AsyncClient) -> None:
    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": "rt_x.y"})
    assert res.status_code == 401
    assert res.json()["type"] == "auth.REFRESH_TOKEN_INVALID"
