"""Async SQLAlchemy engine 和 sessionmaker —— 懒加载、缓存、可释放。"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from admin_platform.core.config import get_settings
from admin_platform.db.tenant_filter import install_tenant_filter


class AppSession(Session):
    """``async_sessionmaker`` 底层的 sync session 类 + 租户隔离事件的锚点。

    为什么要自定义子类而不是用全局 ``Session``：SessionEvents 在 async 下必须注册到
    ``async_sessionmaker`` 的 ``sync_session_class``（见 ADR-E / tenant_filter）。把事件
    挂在专属 ``AppSession`` 上而非全局 ``Session``，避免污染其它（如 Alembic 自带）session。
    """


# 模块加载时一次性把租户隔离事件注册到 AppSession（见 install_tenant_filter 的 ⚠️ 注释）。
install_tenant_filter(AppSession)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        get_engine(),
        sync_session_class=AppSession,  # 事件锚点：让 async 路径的底层 sync session 是 AppSession
        expire_on_commit=False,
        autoflush=False,
    )


async def dispose_engine() -> None:
    """关 pool 并重置缓存的 engine —— 在 lifespan shutdown / 测试中调用。"""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
