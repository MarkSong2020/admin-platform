"""Transaction-boundary integration tests — guards the P0 regression that
prompted v0.4.11.

Pre-v0.4.11 the ``get_session`` dep only ``yield``-ed a session without
opening a transaction, so handler-side ``session.flush()`` writes were
silently rolled back at ``session.close()``. Every generator-produced
``create/update/delete`` was a no-op against the database.

These tests prove, against a real Postgres, that:

  1. a 2xx-returning handler COMMITs its writes (next request can read them)
  2. a handler that raises ROLLBACKs all writes from the same request
  3. ``session.begin_nested()`` (SAVEPOINT) inside a handler can partially
     roll back without aborting the outer request transaction
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db.engine import dispose_engine, get_engine
from admin_platform.db.session import get_session
from admin_platform.main import create_app

pytestmark = pytest.mark.integration

# Scratch table — auto-created per test, dropped after. Name prefixed with an
# underscore so it cannot collide with any business migration.
_TABLE = "_test_txn_scratch"

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@pytest_asyncio.fixture
async def scratch_table() -> AsyncIterator[None]:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {_TABLE}"))
        await conn.execute(text(f"CREATE TABLE {_TABLE} (val TEXT NOT NULL)"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {_TABLE}"))
    await dispose_engine()


@pytest_asyncio.fixture
async def app_with_txn_endpoints(scratch_table: None) -> FastAPI:
    """create_app() + temporary endpoints that exercise get_session writes."""
    del scratch_table  # fixture dependency only
    app = create_app()

    @app.post("/_test/write/{value}")
    async def write(value: str, session: SessionDep) -> dict[str, str]:
        await session.execute(text(f"INSERT INTO {_TABLE} (val) VALUES (:v)"), {"v": value})
        return {"wrote": value}

    @app.post("/_test/write_then_fail/{value}")
    async def write_then_fail(value: str, session: SessionDep) -> dict[str, str]:
        await session.execute(text(f"INSERT INTO {_TABLE} (val) VALUES (:v)"), {"v": value})
        raise HTTPException(status_code=500, detail="boom")

    @app.post("/_test/savepoint/{good}/{bad}")
    async def savepoint(good: str, bad: str, session: SessionDep) -> dict[str, str]:
        # Outer write — part of the request transaction.
        await session.execute(text(f"INSERT INTO {_TABLE} (val) VALUES (:v)"), {"v": good})
        # Nested savepoint that fails — only `bad` gets rolled back; `good` stays.
        try:
            async with session.begin_nested():
                await session.execute(text(f"INSERT INTO {_TABLE} (val) VALUES (:v)"), {"v": bad})
                raise RuntimeError("nested boom")
        except RuntimeError:
            pass
        return {"committed": good, "rolled_back": bad}

    @app.get("/_test/count")
    async def count(session: SessionDep) -> dict[str, int]:
        result = await session.execute(text(f"SELECT COUNT(*) FROM {_TABLE}"))
        return {"count": int(result.scalar_one())}

    @app.get("/_test/values")
    async def values(session: SessionDep) -> dict[str, list[str]]:
        result = await session.execute(text(f"SELECT val FROM {_TABLE} ORDER BY val"))
        return {"values": [row[0] for row in result.all()]}

    return app


@pytest_asyncio.fixture
async def async_client(app_with_txn_endpoints: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app_with_txn_endpoints), base_url="http://test"
    ) as c:
        yield c


async def test_handler_2xx_commits_writes_visible_to_next_request(
    async_client: AsyncClient,
) -> None:
    """The P0 guard: pre-v0.4.11 this test would fail because session.close()
    rolled back the INSERT before the next request's session could see it."""
    write = await async_client.post("/_test/write/alpha")
    assert write.status_code == 200

    # Brand-new request, brand-new session — must observe the committed row.
    count = await async_client.get("/_test/count")
    assert count.status_code == 200
    assert count.json() == {"count": 1}


async def test_handler_raises_rolls_back_all_writes(async_client: AsyncClient) -> None:
    """Symmetry of the contract — failure path must NOT persist."""
    fail = await async_client.post("/_test/write_then_fail/beta")
    assert fail.status_code == 500

    count = await async_client.get("/_test/count")
    assert count.json() == {"count": 0}


async def test_nested_savepoint_isolates_partial_rollback(
    async_client: AsyncClient,
) -> None:
    """SAVEPOINT inside a handler can fail without killing the outer txn.
    `good` stays committed; `bad` is rolled back at the nested level."""
    rsp = await async_client.post("/_test/savepoint/good_row/bad_row")
    assert rsp.status_code == 200

    values = await async_client.get("/_test/values")
    assert values.json() == {"values": ["good_row"]}
