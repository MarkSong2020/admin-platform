"""Integration test fixtures.

Assumes ``make compose-up`` has brought up the local Postgres container and
``make migrate`` (or ``alembic upgrade head``) has been applied. The fixtures
here do not orchestrate Docker; that's the contract documented in README.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.core.config import get_settings
from admin_platform.db.engine import dispose_engine, get_sessionmaker
from admin_platform.main import create_app

pytestmark = pytest.mark.integration

# M8：集成 autouse fixture 会 TRUNCATE 核心表（users/roles/depts/...）——守卫连接串 host 必须是
# 本地/容器测试库。CI 用 @localhost，本地用 localhost/127.0.0.1，compose 内用 @db。
_LOCAL_DB_HOSTS = ("@localhost", "@127.0.0.1", "@db:", "@db/")


@pytest.fixture(scope="session", autouse=True)
def _guard_test_database() -> Iterator[None]:
    """M8（L3 环境守卫）：防开发者 shell 残留指向共享/预发库的 APP_DATABASE_URL 时被集成测试整库
    TRUNCATE。非本地库需显式 APP_TEST_DB_ALLOW_NONLOCAL=1 放行（自担风险）。"""
    url = get_settings().database_url
    local = any(host in url for host in _LOCAL_DB_HOSTS)
    if not local and os.getenv("APP_TEST_DB_ALLOW_NONLOCAL") != "1":
        pytest.exit(
            "集成测试拒绝在疑似非本地库执行 TRUNCATE（database_url host 非 localhost/127.0.0.1/db）；"
            "确认指向本地测试库，或显式 APP_TEST_DB_ALLOW_NONLOCAL=1 放行",
            returncode=2,
        )
    yield


@pytest.fixture(autouse=True)
def _disable_idempotency_by_default(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Baseline integration tests target the DB only — disable idempotency so
    the suite doesn't require ``--profile cache`` (Redis) on the compose
    stack. Tests that need Redis explicitly should re-enable via
    ``monkeypatch.setenv('APP_IDEMPOTENCY_ENABLED', 'true')`` and mark
    themselves so CI can pre-bring up Redis."""
    monkeypatch.setenv("APP_IDEMPOTENCY_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as s:
        yield s
    await dispose_engine()


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_engine()
