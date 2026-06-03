"""Task 7：get_session 从 request.state 注入 tenant→session.info；system_session 设 SYSTEM_CTX。

DB-free：``async session.begin()`` 惰性，不连库即可读 session.info（已实测，见探针）。
真实请求路径下的隔离效果由 Task 10 集成测试端到端覆盖。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from admin_platform.db.session import get_session, system_session
from admin_platform.db.tenant_filter import SYSTEM_CTX, TENANT_CTX_KEY


def _fake_request(**state: object) -> Request:
    """构造最小 Request 并预置 request.state（不进 ASGI，仅供依赖单测）。"""
    request = Request({"type": "http"})
    for key, value in state.items():
        setattr(request.state, key, value)
    return request


@asynccontextmanager
async def _first_session(request: Request) -> AsyncIterator[AsyncSession]:
    """驱动 get_session 依赖、yield 首个 session 并确保 aclose（cast 因注解是 AsyncIterator）。"""
    gen = cast("AsyncGenerator[AsyncSession]", get_session(request))
    try:
        yield await anext(gen)
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_get_session_injects_tenant_ctx() -> None:
    async with _first_session(_fake_request(tenant_id=42, is_platform=False)) as session:
        assert session.info[TENANT_CTX_KEY] == {"tenant_id": 42, "platform": False}


@pytest.mark.asyncio
async def test_get_session_propagates_is_platform() -> None:
    async with _first_session(_fake_request(tenant_id=1, is_platform=True)) as session:
        assert session.info[TENANT_CTX_KEY] == {"tenant_id": 1, "platform": True}


@pytest.mark.asyncio
async def test_get_session_without_tenant_sets_no_ctx() -> None:
    # public 路径（如登录）无 tenant_id → 不设上下文；此类 handler 须走 system_session。
    async with _first_session(_fake_request()) as session:
        assert TENANT_CTX_KEY not in session.info


@pytest.mark.asyncio
async def test_system_session_sets_system_ctx() -> None:
    async with system_session() as session:
        assert session.info[TENANT_CTX_KEY] is SYSTEM_CTX
