"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_platform.core.config import get_settings
from admin_platform.db.engine import dispose_engine, get_engine
from admin_platform.main import create_app


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
