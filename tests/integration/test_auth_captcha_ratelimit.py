"""验证码 + 登录限流端到端（P1.4 slice 3+4，需本地 DB + Redis）。

Q14 联动：失败 N 次后 login 要求验证码；提供有效验证码后可登录。验证码一次性消费。
Redis 不可用则整组 skip（本仓 Redis opt-in）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text

from admin_platform.core.config import get_settings
from admin_platform.core.security import hash_password
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.user.models import User
from admin_platform.main import create_app

pytestmark = pytest.mark.integration

_SECRET = "integration-captcha-secret-" + "x" * 32
_REDIS_URL = "redis://localhost:6379/0"
_PW = "correct-horse-battery-staple"


async def _redis_available() -> bool:
    try:
        r = Redis.from_url(_REDIS_URL)
        await r.ping()  # type: ignore[misc]  # redis-py 7.x stub 把 async ping 标 bool（同 main.py）
        await r.aclose()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture(autouse=True)
async def _setup(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    if not await _redis_available():
        pytest.skip("Redis 不可用（opt-in），跳过验证码/限流测试")
    monkeypatch.setenv("APP_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_AUTH_JWT_SECRET", _SECRET)
    monkeypatch.setenv("APP_REDIS_URL", _REDIS_URL)
    monkeypatch.setenv("APP_IDEMPOTENCY_ENABLED", "true")
    get_settings.cache_clear()
    r = Redis.from_url(_REDIS_URL)
    await r.flushdb()
    await r.aclose()
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE auth_refresh_tokens, users CASCADE"))
    yield
    r = Redis.from_url(_REDIS_URL)
    await r.flushdb()
    await r.aclose()
    async with db_session() as session:
        await session.execute(text("TRUNCATE TABLE auth_refresh_tokens, users CASCADE"))
    await dispose_engine()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_engine()


async def _seed() -> None:
    async with db_session() as session:
        session.add(User(username="alice", password_hash=hash_password(_PW), status="active"))


def _solve(question: str) -> str:
    # "a + b = ?" → str(a+b)
    parts = question.split()
    return str(int(parts[0]) + int(parts[2]))


async def test_captcha_endpoint_and_one_time_use(client: AsyncClient) -> None:
    res = await client.get("/api/v1/auth/captcha")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["captcha_id"] and "?" in body["question"]


async def test_failures_then_require_captcha_then_pass(client: AsyncClient) -> None:
    await _seed()
    threshold = get_settings().auth_login_captcha_threshold
    # 失败到阈值（错密码）
    for _ in range(threshold):
        bad = await client.post(
            "/api/v1/auth/login", json={"username": "alice", "password": "wrong"}
        )
        assert bad.status_code == 401
    # 达阈值后即使密码对，无验证码 → CAPTCHA_REQUIRED（403）
    need = await client.post("/api/v1/auth/login", json={"username": "alice", "password": _PW})
    assert need.status_code == 403
    assert need.json()["type"] == "auth.CAPTCHA_REQUIRED"
    # 取验证码 → 解答 → 带验证码登录成功
    cap = (await client.get("/api/v1/auth/captcha")).json()
    ok = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "alice",
            "password": _PW,
            "captcha_id": cap["captcha_id"],
            "captcha_answer": _solve(cap["question"]),
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["access_token"]


async def test_wrong_captcha_rejected_after_threshold(client: AsyncClient) -> None:
    await _seed()
    threshold = get_settings().auth_login_captcha_threshold
    for _ in range(threshold):
        await client.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong"})
    cap = (await client.get("/api/v1/auth/captcha")).json()
    res = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "alice",
            "password": _PW,
            "captcha_id": cap["captcha_id"],
            "captcha_answer": "999999",  # 错误答案
        },
    )
    assert res.status_code == 403
    assert res.json()["type"] == "auth.CAPTCHA_REQUIRED"
