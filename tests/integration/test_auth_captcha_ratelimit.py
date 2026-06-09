"""验证码 + 登录限流端到端（P1.4 slice 3+4，需本地 DB + Redis）。

Q14 联动：失败 N 次后 login 要求验证码；提供有效验证码后可登录。验证码一次性消费。
Redis 不可用则整组 skip（本仓 Redis opt-in）。
"""

from __future__ import annotations

import logging
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
    # Codex 深审解耦回归：登录防护靠 auth_login_guard_enabled 而非 idempotency。刻意关幂等
    # 仍开 guard → 验证码/限流必须照常生效（证明关幂等不再静默关防护）。
    monkeypatch.setenv("APP_IDEMPOTENCY_ENABLED", "false")
    monkeypatch.setenv("APP_AUTH_LOGIN_GUARD_ENABLED", "true")
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


# ---- Codex 复审安全回归 ----


async def test_account_lock_not_bypassable_by_captcha(client: AsyncClient) -> None:
    # Codex 复审：账号软锁后，即使验证码 + 密码都对也应统一 401（硬锁，不被验证码解）。
    # 直接植入软锁（触发路径需「过 captcha 后持续错密码」，此处直测核心行为：锁→401 不被解）。
    await _seed()
    r = Redis.from_url(_REDIS_URL)
    await r.setex("auth:lock:user:alice", get_settings().auth_login_lock_seconds, "1")
    await r.aclose()
    cap = (await client.get("/api/v1/auth/captcha")).json()
    res = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "alice",
            "password": _PW,  # 正确密码
            "captcha_id": cap["captcha_id"],
            "captcha_answer": _solve(cap["question"]),  # 正确验证码
        },
    )
    assert res.status_code == 401  # 锁定期内仍拒绝（不被验证码 + 正确密码解锁）
    assert res.json()["type"] == "auth.LOGIN_FAILED"


async def test_account_lock_emits_login_failed_audit(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    # Workflow 深审：账号硬锁分支返回 401 也必须 emit login_failed 审计——锁定窗口内的持续
    # 尝试正是暴力破解最该留痕的时刻，不能因「对客户端防枚举不暴露锁定」而连内部审计一起省略。
    await _seed()
    r = Redis.from_url(_REDIS_URL)
    await r.setex("auth:lock:user:alice", get_settings().auth_login_lock_seconds, "1")
    await r.aclose()
    with caplog.at_level(logging.INFO, logger="admin_platform.audit"):
        res = await client.post("/api/v1/auth/login", json={"username": "alice", "password": _PW})
    assert res.status_code == 401
    events = [getattr(rec, "audit_event", None) for rec in caplog.records]
    login_failed = [e for e in events if e and e.get("event_type") == "login_failed"]
    assert login_failed, "账号硬锁分支未 emit login_failed 审计"
    assert login_failed[0]["risk_level"] == "high"  # 锁定窗口尝试升 high


async def test_success_does_not_clear_ip_counter() -> None:
    # Codex 复审：成功登录不清全局 IP 失败计数（防同源 IP 撞库绕过）。
    r = Redis.from_url(_REDIS_URL)
    # 直接植入 IP 失败计数
    await r.set("auth:fail:ip:testclient", 7)
    await r.aclose()
    await _seed()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testclient") as c:
        ok = await c.post("/api/v1/auth/login", json={"username": "alice", "password": _PW})
        assert ok.status_code == 200, ok.text
    await dispose_engine()
    # 成功登录后 IP 计数仍在（未被清零）
    r = Redis.from_url(_REDIS_URL)
    remaining = await r.get("auth:fail:ip:testclient")
    await r.aclose()
    assert remaining is not None and int(remaining) == 7


async def test_captcha_one_time_use_consumed(client: AsyncClient) -> None:
    # 验证码取一次后即消费（GETDEL 原子）：同 id 再校验失败。
    await _seed()
    threshold = get_settings().auth_login_captcha_threshold
    for _ in range(threshold):
        await client.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong"})
    cap = (await client.get("/api/v1/auth/captcha")).json()
    answer = _solve(cap["question"])
    # 第一次用：成功
    first = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "alice",
            "password": _PW,
            "captcha_id": cap["captcha_id"],
            "captcha_answer": answer,
        },
    )
    assert first.status_code == 200
    # 直接验 Redis key 已删（一次性消费）
    r = Redis.from_url(_REDIS_URL)
    gone = await r.get(f"auth:captcha:{cap['captcha_id']}")
    await r.aclose()
    assert gone is None
