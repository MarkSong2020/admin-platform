"""UTCDateTime 类型转换测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from admin_platform.db.base import UTCDateTime


def _dialect(name: str) -> Any:
    return SimpleNamespace(name=name)


def test_bind_aware_datetime_as_utc_naive_for_mysql() -> None:
    typ = UTCDateTime()
    plus_eight = timezone(timedelta(hours=8))

    bound = typ.process_bind_param(
        datetime(2026, 6, 24, 18, 30, tzinfo=plus_eight),
        _dialect("mysql"),
    )

    assert bound is not None
    assert bound == datetime(2026, 6, 24, 10, 30)
    assert bound.tzinfo is None


def test_bind_naive_datetime_treats_value_as_utc() -> None:
    typ = UTCDateTime()

    bound = typ.process_bind_param(
        datetime(2026, 6, 24, 10, 30),
        _dialect("mysql"),
    )

    assert bound is not None
    assert bound == datetime(2026, 6, 24, 10, 30)
    assert bound.tzinfo is None


def test_result_naive_datetime_is_returned_as_utc_aware() -> None:
    typ = UTCDateTime()

    value = typ.process_result_value(
        datetime(2026, 6, 24, 10, 30),
        _dialect("mysql"),
    )

    assert value is not None
    assert value == datetime(2026, 6, 24, 10, 30, tzinfo=UTC)
    assert value.tzinfo is UTC


def test_postgresql_bind_keeps_aware_utc_value() -> None:
    typ = UTCDateTime()
    plus_eight = timezone(timedelta(hours=8))

    bound = typ.process_bind_param(
        datetime(2026, 6, 24, 18, 30, tzinfo=plus_eight),
        _dialect("postgresql"),
    )

    assert bound is not None
    assert bound == datetime(2026, 6, 24, 10, 30, tzinfo=UTC)
    assert bound.tzinfo is UTC
