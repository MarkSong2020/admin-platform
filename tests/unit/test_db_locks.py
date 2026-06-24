"""app_locks 事务锁 helper 单测（DB-free）。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.db import locks
from admin_platform.domains.auth.repository import refresh_user_lock_name

pytestmark = pytest.mark.anyio
REPO_ROOT = Path(__file__).resolve().parents[2]


class _RecordingSession:
    def __init__(self, *, existing: str | None = None, events: list[str] | None = None) -> None:
        self.calls: list[tuple[str, Mapping[str, object] | None]] = []
        self._existing = existing
        self._events = events

    async def execute(
        self, statement: object, params: Mapping[str, object] | None = None
    ) -> _ScalarResult:
        sql = str(statement)
        self.calls.append((sql, params))
        if self._events is not None:
            self._events.append(sql)
        if "INSERT IGNORE INTO app_locks" in sql and params is not None:
            self._existing = str(params["name"])
        return _ScalarResult(self._existing)


class _ScalarResult:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> str | None:
        return self._value


class _FakeLoop:
    """WeakKeyDictionary 测试用 fake loop。"""


async def test_acquire_transaction_lock_uses_existing_row_without_extra_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RecordingSession(existing="dept:tree")
    ensured: list[str] = []

    async def fake_ensure(name: str) -> None:
        ensured.append(name)
        session._existing = name
        session._existing = name

    monkeypatch.setattr(locks, "_KNOWN_LOCK_ROWS", {"dept:tree"})
    monkeypatch.setattr(locks, "_ensure_lock_row", fake_ensure)

    await locks.acquire_transaction_lock(cast(AsyncSession, session), "dept:tree")

    assert ensured == []
    assert len(session.calls) == 1
    sql = session.calls[0][0]
    assert "FROM app_locks" in sql
    assert "FOR UPDATE" in sql


async def test_acquire_transaction_lock_precreates_missing_row_before_session_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    session = _RecordingSession(existing=None, events=events)
    ensured: list[str] = []

    async def fake_ensure(name: str) -> None:
        ensured.append(name)
        events.append(f"ensure:{name}")
        session._existing = name

    monkeypatch.setattr(locks, "_KNOWN_LOCK_ROWS", set())
    monkeypatch.setattr(locks, "_ensure_lock_row", fake_ensure)
    monkeypatch.setattr(locks, "_session_has_checked_out_connection", lambda _session: False)

    await locks.acquire_transaction_lock(cast(AsyncSession, session), "dept:tree")

    assert ensured == ["dept:tree"]
    assert len(session.calls) == 1
    assert events[0] == "ensure:dept:tree"
    assert "FOR UPDATE" in events[1]


async def test_acquire_transaction_lock_uses_current_transaction_when_session_has_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RecordingSession(existing=None)

    async def fake_ensure(name: str) -> None:
        raise AssertionError(f"must not borrow a second connection for {name}")

    monkeypatch.setattr(locks, "_KNOWN_LOCK_ROWS", set())
    monkeypatch.setattr(locks, "_ensure_lock_row", fake_ensure)
    monkeypatch.setattr(locks, "_session_has_checked_out_connection", lambda _session: True)

    await locks.acquire_transaction_lock(cast(AsyncSession, session), "auth:refresh-user:1")

    assert len(session.calls) == 4
    assert session.calls[0][0] == "SET sql_notes = 0"
    assert "INSERT IGNORE INTO app_locks" in session.calls[1][0]
    assert session.calls[2][0] == "SET sql_notes = 1"
    assert "FOR UPDATE" in session.calls[3][0]


async def test_acquire_transaction_lock_recreates_cached_row_when_for_update_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RecordingSession(existing=None)

    async def fake_ensure(name: str) -> None:
        raise AssertionError(f"must not borrow a second connection for {name}")

    monkeypatch.setattr(locks, "_KNOWN_LOCK_ROWS", {"dept:tree"})
    monkeypatch.setattr(locks, "_ensure_lock_row", fake_ensure)

    await locks.acquire_transaction_lock(cast(AsyncSession, session), "dept:tree")

    assert len(session.calls) == 5
    assert "FOR UPDATE" in session.calls[0][0]
    assert session.calls[1][0] == "SET sql_notes = 0"
    assert "INSERT IGNORE INTO app_locks" in session.calls[2][0]
    assert session.calls[3][0] == "SET sql_notes = 1"
    assert "FOR UPDATE" in session.calls[4][0]


async def test_ensure_transaction_lock_row_rechecks_even_when_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensured: list[str] = []

    async def fake_ensure(name: str) -> None:
        ensured.append(name)

    monkeypatch.setattr(locks, "_KNOWN_LOCK_ROWS", {"dept:tree"})
    monkeypatch.setattr(locks, "_ensure_lock_row", fake_ensure)

    await locks.ensure_transaction_lock_row("dept:tree")

    assert ensured == ["dept:tree"]


def test_ensure_guard_is_scoped_by_running_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop_a = _FakeLoop()
    loop_b = _FakeLoop()
    loops = iter([loop_a, loop_b, loop_a])

    monkeypatch.setattr(locks, "_ENSURE_ROW_GUARDS", locks.WeakKeyDictionary())
    monkeypatch.setattr(locks.asyncio, "get_running_loop", lambda: next(loops))

    guard_a = locks._ensure_guard("dept:tree")
    guard_b = locks._ensure_guard("dept:tree")
    guard_a_again = locks._ensure_guard("dept:tree")

    assert guard_a is guard_a_again
    assert guard_a is not guard_b


async def test_acquire_transaction_lock_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        await locks.acquire_transaction_lock(cast(AsyncSession, _RecordingSession()), "")


def test_app_locks_migration_is_idempotent_after_mysql_ddl_partial_apply() -> None:
    text = (REPO_ROOT / "migrations/versions/0021_mysql_app_locks.py").read_text()

    assert "CREATE TABLE IF NOT EXISTS app_locks" in text
    assert "PRIMARY KEY (name)" in text
    # 第二轮修复：CREATE IF NOT EXISTS 之外的幂等修正 + 迁移内自检（堵既存错误表逃逸 ENGINE 声明）。
    assert "ALTER TABLE app_locks ENGINE=InnoDB" in text
    assert "CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin" in text
    assert "assert_app_locks_table_healthy" in text


def test_refresh_user_lock_name_buckets_user_id_into_bounded_set() -> None:
    """per-user refresh 锁名分桶（I-2）：同 user_id 同桶（确定性），user_id 与 user_id+4096 同桶
    （取模有界），避免 app_locks 行 / 进程缓存随 user_id 无界增长。auth 与 monitor 复用同一 helper。"""
    assert refresh_user_lock_name(1) == refresh_user_lock_name(1)
    assert refresh_user_lock_name(1) == refresh_user_lock_name(1 + 4096)
    assert refresh_user_lock_name(1) != refresh_user_lock_name(2)
    assert refresh_user_lock_name(5).startswith("auth:refresh-user:")
