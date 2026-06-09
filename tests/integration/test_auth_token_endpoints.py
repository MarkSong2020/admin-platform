"""login / refresh / logout 端点端到端（P1.4 slice 2，需本地 DB）。

login 发 access+refresh → refresh 轮换换新对 → 旧 refresh reuse 401 → logout 后失效。
"""

from __future__ import annotations

import logging
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


async def _active_refresh_tokens() -> list[RefreshToken]:
    async with db_session() as session:
        return list(
            (
                await session.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
            ).all()
        )


async def test_reuse_revokes_family_in_db(client: AsyncClient) -> None:
    """🔴-2 回归：reuse 检测的 family 撤销是安全副作用，必须在真实 HTTP 路径（db_session
    事务）提交。此前 AppError 穿出 session.begin() 触发 ROLLBACK → 401 返回了但 family 仍
    active（防盗用失效）。直接查 DB 证副作用已持久化；修复前本断言失败、修复后通过。
    """
    await _seed()
    first = await _login(client)
    rotated = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).json()
    # 旧（已轮换）token reuse → 401 REUSED
    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert res.status_code == 401
    assert res.json()["type"] == "auth.REFRESH_TOKEN_REUSED"
    # 关键：整个 family 在 DB 里必须全部撤销（含刚轮换出的新 token）。
    assert await _active_refresh_tokens() == [], (
        "reuse 检测后 family 仍有 active token —— 撤销被回滚"
    )
    # 刚轮换出的新 token 也不可再用。
    res2 = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert res2.status_code == 401


async def test_refresh_revokes_family_when_user_deactivated(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """🔴-2 第二路径回归：停用账号用 refresh → 撤销 family 的副作用须随事务提交；并产
    login_failed/auth.refresh 审计（Round-3 对称：与 reuse 路径留痕一致）。"""
    await _seed()
    first = await _login(client)
    async with db_session() as session:
        await session.execute(text("UPDATE users SET status='disabled' WHERE username='alice'"))
    with caplog.at_level(logging.INFO, logger="admin_platform.audit"):
        res = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
        )
    assert res.status_code == 401
    assert await _active_refresh_tokens() == [], "停用账号 refresh 后 family 未撤销 —— 副作用被回滚"
    audit = [getattr(r, "audit_event", None) for r in caplog.records]
    rejects = [
        e
        for e in audit
        if e and e.get("event_type") == "login_failed" and e.get("action") == "auth.refresh"
    ]
    assert rejects, "停用账号 refresh 拒绝未产审计事件（Round-3 对称缺口）"
