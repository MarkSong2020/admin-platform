"""登录日志集成测试（P2 Phase 3）—— 登录全路径落 login_logs + 审计 login_success/failed。

roadmap §167 验收：登录成功 / 失败各落 1 条登录日志（含操作人 / IP / 结果）。同时验证 IP/UA 经
中间件 ContextVar 灌入登录日志，audit_events 侧 login_success / login_failed 也落库。
guard 路径（限流 / 锁 / 验证码）的登录日志 Redis-gated（无 Redis 跳过）。需 DB。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, text

from admin_platform.audit.models import AuditEventLog
from admin_platform.audit.sink import DbAuditSink, configure_audit_sink
from admin_platform.core.config import get_settings
from admin_platform.core.security import hash_password
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.auth.models import LoginLog
from admin_platform.domains.user.models import User
from admin_platform.main import create_app

pytestmark = pytest.mark.integration

_SECRET = "integration-loginlog-secret-" + "x" * 32
_REDIS_URL = "redis://localhost:6379/0"
_PW = "correct-horse-battery-staple"


async def _wipe() -> None:
    async with db_session() as session:
        await session.execute(
            text("TRUNCATE TABLE login_logs, audit_events, auth_refresh_tokens, users CASCADE")
        )


async def _redis_available() -> bool:
    try:
        r = Redis.from_url(_REDIS_URL)
        await r.ping()  # type: ignore[misc]
        await r.aclose()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture(autouse=True)
async def _setup(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setenv("APP_AUTH_ENABLED", "true")
    monkeypatch.setenv("APP_AUTH_JWT_SECRET", _SECRET)
    get_settings.cache_clear()
    await _wipe()
    # lifespan 不在 ASGITransport 下跑，显式注册 sink（验证 audit_events 侧落库）。
    configure_audit_sink(DbAuditSink())
    yield
    configure_audit_sink(None)
    await _wipe()
    await dispose_engine()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_engine()


async def _seed(username: str, *, status: str = "active") -> int:
    async with db_session() as session:
        user = User(username=username, password_hash=hash_password(_PW), status=status)
        session.add(user)
        await session.flush()
        return user.id


async def _login_logs(status: str | None = None) -> list[LoginLog]:
    async with db_session() as session:
        stmt = select(LoginLog).order_by(LoginLog.id)
        if status is not None:
            stmt = stmt.where(LoginLog.status == status)
        return list((await session.execute(stmt)).scalars().all())


async def _audit_count(event_type: str) -> int:
    async with db_session() as session:
        rows = (
            await session.execute(
                select(AuditEventLog).where(AuditEventLog.event_type == event_type)
            )
        ).scalars()
        return len(list(rows))


async def test_login_success_records_login_log_and_audit(client: AsyncClient) -> None:
    uid = await _seed("alice")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": _PW},
        headers={"User-Agent": "pytest-login"},
    )
    assert resp.status_code == 200, resp.text

    logs = await _login_logs("success")
    assert len(logs) == 1
    assert logs[0].username == "alice"
    assert logs[0].user_id == uid
    assert logs[0].ip is not None
    assert logs[0].user_agent == "pytest-login"
    # audit_events 侧也有 login_success（envelope 完整覆盖登录活动）。
    assert await _audit_count("login_success") == 1


async def test_login_failure_records_login_log_and_audit(client: AsyncClient) -> None:
    await _seed("alice")
    resp = await client.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401

    logs = await _login_logs("failure")
    assert len(logs) == 1
    assert logs[0].username == "alice"
    assert logs[0].reason_code == "auth.LOGIN_FAILED"
    assert logs[0].ip is not None
    # 失败审计也落 audit_events（双轨：审计安全轨 + 登录历史）。
    assert await _audit_count("login_failed") == 1


async def test_login_unknown_user_records_failure_without_user_id(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/login", json={"username": "ghost", "password": _PW})
    assert resp.status_code == 401

    logs = await _login_logs("failure")
    assert len(logs) == 1
    assert logs[0].username == "ghost"
    assert logs[0].user_id is None  # 未知用户：防枚举不暴露，user_id 空


async def test_login_guard_captcha_path_logged() -> None:
    # Redis-gated：失败达验证码阈值后，下一次登录要求验证码 → login_logs 记 captcha_required。
    if not await _redis_available():
        pytest.skip("Redis 不可用（opt-in），跳过 guard 路径登录日志")
    r = Redis.from_url(_REDIS_URL)
    await r.flushdb()
    await r.aclose()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("APP_AUTH_ENABLED", "true")
        mp.setenv("APP_AUTH_JWT_SECRET", _SECRET)
        mp.setenv("APP_REDIS_URL", _REDIS_URL)
        mp.setenv("APP_IDEMPOTENCY_ENABLED", "false")
        mp.setenv("APP_AUTH_LOGIN_GUARD_ENABLED", "true")
        get_settings.cache_clear()
        await _seed("alice")
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # 默认 captcha_threshold=3：连错 3 次后第 4 次要求验证码。
            for _ in range(3):
                assert (
                    await c.post(
                        "/api/v1/auth/login", json={"username": "alice", "password": "wrong"}
                    )
                ).status_code == 401
            res = await c.post("/api/v1/auth/login", json={"username": "alice", "password": _PW})
            assert res.status_code == 403  # captcha required
        await dispose_engine()
        get_settings.cache_clear()

    assert len(await _login_logs("failure")) == 3
    assert len(await _login_logs("captcha_required")) == 1
