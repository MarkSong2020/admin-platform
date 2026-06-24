"""MySQL DATETIME 的 UTC 读写闭环测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.auth.models import LoginLog
from tests.integration.db_cleanup import truncate_tables

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _clean_login_logs() -> AsyncIterator[None]:
    await truncate_tables("login_logs")
    yield
    await truncate_tables("login_logs")


async def test_mysql_datetime_roundtrip_preserves_utc_instant(
    session: AsyncSession,
) -> None:
    plus_eight = timezone(timedelta(hours=8))
    original = datetime(2026, 6, 24, 18, 30, tzinfo=plus_eight)
    expected_utc_aware = datetime(2026, 6, 24, 10, 30, tzinfo=UTC)
    expected_utc_naive = datetime(2026, 6, 24, 10, 30)
    before_insert = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=2)

    row = LoginLog(
        username="tz-probe",
        user_id=None,
        status="success",
        login_at_utc=original,
    )
    session.add(row)
    await session.flush()
    row_id = row.id
    await session.commit()
    after_insert = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=2)

    raw_result = await session.execute(
        text("SELECT login_at_utc, created_at, updated_at FROM login_logs WHERE id = :id"),
        {"id": row_id},
    )
    raw_login_at, raw_created_at, raw_updated_at = raw_result.one()
    assert raw_login_at == expected_utc_naive
    assert before_insert <= raw_created_at <= after_insert
    assert before_insert <= raw_updated_at <= after_insert

    session.expunge_all()
    loaded_result = await session.execute(select(LoginLog).where(LoginLog.id == row_id))
    loaded = loaded_result.scalar_one()

    assert loaded.login_at_utc == expected_utc_aware
    assert loaded.login_at_utc.tzinfo is UTC
    assert loaded.created_at.tzinfo is UTC
    assert loaded.updated_at.tzinfo is UTC
