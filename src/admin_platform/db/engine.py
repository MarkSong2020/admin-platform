"""Async SQLAlchemy engine 和 sessionmaker —— 懒加载、缓存、可释放。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from admin_platform.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    is_mysql = settings.database_url.startswith("mysql+aiomysql://")
    engine_kwargs: dict[str, Any] = {
        "echo": settings.db_echo,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
    }
    if is_mysql:
        engine_kwargs["isolation_level"] = "READ COMMITTED"

    engine = create_async_engine(settings.database_url, **engine_kwargs)
    if is_mysql:
        _install_mysql_utc_session_hook(engine)
    return engine


def _install_mysql_utc_session_hook(engine: AsyncEngine) -> None:
    """MySQL 连接入池时固定会话时区，保证 DB 侧时间函数按 UTC 解释。"""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_utc_time_zone(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET time_zone = '+00:00'")
        finally:
            cursor.close()


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )


async def dispose_engine() -> None:
    """关 pool 并重置缓存的 engine —— 在 lifespan shutdown / 测试中调用。"""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
