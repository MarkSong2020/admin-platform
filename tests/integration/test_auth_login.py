"""登录 API 集成测试（需本地 DB：make compose-up + make migrate）。

覆盖验收（成功拿 token / 错密码 401 / 未知用户 401 / 停用用户 401）。
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
from admin_platform.db.session import db_session
from admin_platform.domains.user.models import User
from admin_platform.main import create_app

pytestmark = pytest.mark.integration

_SECRET = "integration-login-secret-" + "x" * 32
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
async def login_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("APP_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_AUTH_JWT_SECRET", _SECRET)
    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await dispose_engine()
    get_settings.cache_clear()


async def _seed(
    username: str,
    *,
    password: str = _PASSWORD,
    user_status: str = "active",
) -> int:
    """种一个用户。返回 user_id。"""
    async with db_session() as session:
        user = User(
            username=username,
            password_hash=hash_password(password),
            status=user_status,
        )
        session.add(user)
        await session.flush()
        return user.id


async def _login(client: AsyncClient, username: str, password: str):
    return await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


async def test_login_success_returns_token(login_client: AsyncClient) -> None:
    user_id = await _seed("alice")
    resp = await _login(login_client, "alice", _PASSWORD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    payload = decode_token(body["access_token"])
    assert payload["sub"] == str(user_id)
    assert payload["username"] == "alice"


async def test_login_wrong_password_401(login_client: AsyncClient) -> None:
    await _seed("alice")
    resp = await _login(login_client, "alice", "wrong-password")
    assert resp.status_code == 401
    assert resp.json()["type"] == "auth.LOGIN_FAILED"


async def test_login_unknown_user_401(login_client: AsyncClient) -> None:
    await _seed("alice")
    resp = await _login(login_client, "nobody", _PASSWORD)
    assert resp.status_code == 401
    assert resp.json()["type"] == "auth.LOGIN_FAILED"


async def test_login_suspended_user_401(login_client: AsyncClient) -> None:
    # Codex PK：用户停用必须和密码错同桶拒登（正确密码也不放行）。
    await _seed("bob", user_status="disabled")
    resp = await _login(login_client, "bob", _PASSWORD)
    assert resp.status_code == 401
    assert resp.json()["type"] == "auth.LOGIN_FAILED"
