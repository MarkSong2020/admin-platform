"""监控 DTO 时间字段 UTC 归一化测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

from admin_platform.domains.monitor.schemas import LoginLogRead, OnlineSession


def test_monitor_from_attributes_naive_datetime_is_utc() -> None:
    row = SimpleNamespace(
        id=1,
        username="alice",
        user_id=1,
        status="success",
        reason_code=None,
        ip=None,
        user_agent=None,
        request_id=None,
        login_at_utc=datetime(2026, 6, 23, 10, 0),
        created_at=datetime(2026, 6, 23, 10, 1),
    )

    dto = LoginLogRead.model_validate(row)

    assert dto.login_at_utc.tzinfo is UTC
    assert dto.created_at.tzinfo is UTC
    assert dto.model_dump(mode="json")["login_at_utc"].endswith("Z")


def test_monitor_aware_datetime_is_converted_to_utc() -> None:
    plus_eight = timezone(timedelta(hours=8))

    dto = OnlineSession(
        session_id="s1",
        user_id=1,
        username="alice",
        login_time=datetime(2026, 6, 23, 18, 0, tzinfo=plus_eight),
        last_active_time=datetime(2026, 6, 23, 18, 30, tzinfo=plus_eight),
        expires_at=datetime(2026, 6, 24, 18, 0, tzinfo=plus_eight),
    )

    assert dto.login_time == datetime(2026, 6, 23, 10, 0, tzinfo=UTC)
    assert dto.last_active_time == datetime(2026, 6, 23, 10, 30, tzinfo=UTC)
    assert dto.expires_at == datetime(2026, 6, 24, 10, 0, tzinfo=UTC)
