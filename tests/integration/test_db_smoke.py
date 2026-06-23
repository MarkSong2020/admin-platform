"""Smoke tests against the compose MySQL database — proves connectivity end-to-end."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_session_can_execute_select_1(session: AsyncSession) -> None:
    result = await session.execute(text("SELECT 1"))
    assert result.scalar() == 1


async def test_readyz_passes_against_real_db(async_client: AsyncClient) -> None:
    response = await async_client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
