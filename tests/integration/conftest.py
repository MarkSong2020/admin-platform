"""集成测试 fixtures。

集成测试默认连接本地 MySQL 测试库；本文件不编排 Docker，启动和迁移约定见 README。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.core.config import get_settings
from admin_platform.db.engine import dispose_engine, get_sessionmaker
from admin_platform.main import create_app
from tests.integration.db_cleanup import assert_destructive_test_database_allowed

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session", autouse=True)
def _guard_test_database() -> Iterator[None]:
    """M8（L3 环境守卫）：防开发者 shell 残留指向共享/预发库的 APP_DATABASE_URL 时被集成测试整库
    TRUNCATE。所有破坏性清表都需显式 APP_TEST_DB_ALLOW_DESTRUCTIVE=1。"""
    try:
        assert_destructive_test_database_allowed(get_settings().database_url)
    except RuntimeError as exc:
        pytest.exit(
            str(exc),
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
