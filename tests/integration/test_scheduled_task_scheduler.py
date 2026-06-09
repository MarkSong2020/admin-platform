"""调度器 + 执行 claim 集成测试（P4c 多 worker 红线核心）—— 需 DB。

覆盖：① leader election 单赢家 + failover 接管（PG advisory lock）；② **执行 claim 并发去重**
（两 worker 同 tick 触发同任务 → partial unique 只放一条，红线正确性层）；③ allow_concurrent=False
上次未跑完 → skipped；④ reconcile 只装载 enabled 任务；⑤ _fire 产 schedule 执行日志。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from admin_platform.core.config import get_settings
from admin_platform.db.engine import dispose_engine
from admin_platform.db.session import db_session
from admin_platform.domains.scheduled_task.executor import ExecutionOutcome, TaskExecutor
from admin_platform.domains.scheduled_task.models import ScheduledTask, ScheduledTaskLog
from admin_platform.domains.scheduled_task.registry import (
    JOB_REGISTRY,
    HandlerSpec,
    JobHandlerRegistry,
)
from admin_platform.domains.scheduled_task.scheduler import SchedulerController

pytestmark = pytest.mark.integration

_SCHED_AT = datetime(2026, 6, 10, 2, 0, tzinfo=UTC)


def _settings():
    return get_settings().model_copy(
        update={"scheduler_enabled": True, "scheduler_poll_seconds": 3600}
    )


async def _wipe() -> None:
    async with db_session() as s:
        await s.execute(text("TRUNCATE TABLE scheduled_task_logs, scheduled_tasks CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()
    await dispose_engine()


async def _seed_task(**kw: object) -> int:
    async with db_session() as s:
        defaults: dict[str, object] = {
            "name": "j",
            "handler_key": "noop",
            "params_json": {},
            "cron_expression": "0 2 * * *",
            "cron_timezone": "Asia/Shanghai",
            "status": "enabled",
            "allow_concurrent": False,
            "misfire_grace_seconds": 300,
        }
        defaults.update(kw)
        task = ScheduledTask(**defaults)
        s.add(task)
        await s.flush()
        return task.id


async def _count_logs(*, task_id: int, scheduled_at: datetime | None = None) -> int:
    async with db_session() as s:
        stmt = (
            select(func.count())
            .select_from(ScheduledTaskLog)
            .where(ScheduledTaskLog.task_id == task_id)
        )
        if scheduled_at is not None:
            stmt = stmt.where(ScheduledTaskLog.scheduled_at == scheduled_at)
        return int((await s.execute(stmt)).scalar_one())


# ---- leader election ----


async def test_leader_election_single_winner() -> None:
    a = SchedulerController(_settings(), JOB_REGISTRY)
    b = SchedulerController(_settings(), JOB_REGISTRY)
    await a.start()
    await b.start()
    try:
        assert a.is_leader is True
        assert b.is_leader is False  # a 持锁，b 抢不到
    finally:
        await a.stop()
        await b.stop()


async def test_leader_failover() -> None:
    a = SchedulerController(_settings(), JOB_REGISTRY)
    b = SchedulerController(_settings(), JOB_REGISTRY)
    await a.start()
    await b.start()
    try:
        assert a.is_leader and not b.is_leader
        await a.stop()  # 释放锁
        assert await b._try_acquire_leader() is True  # b 接管
    finally:
        await b.stop()
        await a.stop()


# ---- 执行 claim 并发去重（红线核心）----


async def test_schedule_claim_dedup_concurrent() -> None:
    """两 worker 同 tick 触发同任务 → partial unique 只放一条（防 failover 双执行）。"""
    task_id = await _seed_task()
    ex = TaskExecutor(JOB_REGISTRY)
    results = await asyncio.gather(
        ex.run(task_id, trigger_type="schedule", scheduled_at=_SCHED_AT, actor_user_id=None),
        ex.run(task_id, trigger_type="schedule", scheduled_at=_SCHED_AT, actor_user_id=None),
        return_exceptions=True,
    )
    # 无异常冒泡（claim 冲突在 executor 内部消化为 None）。
    assert not any(isinstance(r, BaseException) for r in results), results
    won = [r for r in results if isinstance(r, ExecutionOutcome)]
    assert len(won) == 1  # 仅一个 worker 真正执行
    assert won[0].status == "success"  # 赢家正常跑完
    assert results.count(None) == 1  # 败者走 IntegrityError→None（claim 被抢），非异常静默
    assert await _count_logs(task_id=task_id, scheduled_at=_SCHED_AT) == 1  # 仅一条日志


async def test_schedule_claim_dedup_sequential() -> None:
    task_id = await _seed_task()
    ex = TaskExecutor(JOB_REGISTRY)
    first = await ex.run(
        task_id, trigger_type="schedule", scheduled_at=_SCHED_AT, actor_user_id=None
    )
    second = await ex.run(
        task_id, trigger_type="schedule", scheduled_at=_SCHED_AT, actor_user_id=None
    )
    assert first is not None and first.status == "success"
    assert second is None  # 同 (task, scheduled_at) 已被 claim
    assert await _count_logs(task_id=task_id, scheduled_at=_SCHED_AT) == 1


# ---- 并发策略 ----


async def test_allow_concurrent_false_skips_when_running() -> None:
    task_id = await _seed_task(allow_concurrent=False)
    async with db_session() as s:
        s.add(
            ScheduledTaskLog(
                task_id=task_id,
                execution_id=uuid.uuid4(),
                trigger_type="manual",
                handler_key="noop",
                params_json={},
                status="running",
                started_at=datetime.now(UTC),
            )
        )
    ex = TaskExecutor(JOB_REGISTRY)
    outcome = await ex.run(task_id, trigger_type="manual", scheduled_at=None, actor_user_id=None)
    assert outcome is not None
    assert outcome.status == "skipped"


# ---- reconcile + _fire ----


async def test_reconcile_loads_only_enabled() -> None:
    enabled = await _seed_task(name="e1", status="enabled")
    await _seed_task(name="d1", status="disabled")
    ctl = SchedulerController(_settings(), JOB_REGISTRY)
    await ctl.start()
    try:
        assert ctl.is_leader
        assert ctl._scheduler is not None
        assert {j.id for j in ctl._scheduler.get_jobs()} == {str(enabled)}
    finally:
        await ctl.stop()


async def test_fire_creates_schedule_log() -> None:
    task_id = await _seed_task(status="enabled")
    ctl = SchedulerController(_settings(), JOB_REGISTRY)
    await ctl._fire(task_id)  # 直接触发 wrapper（不依赖定时）
    assert await _count_logs(task_id=task_id) == 1
    async with db_session() as s:
        log = (await s.execute(select(ScheduledTaskLog))).scalar_one()
        assert log.trigger_type == "schedule"
        assert log.status == "success"


async def test_reconcile_removes_disabled_job() -> None:
    task_id = await _seed_task(name="e1", status="enabled")
    ctl = SchedulerController(_settings(), JOB_REGISTRY)
    await ctl.start()
    try:
        assert ctl._scheduler is not None
        assert {j.id for j in ctl._scheduler.get_jobs()} == {str(task_id)}
        async with db_session() as s:
            task = await s.get(ScheduledTask, task_id)
            assert task is not None
            task.status = "disabled"
        await ctl._reconcile()
        assert ctl._scheduler.get_jobs() == []  # 禁用后从调度器摘除
    finally:
        await ctl.stop()


async def test_reconcile_skips_invalid_cron() -> None:
    # 直插（绕 service 校验）一个 enabled 但 cron 非法的任务，reconcile 不抛、不调度它。
    await _seed_task(name="bad", status="enabled", cron_expression="not a cron")
    ctl = SchedulerController(_settings(), JOB_REGISTRY)
    await ctl.start()
    try:
        assert ctl._scheduler is not None
        assert ctl._scheduler.get_jobs() == []
    finally:
        await ctl.stop()


# ---- executor 失败链路（handler 抛异常 / 超时 / 下线）----


def _registry_with(**handlers: object) -> JobHandlerRegistry:
    reg = JobHandlerRegistry()
    for key, handler in handlers.items():
        reg.register(HandlerSpec(key, key, handler))  # type: ignore[arg-type]
    return reg


async def _boom(params: dict) -> str | None:
    raise RuntimeError("boom detail")


async def _slow(params: dict) -> str | None:
    await asyncio.sleep(5)
    return "done"


async def test_executor_handler_failure_records_failure_log() -> None:
    task_id = await _seed_task(handler_key="boom")
    ex = TaskExecutor(_registry_with(boom=_boom))
    outcome = await ex.run(task_id, trigger_type="manual", scheduled_at=None, actor_user_id=None)
    assert outcome is not None and outcome.status == "failure"
    async with db_session() as s:
        log = (await s.execute(select(ScheduledTaskLog))).scalar_one()
        assert log.status == "failure"
        assert log.error_code == "RuntimeError"
        assert log.error_message is not None and "boom detail" in log.error_message
        assert log.duration_ms is not None
        task = await s.get(ScheduledTask, task_id)
        assert task is not None and task.last_status == "failure"


async def test_executor_handler_timeout_records_failure() -> None:
    task_id = await _seed_task(handler_key="slow", timeout_seconds=1)
    ex = TaskExecutor(_registry_with(slow=_slow))
    outcome = await ex.run(task_id, trigger_type="manual", scheduled_at=None, actor_user_id=None)
    assert outcome is not None and outcome.status == "failure"
    async with db_session() as s:
        log = (await s.execute(select(ScheduledTaskLog))).scalar_one()
        assert log.error_code == "scheduled_task.TIMEOUT"


async def test_executor_handler_offline_records_failure() -> None:
    task_id = await _seed_task(handler_key="ghost")  # JOB_REGISTRY 无此 handler
    ex = TaskExecutor(JOB_REGISTRY)
    outcome = await ex.run(task_id, trigger_type="manual", scheduled_at=None, actor_user_id=None)
    assert outcome is not None and outcome.status == "failure"
    async with db_session() as s:
        log = (await s.execute(select(ScheduledTaskLog))).scalar_one()
        assert log.error_code == "scheduled_task.HANDLER_NOT_REGISTERED"
