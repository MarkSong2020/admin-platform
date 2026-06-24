"""MySQL 迁移阶段 3 并发控制验证脚本。

运行前需设置 ``APP_DATABASE_URL`` 指向本地 disposable MySQL 测试库，并已执行
``alembic upgrade head``，同时显式设置 ``APP_TEST_DB_ALLOW_DESTRUCTIVE=1``。脚本会清空
``scheduled_task_logs``、``scheduled_tasks`` 和 ``app_locks``，只用于本地空库/测试库。
"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import func, select, text
from tests.integration.db_cleanup import assert_destructive_test_database_allowed

from admin_platform.core.config import get_settings
from admin_platform.db.engine import dispose_engine, get_engine
from admin_platform.db.locks import acquire_transaction_lock
from admin_platform.db.session import db_session
from admin_platform.domains.scheduled_task.executor import ExecutionOutcome, TaskExecutor
from admin_platform.domains.scheduled_task.models import ScheduledTask, ScheduledTaskLog
from admin_platform.domains.scheduled_task.registry import (
    HandlerSpec,
    JobHandlerRegistry,
)
from admin_platform.domains.scheduled_task.scheduler import SchedulerController

_SCHEDULED_AT = datetime(2026, 6, 24, 3, 0, tzinfo=UTC)
_WORKERS = 12


@dataclass
class _CriticalSectionState:
    active: int = 0
    max_active: int = 0


async def _handler(_params: dict[str, Any]) -> str:
    return "phase3-ok"


def _registry() -> JobHandlerRegistry:
    registry = JobHandlerRegistry()
    registry.register(HandlerSpec("phase3_noop", "阶段3验证空任务", _handler))
    return registry


def _emit(line: str) -> None:
    sys.stdout.write(f"{line}\n")


def _as_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _reset_tables() -> None:
    async with db_session() as session:
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            await session.execute(text("TRUNCATE TABLE scheduled_task_logs"))
            await session.execute(text("TRUNCATE TABLE scheduled_tasks"))
            await session.execute(text("TRUNCATE TABLE app_locks"))
        finally:
            await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


async def _seed_task(
    name: str,
    *,
    cron_expression: str = "0 3 * * *",
    cron_timezone: str = "Asia/Shanghai",
    misfire_grace_seconds: int = 300,
) -> int:
    async with db_session() as session:
        task = ScheduledTask(
            name=name,
            handler_key="phase3_noop",
            params_json={},
            cron_expression=cron_expression,
            cron_timezone=cron_timezone,
            status="enabled",
            allow_concurrent=True,
            misfire_grace_seconds=misfire_grace_seconds,
        )
        session.add(task)
        await session.flush()
        return task.id


async def _count_logs(task_id: int) -> int:
    async with db_session() as session:
        stmt = (
            select(func.count())
            .select_from(ScheduledTaskLog)
            .where(
                ScheduledTaskLog.task_id == task_id,
                ScheduledTaskLog.scheduled_at == _SCHEDULED_AT,
            )
        )
        return int((await session.execute(stmt)).scalar_one())


async def _get_schedule_log(task_id: int) -> ScheduledTaskLog:
    async with db_session() as session:
        stmt = (
            select(ScheduledTaskLog)
            .where(
                ScheduledTaskLog.task_id == task_id,
                ScheduledTaskLog.trigger_type == "schedule",
            )
            .order_by(ScheduledTaskLog.id.desc())
            .limit(1)
        )
        log = (await session.execute(stmt)).scalar_one_or_none()
        if log is None:
            raise AssertionError(f"schedule log not found for task_id={task_id}")
        return log


async def _verify_get_lock_leader() -> None:
    settings = get_settings().model_copy(
        update={"scheduler_enabled": True, "scheduler_poll_seconds": 3600}
    )
    registry = _registry()
    first = SchedulerController(settings, registry)
    second = SchedulerController(settings, registry)
    await first.start()
    await second.start()
    try:
        leaders = [controller for controller in (first, second) if controller.is_leader]
        if len(leaders) != 1:
            raise AssertionError(f"expected exactly one leader, got {len(leaders)}")
        leader = leaders[0]
        standby = second if leader is first else first
        if leader._leader_conn is None:
            raise AssertionError("leader connection missing")
        leader_conn_id = (
            await leader._leader_conn.execute(text("SELECT CONNECTION_ID()"))
        ).scalar_one()
        await leader._leader_conn.commit()
        async with get_engine().connect() as killer:
            await killer.execute(text(f"KILL CONNECTION {int(leader_conn_id)}"))
            await killer.commit()
        demoted = await leader._verify_leadership()
        if demoted is not False or leader.is_leader:
            raise AssertionError("closed leader connection did not demote")
        if not await standby._try_acquire_leader():
            raise AssertionError("standby did not acquire GET_LOCK after leader disconnect")
        _emit("PASS get_lock_single_leader_and_disconnect_failover")
    finally:
        await second.stop()
        await first.stop()


async def _verify_app_lock_serializes() -> None:
    state = _CriticalSectionState()
    state_lock = asyncio.Lock()

    async def worker(worker_id: int) -> None:
        async with db_session() as session:
            await acquire_transaction_lock(session, "phase3:serial")
            async with state_lock:
                state.active += 1
                state.max_active = max(state.max_active, state.active)
            await asyncio.sleep(0.02 + worker_id * 0.001)
            async with state_lock:
                state.active -= 1

    await asyncio.gather(*(worker(i) for i in range(_WORKERS)))
    if state.max_active != 1:
        raise AssertionError(
            f"app_locks critical section overlapped: max_active={state.max_active}"
        )
    _emit(f"PASS app_locks_same_name_serializes workers={_WORKERS} max_active={state.max_active}")


async def _verify_scheduled_claim_dedup() -> None:
    task_id = await _seed_task(f"phase3-claim-{uuid.uuid4().hex}")
    executor = TaskExecutor(_registry())
    results = await asyncio.gather(
        *(
            executor.run(
                task_id, trigger_type="schedule", scheduled_at=_SCHEDULED_AT, actor_user_id=None
            )
            for _ in range(_WORKERS)
        )
    )
    winners = [result for result in results if isinstance(result, ExecutionOutcome)]
    if len(winners) != 1 or results.count(None) != _WORKERS - 1:
        raise AssertionError(f"unexpected claim results: {results!r}")
    rows = await _count_logs(task_id)
    if rows != 1:
        raise AssertionError(f"expected one schedule log row, got {rows}")
    _emit(
        f"PASS scheduled_claim_same_task_dedup workers={_WORKERS} winners={len(winners)} rows={rows}"
    )


async def _verify_different_tasks_do_not_share_claim_lock() -> None:
    task_a = await _seed_task(f"phase3-task-a-{uuid.uuid4().hex}")
    task_b = await _seed_task(f"phase3-task-b-{uuid.uuid4().hex}")
    executor = TaskExecutor(_registry())
    result_a, result_b = await asyncio.gather(
        executor.run(
            task_a, trigger_type="schedule", scheduled_at=_SCHEDULED_AT, actor_user_id=None
        ),
        executor.run(
            task_b, trigger_type="schedule", scheduled_at=_SCHEDULED_AT, actor_user_id=None
        ),
    )
    if not isinstance(result_a, ExecutionOutcome) or not isinstance(result_b, ExecutionOutcome):
        raise AssertionError(f"different task claims should both win: {result_a!r}, {result_b!r}")
    rows_a = await _count_logs(task_a)
    rows_b = await _count_logs(task_b)
    if (rows_a, rows_b) != (1, 1):
        raise AssertionError(f"expected one log per task, got {(rows_a, rows_b)}")
    _emit("PASS scheduled_claim_different_tasks_independent rows=2")


async def _verify_non_utc_tick_claim_dedup_and_storage() -> None:
    shanghai_now = datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai"))
    expected_local_tick = (shanghai_now - timedelta(minutes=2)).replace(second=0, microsecond=0)
    expected_utc_tick = expected_local_tick.astimezone(UTC)
    cron_expression = f"{expected_local_tick.minute} {expected_local_tick.hour} * * *"
    task_id = await _seed_task(
        f"phase3-non-utc-{uuid.uuid4().hex}",
        cron_expression=cron_expression,
        cron_timezone="Asia/Shanghai",
        misfire_grace_seconds=300,
    )
    executor = TaskExecutor(_registry())
    results = await asyncio.gather(
        *(
            executor.run(task_id, trigger_type="schedule", scheduled_at=None, actor_user_id=None)
            for _ in range(_WORKERS)
        )
    )
    winners = [result for result in results if isinstance(result, ExecutionOutcome)]
    if len(winners) != 1 or results.count(None) != _WORKERS - 1:
        raise AssertionError(f"unexpected non-UTC claim results: {results!r}")
    rows = await _count_schedule_logs(task_id)
    if rows != 1:
        raise AssertionError(f"expected one non-UTC schedule log row, got {rows}")
    log = await _get_schedule_log(task_id)
    if log.scheduled_at is None:
        raise AssertionError("non-UTC schedule claim wrote scheduled_at=NULL")
    stored = _as_utc_aware(log.scheduled_at)
    if stored != expected_utc_tick:
        raise AssertionError(
            "non-UTC cron tick was not stored as the expected UTC instant: "
            f"stored={stored.isoformat()}, expected={expected_utc_tick.isoformat()}, "
            f"cron={cron_expression!r}, timezone='Asia/Shanghai'"
        )
    _emit(
        "PASS scheduled_claim_non_utc_tick_utc_storage "
        f"workers={_WORKERS} winners={len(winners)} rows={rows}"
    )


async def _count_schedule_logs(task_id: int) -> int:
    async with db_session() as session:
        stmt = (
            select(func.count())
            .select_from(ScheduledTaskLog)
            .where(
                ScheduledTaskLog.task_id == task_id,
                ScheduledTaskLog.trigger_type == "schedule",
            )
        )
        return int((await session.execute(stmt)).scalar_one())


async def _verify_schema_basics() -> None:
    async with get_engine().connect() as conn:
        version = (await conn.execute(text("SELECT VERSION()"))).scalar_one()
        tz = (await conn.execute(text("SELECT @@session.time_zone"))).scalar_one()
    _emit(f"PASS mysql_version={version}")
    _emit(f"PASS session_time_zone={tz}")


async def main() -> int:
    try:
        assert_destructive_test_database_allowed(get_settings().database_url)
    except RuntimeError as exc:
        sys.stderr.write(f"拒绝执行破坏性阶段 3 验证脚本：{exc}\n")
        return 2
    try:
        await _reset_tables()
        await _verify_schema_basics()
        await _verify_get_lock_leader()
        await _verify_app_lock_serializes()
        await _verify_scheduled_claim_dedup()
        await _verify_different_tasks_do_not_share_claim_lock()
        await _verify_non_utc_tick_claim_dedup_and_storage()
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
