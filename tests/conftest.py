"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_platform.core.config import Settings, get_settings

# 测试隔离真实 .env（2026-06-15 PK 审查第一优先级）：本地 .env 含 APP_DEBUG / APP_AUTH_ENABLED /
# APP_AUTH_LOGIN_GUARD_ENABLED / pepper 等，会污染测试期望的默认配置——debug 脱敏关、auth 401、
# login_guard captcha 403，曾致 `make check` 出 19 个假失败、且随各开发者本地 .env 漂移不稳定。
# 测试一律**不读 .env 文件**、只认显式 env var（测试用 monkeypatch.setenv 注入）；DB/Redis 走 config
# 默认（已指向本地 compose）。生产 env_file=".env" 语义不变——仅本测试进程把它置空。
Settings.model_config["env_file"] = None

from admin_platform.db.engine import dispose_engine, get_engine  # noqa: E402
from admin_platform.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_settings_and_engine_cache() -> Iterator[None]:
    """Clear both ``Settings`` and the cached SQLAlchemy engine before/after
    every test. Without disposing the engine, a test that monkey-patches
    ``APP_DATABASE_URL`` could observe a stale engine pointed at the previous
    URL — a latent foot-gun that would surface the day someone added such
    a test."""
    get_settings.cache_clear()
    _sync_dispose_engine()
    yield
    get_settings.cache_clear()
    _sync_dispose_engine()


def _sync_dispose_engine() -> None:
    """Dispose the cached AsyncEngine from sync test setup/teardown.

    ``dispose_engine`` is async because the underlying pool close is async,
    but pytest fixtures here are sync. Skip the await when no engine has
    been instantiated yet (the common case for pure unit tests).

    Future-compat: avoid ``asyncio.get_event_loop()`` (deprecated in 3.12,
    removed in 3.14). Create a fresh loop per call — pytest fixtures are
    short-lived and this runs at most once per test.
    """
    if get_engine.cache_info().currsize == 0:
        return
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(dispose_engine())
    finally:
        loop.close()


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
