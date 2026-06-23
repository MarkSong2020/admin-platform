"""TaskExecutor.run() manual 触发兜底超时单测（hardening，DB-free）。

manual 经同步 HTTP 执行，长占请求连接/事务 → run() 对 trigger_type=="manual" 施加
``_MANUAL_RUN_MAX_TIMEOUT`` 兜底上限；schedule 后台触发不占连接，沿用任务级 timeout_seconds。

测真实 run() 的 cap 取值：override DB 边界方法（_claim/_invoke/_finish），捕获 _invoke
实际收到的 effective_timeout，不碰 DB。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from admin_platform.domains.scheduled_task import executor as executor_mod
from admin_platform.domains.scheduled_task.executor import (
    _MANUAL_RUN_MAX_TIMEOUT,
    TaskExecutor,
    _as_utc_for_storage,
)
from admin_platform.domains.scheduled_task.registry import JobHandlerRegistry

pytestmark = pytest.mark.anyio


class _CapturingExecutor(TaskExecutor):
    """绕过 DB 的 executor：_claim 返回固定 claim，_invoke 记录收到的 timeout，_finish 空转。"""

    def __init__(self, claim_timeout: int | None) -> None:
        super().__init__(JobHandlerRegistry())
        self._claim_timeout = claim_timeout
        self.invoked_timeout: int | None = -1  # 哨兵，run 后应被真实值覆盖

    async def _claim(  # type: ignore[override]
        self,
        task_id: int,
        *,
        trigger_type: str,
        scheduled_at: datetime | None,
        actor_user_id: int | None,
        execution_id: uuid.UUID,
    ) -> tuple[int, str, dict, int | None, bool]:
        # (log_id, handler_key, params, timeout_seconds, skipped)
        return (1, "noop", {}, self._claim_timeout, False)

    async def _invoke(  # type: ignore[override]
        self, handler_key: str, params: dict, timeout_seconds: int | None
    ) -> tuple[str, str | None, str | None, str | None]:
        self.invoked_timeout = timeout_seconds
        return ("success", None, None, None)

    async def _finish(self, *args: object, **kwargs: object) -> None:  # type: ignore[override]
        return None


class _ClaimOrderExecutor(TaskExecutor):
    def __init__(self, events: list[str]) -> None:
        super().__init__(JobHandlerRegistry())
        self._events = events

    async def _claim_once(  # type: ignore[override]
        self,
        task_id: int,
        *,
        trigger_type: str,
        scheduled_at: datetime | None,
        actor_user_id: int | None,
        execution_id: uuid.UUID,
    ) -> tuple[int, str, dict, int | None, bool]:
        self._events.append("claim")
        return (1, "noop", {}, None, True)


async def _run(executor: _CapturingExecutor, trigger_type: str) -> None:
    await executor.run(1, trigger_type=trigger_type, scheduled_at=None, actor_user_id=1)


async def test_manual_caps_unset_timeout_to_max() -> None:
    """manual + task.timeout_seconds=None → 兜底到 5min 上限（不让无超时任务长占 HTTP 连接）。"""
    ex = _CapturingExecutor(claim_timeout=None)
    await _run(ex, "manual")
    assert ex.invoked_timeout == _MANUAL_RUN_MAX_TIMEOUT


async def test_manual_caps_oversized_timeout_to_max() -> None:
    """manual + task.timeout_seconds=86400 → 被 cap 到 300（任务级长超时只在 schedule 生效）。"""
    ex = _CapturingExecutor(claim_timeout=86400)
    await _run(ex, "manual")
    assert ex.invoked_timeout == _MANUAL_RUN_MAX_TIMEOUT


async def test_manual_keeps_timeout_below_cap() -> None:
    """manual + task.timeout_seconds=60（< cap）→ 原样保留，不抬高。"""
    ex = _CapturingExecutor(claim_timeout=60)
    await _run(ex, "manual")
    assert ex.invoked_timeout == 60


async def test_schedule_does_not_cap_oversized_timeout() -> None:
    """schedule + task.timeout_seconds=86400 → 不 cap，沿用任务级值（后台触发不占请求连接）。"""
    ex = _CapturingExecutor(claim_timeout=86400)
    await _run(ex, "schedule")
    assert ex.invoked_timeout == 86400


async def test_schedule_keeps_unset_timeout_none() -> None:
    """schedule + task.timeout_seconds=None → 保持 None（无超时，由 handler 自身约束）。"""
    ex = _CapturingExecutor(claim_timeout=None)
    await _run(ex, "schedule")
    assert ex.invoked_timeout is None


async def test_claim_ensures_task_lock_row_before_opening_claim_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def fake_ensure(name: str) -> None:
        events.append(f"ensure:{name}")

    monkeypatch.setattr(executor_mod, "ensure_transaction_lock_row", fake_ensure, raising=False)

    ex = _ClaimOrderExecutor(events)
    await ex._claim(
        42,
        trigger_type="schedule",
        scheduled_at=None,
        actor_user_id=None,
        execution_id=uuid.uuid4(),
    )

    assert events == ["ensure:scheduled-task:claim:42", "claim"]


def test_scheduled_at_storage_converts_non_utc_tick_to_utc() -> None:
    """MySQL DATETIME 无 timezone；非 UTC cron tick 写库前必须保存 UTC instant。"""
    tick = datetime(2026, 6, 11, 2, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    stored = _as_utc_for_storage(tick)

    assert stored == datetime(2026, 6, 10, 18, 0, tzinfo=UTC)


def _integrity_error(code: int, message: str) -> IntegrityError:
    """构造带 MySQL 错误码 + 消息的 IntegrityError（orig.args[0]=code，str(orig) 含 message）。"""
    return IntegrityError("INSERT ...", {}, Exception(code, message))


def test_is_claim_taken_true_for_1062_claim_index() -> None:
    exc = _integrity_error(
        1062,
        "Duplicate entry '1-2026' for key "
        "'scheduled_task_logs.uq_scheduled_task_logs_schedule_claim'",
    )
    assert executor_mod._is_claim_taken(exc) is True


def test_is_claim_taken_false_for_1062_other_unique() -> None:
    # execution_id unique 也是 1062，但 key 名不同 → 不能当 claim 被抢，必须上抛。
    exc = _integrity_error(
        1062, "Duplicate entry 'uuid' for key 'scheduled_task_logs.execution_id'"
    )
    assert executor_mod._is_claim_taken(exc) is False


def test_is_claim_taken_false_for_non_1062_violation() -> None:
    # CHECK 违例（3819）等非 duplicate 错误必须上抛，不被吞成「被抢占」。
    exc = _integrity_error(3819, "Check constraint 'ck_x' is violated")
    assert executor_mod._is_claim_taken(exc) is False
