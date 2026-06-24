"""任务执行器 —— 手动触发 + 自动调度共用的执行核心（P4c）。

**两段 session（Codex 风险 #5 + 多 worker 红线）**：
1. claim session：建 running 日志并提交——让 claim 立即对其他 worker 可见，且 schedule 触发的
   ``(task_id, scheduled_at)`` 生成列唯一索引在 INSERT 时即生效（failover 窗口两 worker 同触发，
   只有一条成功，另一条撞唯一约束 → 跳过）。
2. handler 在**事务外**跑（不长持事务/连接）。
3. result session：写回 success/failure + 任务 last_run，提交。

并发：``allow_concurrent=False`` 且已有 running → 记 ``skipped``（不静默吞）。超时：``timeout_seconds``
经 ``asyncio.wait_for``。错误信息截断到列宽、不在此层主动写敏感值（admin-only 日志）。
"""

from __future__ import annotations

import asyncio
import os
import re
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import DBAPIError, IntegrityError

from admin_platform.db.locks import (
    acquire_transaction_lock,
    app_lock_name,
    ensure_transaction_lock_row,
)
from admin_platform.db.session import db_session
from admin_platform.domains.scheduled_task.cron import CronValidationError, scheduled_tick_at
from admin_platform.domains.scheduled_task.models import ScheduledTaskLog
from admin_platform.domains.scheduled_task.registry import JobHandlerRegistry
from admin_platform.domains.scheduled_task.repository import ScheduledTaskRepository

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
_ERR_MSG_MAX = 1024
_SUMMARY_MAX = 1024
# 孤儿 running 兜底：无 timeout_seconds 的任务，超过此秒数的 running 视为崩溃遗留、不计入并发判定。
_DEFAULT_STALE_SECONDS = 3600
# manual 手动触发经同步 HTTP 执行，长占请求连接/事务（schedule 后台触发不占）：manual 路径强制
# 兜底超时上限，最长 5min；task.timeout_seconds=None（不设）时也兜底，schedule 仍用任务级值（可至 86400）。
_MANUAL_RUN_MAX_TIMEOUT = 300
_SCHEDULED_TASK_CLAIM_LOCK_NAMESPACE = "scheduled-task:claim"
# claim 去重生成列唯一索引名（须与 models.ScheduledTaskLog 的 Index 名一致）：
# 只有撞它才算「被其他 worker 抢占」，其它 IntegrityError 上抛（不静默吞）。
_CLAIM_UNIQUE_INDEX = "uq_scheduled_task_logs_schedule_claim"
_MYSQL_DEADLOCK = 1213
_MYSQL_DUPLICATE = 1062
_CLAIM_LOCK_RETRY_LIMIT = 3
_CLAIM_LOCK_RETRY_BACKOFF_SECONDS = 0.02

# F6：执行日志脱敏兜底——error_message / result_summary 可能含 handler 异常里的连接串/密钥
# （admin-only 日志，但 handler registry 是扩展点，纵深防御屏蔽常见敏感模式胜过裸写）。
_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|pwd|token|secret|api[_-]?key|authorization)\s*[=:]\s*\S+"
    r"|[a-z][a-z0-9+.-]*://[^:/\s]+:[^@\s]+@"  # 连接串 scheme://user:pass@host
)


def _redact(text: str) -> str:
    """屏蔽常见敏感模式（key=value / key:value 形式的密钥 + URL 内嵌凭据）。"""
    return _SECRET_PATTERN.sub("***REDACTED***", text)


def _mysql_error_code(exc: BaseException) -> int | None:
    orig = getattr(exc, "orig", None)
    for candidate in (orig, exc):
        args = getattr(candidate, "args", ())
        if args and isinstance(args[0], int):
            return int(args[0])
    return None


def _is_claim_taken(exc: IntegrityError) -> bool:
    """IntegrityError 是否为 schedule claim 生成列唯一索引冲突（被其他 worker 抢占 → 跳过）。

    先确认 MySQL 1062 duplicate-entry 错误码，再匹配 claim 索引名（codex 对抗审查 #4 + 第二轮）：
    execution_id unique 也是 1062 但 key 名不同 → 被第二段挡下；CHECK/FK 等非 1062 → 第一段直接
    False。两段都不命中即真实约束错误，必须上抛，不能伪装成「被抢占」掩盖数据/程序错误。
    """
    if _mysql_error_code(exc) != _MYSQL_DUPLICATE:
        return False
    return _CLAIM_UNIQUE_INDEX in str(exc.orig)


def _as_utc_aware(value: datetime) -> datetime:
    """MySQL DATETIME 经 aiomysql 读回为 naive；本仓约定其语义是 UTC。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_utc_for_storage(value: datetime) -> datetime:
    """写入库前统一成 UTC；MySQL DATETIME 不保存 timezone 信息。"""
    return _as_utc_aware(value)


@dataclass(frozen=True)
class ExecutionOutcome:
    """一次执行的结果（供手动触发回读 / 调度日志）。``log_id=None`` = 被其他 worker 抢占跳过。"""

    execution_id: uuid.UUID | None
    status: str  # running 之后的终态：success/failure/skipped，或 None claim 被抢占
    log_id: int | None


class TaskExecutor:
    def __init__(self, registry: JobHandlerRegistry) -> None:
        self._registry = registry

    async def run(
        self,
        task_id: int,
        *,
        trigger_type: str,
        scheduled_at: datetime | None,
        actor_user_id: int | None,
    ) -> ExecutionOutcome | None:
        """执行一次任务。task 不存在（调度后被删）→ None；claim 被抢占 → None。"""
        execution_id = uuid.uuid4()
        claim = await self._claim(
            task_id,
            trigger_type=trigger_type,
            scheduled_at=scheduled_at,
            actor_user_id=actor_user_id,
            execution_id=execution_id,
        )
        if claim is None:
            return None
        log_id, handler_key, params, timeout_seconds, skipped = claim
        if skipped:
            return ExecutionOutcome(execution_id=execution_id, status="skipped", log_id=log_id)

        # manual 触发同步占 HTTP 连接/请求事务 → 施加兜底上限（最长 5min）；schedule 后台触发
        # 不占连接，沿用任务级 timeout_seconds。
        effective_timeout = timeout_seconds
        if trigger_type == "manual":
            effective_timeout = min(
                timeout_seconds or _MANUAL_RUN_MAX_TIMEOUT, _MANUAL_RUN_MAX_TIMEOUT
            )
        status, error_code, error_message, result_summary = await self._invoke(
            handler_key, params, effective_timeout
        )
        await self._finish(log_id, task_id, status, error_code, error_message, result_summary)
        return ExecutionOutcome(execution_id=execution_id, status=status, log_id=log_id)

    async def _claim(
        self,
        task_id: int,
        *,
        trigger_type: str,
        scheduled_at: datetime | None,
        actor_user_id: int | None,
        execution_id: uuid.UUID,
    ) -> tuple[int, str, dict, int | None, bool] | None:
        """claim session：建日志。返回 (log_id, handler_key, params, timeout, skipped) 或 None。

        None = 任务已删 / schedule claim 被其他 worker 抢占（生成列唯一索引冲突）。
        skipped=True = allow_concurrent=False 且已有 running（记 skipped 日志，不执行）。
        """
        await ensure_transaction_lock_row(
            app_lock_name(_SCHEDULED_TASK_CLAIM_LOCK_NAMESPACE, task_id)
        )
        for attempt in range(_CLAIM_LOCK_RETRY_LIMIT):
            try:
                return await self._claim_once(
                    task_id,
                    trigger_type=trigger_type,
                    scheduled_at=scheduled_at,
                    actor_user_id=actor_user_id,
                    execution_id=execution_id,
                )
            except DBAPIError as exc:
                if (
                    _mysql_error_code(exc) != _MYSQL_DEADLOCK
                    or attempt == _CLAIM_LOCK_RETRY_LIMIT - 1
                ):
                    raise
                await asyncio.sleep(_CLAIM_LOCK_RETRY_BACKOFF_SECONDS * (2**attempt))
        return None

    async def _claim_once(
        self,
        task_id: int,
        *,
        trigger_type: str,
        scheduled_at: datetime | None,
        actor_user_id: int | None,
        execution_id: uuid.UUID,
    ) -> tuple[int, str, dict, int | None, bool] | None:
        """单次 claim 事务；MySQL 1213 由外层重开事务重试。"""
        try:
            async with db_session() as session:
                repo = ScheduledTaskRepository(session)
                # app_locks sentinel 按 task_id 粒度串行化 claim 临界区，避免照搬阶段 0 PoC 的全局锁
                # 导致不同任务互相阻塞。随后再 FOR UPDATE 锁任务行，保留任务删除/更新的行级一致性。
                await acquire_transaction_lock(
                    session, app_lock_name(_SCHEDULED_TASK_CLAIM_LOCK_NAMESPACE, task_id)
                )
                # FOR UPDATE 锁任务行：串行化同一任务的并发触发（含 manual，无生成列唯一索引兜底），
                # 把 count_running 检查 + claim INSERT 收进同一行锁临界区，消除 TOCTOU。
                task = await repo.get_for_update(task_id)
                if task is None:
                    return None
                # H3：schedule 触发的 claim 键取 cron 计划 tick（非触发墙钟分钟）——failover 跨分钟界 /
                # misfire 延迟下同一逻辑 tick 键值恒定，去重正确。manual 触发 scheduled_at 恒 None。
                if trigger_type == "schedule" and scheduled_at is None:
                    now_ = datetime.now(UTC)
                    try:
                        tick = scheduled_tick_at(
                            task.cron_expression,
                            timezone=task.cron_timezone,
                            now=now_,
                            lookback_seconds=task.misfire_grace_seconds + 60,
                        )
                    except CronValidationError:
                        tick = None  # 防御：cron 被并发改非法（reconcile 已挡，几不可达）→ 墙钟兜底
                    scheduled_at = _as_utc_for_storage(
                        tick or now_.replace(second=0, microsecond=0)
                    )
                stale_seconds = task.timeout_seconds or _DEFAULT_STALE_SECONDS
                since = datetime.now(UTC) - timedelta(seconds=stale_seconds)
                concurrency_skip = (
                    not task.allow_concurrent and await repo.count_running(task_id, since=since) > 0
                )
                log = ScheduledTaskLog(
                    task_id=task_id,
                    execution_id=execution_id,
                    trigger_type=trigger_type,
                    scheduled_at=scheduled_at,
                    handler_key=task.handler_key,
                    params_json=dict(task.params_json),
                    status="skipped" if concurrency_skip else "running",
                    started_at=None if concurrency_skip else datetime.now(UTC),
                    finished_at=datetime.now(UTC) if concurrency_skip else None,
                    worker_id=WORKER_ID,
                    actor_user_id=actor_user_id,
                )
                await repo.create_log(log)
                return (
                    log.id,
                    task.handler_key,
                    dict(task.params_json),
                    task.timeout_seconds,
                    concurrency_skip,
                )
        except IntegrityError as exc:
            # 只把 claim 生成列唯一索引的 1062 冲突当作「被其他 worker 抢占」→ 跳过；execution_id
            # unique / CHECK / FK 等真实约束错误必须上抛（详见 _is_claim_taken）。
            if _is_claim_taken(exc):
                return None
            raise

    async def _invoke(
        self, handler_key: str, params: dict, timeout_seconds: int | None
    ) -> tuple[str, str | None, str | None, str | None]:
        """事务外执行 handler。返回 (status, error_code, error_message, result_summary)。"""
        spec = self._registry.get(handler_key)
        if spec is None:
            return (
                "failure",
                "scheduled_task.HANDLER_NOT_REGISTERED",
                f"handler 已下线: {handler_key}",
                None,
            )
        try:
            coro = spec.handler(params)
            summary = (
                await asyncio.wait_for(coro, timeout=timeout_seconds)
                if timeout_seconds is not None
                else await coro
            )
        except TimeoutError:
            return "failure", "scheduled_task.TIMEOUT", f"执行超时(> {timeout_seconds}s)", None
        except Exception as exc:
            # F6：脱敏兜底——handler 异常文本可能含连接串/密钥（纵深防御，不裸写入库）。
            return "failure", type(exc).__name__, _redact(str(exc))[:_ERR_MSG_MAX], None
        return "success", None, None, (_redact(summary)[:_SUMMARY_MAX] if summary else None)

    async def _finish(  # noqa: PLR0913 —— 执行终态字段多且全显式传，内部 helper 可放宽
        self,
        log_id: int,
        task_id: int,
        status: str,
        error_code: str | None,
        error_message: str | None,
        result_summary: str | None,
    ) -> None:
        """result session：写回日志终态 + 任务 last_run。"""
        now = datetime.now(UTC)
        async with db_session() as session:
            repo = ScheduledTaskRepository(session)
            log = await repo.get_log(log_id)
            if log is not None:
                log.status = status
                log.finished_at = now
                log.error_code = error_code
                log.error_message = error_message
                log.result_summary = result_summary
                if log.started_at is not None:
                    log.duration_ms = int(
                        (now - _as_utc_aware(log.started_at)).total_seconds() * 1000
                    )
            task = await repo.get(task_id)
            if task is not None:
                await repo.mark_task_last_run(task, status=status, when=now)
