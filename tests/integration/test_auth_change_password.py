"""自助改密端点端到端（POST /api/v1/auth/change-password，需本地 DB）。

验原密 → 改密成功撤该用户**全部**旧 refresh + 给当前会话重签新 token（方案 A）；原密码错 400；
新密码弱（=旧 / <12）422；未鉴权 401。验证撤销会话副作用在真实 HTTP 路径（db_session 事务）持久化。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from admin_platform.core.config import get_settings
from admin_platform.core.security import hash_password
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.auth.models import RefreshToken
from admin_platform.domains.user.models import User
from admin_platform.main import create_app

pytestmark = pytest.mark.integration

_SECRET = "integration-changepw-secret-" + "x" * 32
_PEPPER = "integration-changepw-pepper-" + "p" * 32
_PW = "correct-horse-battery-staple"
_NEW_PW = "brand-new-secure-pw-2026"


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


async def _change_password(client: AsyncClient, access_token: str, old_pw: str, new_pw: str):
    return await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": old_pw, "new_password": new_pw},
        headers={"Authorization": f"Bearer {access_token}"},
    )


async def _active_refresh_tokens() -> list[RefreshToken]:
    async with db_session() as session:
        return list(
            (
                await session.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
            ).all()
        )


async def test_change_password_success_rotates_and_revokes_old(client: AsyncClient) -> None:
    await _seed()
    body = await _login(client)
    old_refresh = body["refresh_token"]
    res = await _change_password(client, body["access_token"], _PW, _NEW_PW)
    assert res.status_code == 200, res.text
    out = res.json()
    # 当前会话拿到重签的新 token
    assert out["access_token"]
    assert out["refresh_token"].startswith("rt_")
    assert out["refresh_token"] != old_refresh
    # 旧 refresh 失效（撤销）
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    ).status_code == 401
    # 新 refresh 可用
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": out["refresh_token"]})
    ).status_code == 200
    # 新密码能登录、旧密码不能
    assert (
        await client.post("/api/v1/auth/login", json={"username": "alice", "password": _NEW_PW})
    ).status_code == 200
    assert (
        await client.post("/api/v1/auth/login", json={"username": "alice", "password": _PW})
    ).status_code == 401


async def test_change_password_revokes_all_other_sessions(client: AsyncClient) -> None:
    """登录两次 = 2 family；改密后旧的全撤销，仅当前重签的新 token 活跃（DB 验证副作用持久化）。"""
    await _seed()
    first = await _login(client)
    second = await _login(client)
    res = await _change_password(client, second["access_token"], _PW, _NEW_PW)
    assert res.status_code == 200, res.text
    # 两个旧 refresh 全失效
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    ).status_code == 401
    # DB 里只剩当前会话重签的 1 个 active token（撤销副作用已提交）
    assert len(await _active_refresh_tokens()) == 1


async def test_change_password_wrong_old_returns_400(client: AsyncClient) -> None:
    await _seed()
    body = await _login(client)
    res = await _change_password(client, body["access_token"], "wrong-old-pw-xxxx", _NEW_PW)
    assert res.status_code == 400
    assert res.json()["type"] == "auth.PASSWORD_INCORRECT"
    # 密码未变（旧密码仍能登录），旧会话未被撤销
    assert (
        await client.post("/api/v1/auth/login", json={"username": "alice", "password": _PW})
    ).status_code == 200
    assert len(await _active_refresh_tokens()) >= 1


async def test_change_password_new_equals_old_rejected_422(client: AsyncClient) -> None:
    await _seed()
    body = await _login(client)
    res = await _change_password(client, body["access_token"], _PW, _PW)
    assert res.status_code == 422
    assert res.json()["type"] == "auth.PASSWORD_TOO_WEAK"


async def test_change_password_too_short_rejected_422(client: AsyncClient) -> None:
    await _seed()
    body = await _login(client)
    # 新密码 <12 → schema min_length 拦（FastAPI 422 validation）
    res = await _change_password(client, body["access_token"], _PW, "short")
    assert res.status_code == 422


async def test_change_password_requires_auth_401(client: AsyncClient) -> None:
    await _seed()
    # 不带 Authorization → require_current_user 401（不需先登录）
    res = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": _PW, "new_password": _NEW_PW},
    )
    assert res.status_code == 401
