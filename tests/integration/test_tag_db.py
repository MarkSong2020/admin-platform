"""/api/v1/tags 的集成测试 — 真实 Postgres CRUD。

比 todo 套件简单 —— tag 业务规则简单（无 enum、无 nullable 时间戳、
不在本侧管理多对多）。跨 domain 的 ``ON DELETE CASCADE`` 行为放 todo
套件（``test_delete_tag_cascades_through_association``）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from admin_platform.db.engine import get_engine

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _truncate_all() -> AsyncIterator[None]:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE todo_tags, todos, tags RESTART IDENTITY CASCADE"))
    yield


async def test_create_then_get(async_client: AsyncClient) -> None:
    created = await async_client.post("/api/v1/tags", json={"name": "urgent"})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "urgent"

    fetched = await async_client.get(f"/api/v1/tags/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "urgent"


async def test_get_missing_returns_404(async_client: AsyncClient) -> None:
    res = await async_client.get("/api/v1/tags/999")
    assert res.status_code == 404
    assert res.json()["type"] == "admin_platform.TAG_NOT_FOUND"


async def test_duplicate_name_returns_409(async_client: AsyncClient) -> None:
    first = await async_client.post("/api/v1/tags", json={"name": "urgent"})
    assert first.status_code == 201
    dup = await async_client.post("/api/v1/tags", json={"name": "urgent"})
    assert dup.status_code == 409
    assert dup.json()["type"] == "admin_platform.TAG_NAME_DUPLICATE"


async def test_patch_renames(async_client: AsyncClient) -> None:
    created = await async_client.post("/api/v1/tags", json={"name": "urgent"})
    tag_id = created.json()["id"]

    patched = await async_client.patch(f"/api/v1/tags/{tag_id}", json={"name": "critical"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "critical"


async def test_delete_then_get_returns_404(async_client: AsyncClient) -> None:
    created = await async_client.post("/api/v1/tags", json={"name": "ephemeral"})
    tag_id = created.json()["id"]

    deleted = await async_client.delete(f"/api/v1/tags/{tag_id}")
    assert deleted.status_code == 204

    refetched = await async_client.get(f"/api/v1/tags/{tag_id}")
    assert refetched.status_code == 404


async def test_list_returns_pagination_envelope(async_client: AsyncClient) -> None:
    for i in range(3):
        await async_client.post("/api/v1/tags", json={"name": f"tag-{i}"})

    res = await async_client.get("/api/v1/tags?page=1&size=10")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert body["total_pages"] == 1
    assert len(body["items"]) == 3
