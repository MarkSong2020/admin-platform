"""定时任务 service —— CRUD + 手动触发编排 + registry/cron 强校验。

安全核心（P4c §3）：create/update/manual_run 必须 ``registry.get(handler_key)`` 命中 + params 过
handler schema，否则 422——任务永远绑到代码侧预注册 handler，无任意调用目标。cron 经 ``validate_cron``
（校验器 = 调度构造器，校验通过即能调度）。手动触发委托 executor（两段 session，事务外跑 handler）。

分层：不 import fastapi、不抛 HTTPException —— 用 ``AppError``。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from admin_platform.core.errors import AppError
from admin_platform.core.pagination import compute_total_pages
from admin_platform.domains.scheduled_task.cron import (
    CronValidationError,
    next_run_after,
    validate_cron,
)
from admin_platform.domains.scheduled_task.executor import TaskExecutor
from admin_platform.domains.scheduled_task.models import ScheduledTask
from admin_platform.domains.scheduled_task.registry import HandlerParamsError, JobHandlerRegistry
from admin_platform.domains.scheduled_task.repository import ScheduledTaskRepository
from admin_platform.domains.scheduled_task.schemas import (
    HandlerInfo,
    ScheduledTaskCreate,
    ScheduledTaskLogPage,
    ScheduledTaskLogRead,
    ScheduledTaskPage,
    ScheduledTaskRead,
    ScheduledTaskUpdate,
)

_NOT_FOUND = "scheduled_task.NOT_FOUND"
_NAME_DUPLICATE = "scheduled_task.NAME_DUPLICATE"
_HANDLER_UNKNOWN = "scheduled_task.HANDLER_UNKNOWN"
_PARAMS_INVALID = "scheduled_task.PARAMS_INVALID"
_CRON_INVALID = "scheduled_task.CRON_INVALID"
_MANUAL_NOT_ALLOWED = "scheduled_task.MANUAL_NOT_ALLOWED"
_LOG_NOT_FOUND = "scheduled_task.LOG_NOT_FOUND"
# M10：manual_run 专属冲突码（type↔status 一对一）——区别 create/update 的 422 HANDLER_UNKNOWN /
# get 的 404 NOT_FOUND，避免同一 type 映射两种 HTTP 状态破坏 SDK 类型化错误契约。
_HANDLER_OFFLINE = "scheduled_task.HANDLER_OFFLINE"  # handler 运行期下线（409，非 422 未注册）
_RUN_CONFLICT = "scheduled_task.RUN_CONFLICT"  # 执行期 task 被删/claim 抢占（409，非 404 不存在）


class ScheduledTaskService:
    def __init__(
        self,
        repo: ScheduledTaskRepository,
        registry: JobHandlerRegistry,
        executor: TaskExecutor,
    ) -> None:
        self._repo = repo
        self._registry = registry
        self._executor = executor

    # ---- 校验 helper ----

    def _require_handler(self, handler_key: str) -> None:
        if self._registry.get(handler_key) is None:
            raise AppError(
                code=_HANDLER_UNKNOWN,
                title="Unknown handler",
                detail=f"handler_key 未注册: {handler_key}（可选：{self._registry.keys()}）",
                status_code=422,
            )

    def _validate_params(self, handler_key: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._registry.validate_params(handler_key, params)
        except HandlerParamsError as exc:
            raise AppError(
                code=_PARAMS_INVALID, title="Invalid params", detail=str(exc), status_code=422
            ) from exc

    def _validate_cron(self, expr: str, timezone: str) -> None:
        try:
            validate_cron(expr, timezone=timezone)
        except CronValidationError as exc:
            raise AppError(
                code=_CRON_INVALID, title="Invalid cron", detail=str(exc), status_code=422
            ) from exc

    def _to_read(self, task: ScheduledTask, *, with_next_run: bool = False) -> ScheduledTaskRead:
        read = ScheduledTaskRead.model_validate(task)
        # next_run 仅在单条（详情/create/update）算：list 批量算会被「合法但永不触发」的 cron
        # （如 2月30日）放大成事件循环阻塞（APScheduler 对此类做 ~4 年 lookahead）。
        if with_next_run and task.status == "enabled":
            try:
                nxt = next_run_after(
                    task.cron_expression, timezone=task.cron_timezone, now=datetime.now(UTC)
                )
                read.next_run_at = nxt.astimezone(UTC) if nxt is not None else None
            except CronValidationError:
                read.next_run_at = None
        return read

    # ---- registry ----

    def list_handlers(self) -> list[HandlerInfo]:
        return [
            HandlerInfo(key=s.key, display_name=s.display_name, allow_manual=s.allow_manual)
            for s in self._registry.specs()
        ]

    # ---- CRUD ----

    async def list_tasks(
        self, *, status: str | None, handler_key: str | None, page: int, size: int
    ) -> ScheduledTaskPage:
        rows = await self._repo.list(status=status, handler_key=handler_key, page=page, size=size)
        total = await self._repo.count(status=status, handler_key=handler_key)
        return ScheduledTaskPage(
            items=[self._to_read(r) for r in rows],
            page=page,
            size=size,
            total=total,
            total_pages=compute_total_pages(total, size),
        )

    async def get_task(self, task_id: int) -> ScheduledTaskRead:
        task = await self._repo.get(task_id)
        if task is None:
            raise AppError(code=_NOT_FOUND, title="Task not found", status_code=404)
        return self._to_read(task, with_next_run=True)

    async def create(self, payload: ScheduledTaskCreate) -> ScheduledTaskRead:
        self._require_handler(payload.handler_key)
        params = self._validate_params(payload.handler_key, payload.params)
        self._validate_cron(payload.cron_expression, payload.cron_timezone)
        if await self._repo.get_by_name(payload.name) is not None:
            raise AppError(code=_NAME_DUPLICATE, title="Name exists", status_code=409)
        task = ScheduledTask(
            name=payload.name,
            handler_key=payload.handler_key,
            params_json=params,
            cron_expression=payload.cron_expression,
            cron_timezone=payload.cron_timezone,
            status=payload.status,
            allow_concurrent=payload.allow_concurrent,
            misfire_grace_seconds=payload.misfire_grace_seconds,
            timeout_seconds=payload.timeout_seconds,
            remark=payload.remark,
        )
        await self._repo.create(task)
        return self._to_read(task, with_next_run=True)

    async def update(self, task_id: int, payload: ScheduledTaskUpdate) -> ScheduledTaskRead:
        task = await self._repo.get(task_id)
        if task is None:
            raise AppError(code=_NOT_FOUND, title="Task not found", status_code=404)

        # handler/params 任一变更 → 用「合并后」的有效值重校验。
        eff_handler = payload.handler_key if payload.handler_key is not None else task.handler_key
        if payload.handler_key is not None or payload.params is not None:
            self._require_handler(eff_handler)
            eff_params = payload.params if payload.params is not None else task.params_json
            task.params_json = self._validate_params(eff_handler, eff_params)
            task.handler_key = eff_handler

        # cron/timezone 任一变更 → 用合并后的有效值重校验。
        if payload.cron_expression is not None or payload.cron_timezone is not None:
            eff_cron = (
                payload.cron_expression
                if payload.cron_expression is not None
                else task.cron_expression
            )
            eff_tz = (
                payload.cron_timezone if payload.cron_timezone is not None else task.cron_timezone
            )
            self._validate_cron(eff_cron, eff_tz)
            task.cron_expression = eff_cron
            task.cron_timezone = eff_tz

        if payload.name is not None and payload.name != task.name:
            if await self._repo.get_by_name(payload.name) is not None:
                raise AppError(code=_NAME_DUPLICATE, title="Name exists", status_code=409)
            task.name = payload.name

        if payload.status is not None:
            task.status = payload.status
        if payload.allow_concurrent is not None:
            task.allow_concurrent = payload.allow_concurrent
        if payload.misfire_grace_seconds is not None:
            task.misfire_grace_seconds = payload.misfire_grace_seconds
        # timeout_seconds / remark 是 nullable 列（None = 不限时 / 无备注）：用 model_fields_set 区分
        # 「显式传 null（清空）」与「未传（不动）」——PATCH 语义，传了就改。其余字段（name/handler/cron/
        # status/allow_concurrent/misfire/params）对应 NOT NULL 列，沿用 is not None 忽略显式 null
        # （不可清空成 NULL）。
        if "timeout_seconds" in payload.model_fields_set:
            task.timeout_seconds = payload.timeout_seconds
        if "remark" in payload.model_fields_set:
            task.remark = payload.remark

        await self._repo.create(task)  # flush
        await self._repo.refresh(
            task
        )  # 重载 onupdate 的 updated_at（防 model_validate MissingGreenlet）
        return self._to_read(task, with_next_run=True)

    async def delete(self, task_id: int) -> None:
        task = await self._repo.get(task_id)
        if task is None:
            raise AppError(code=_NOT_FOUND, title="Task not found", status_code=404)
        await self._repo.delete(task)

    # ---- 执行日志 ----

    async def list_logs(
        self, *, task_id: int | None, status: str | None, page: int, size: int
    ) -> ScheduledTaskLogPage:
        rows = await self._repo.list_logs(task_id=task_id, status=status, page=page, size=size)
        total = await self._repo.count_logs(task_id=task_id, status=status)
        return ScheduledTaskLogPage(
            items=[ScheduledTaskLogRead.model_validate(r) for r in rows],
            page=page,
            size=size,
            total=total,
            total_pages=compute_total_pages(total, size),
        )

    # ---- 手动触发 ----

    async def manual_run(self, task_id: int, *, actor_user_id: int | None) -> ScheduledTaskLogRead:
        """手动触发一次：校验 → executor 执行（事务外）→ 回读执行日志返回。

        handler 已下线 / 不允许手动 → 409。允许触发 disabled 任务（admin 显式 test-run）。
        """
        task = await self._repo.get(task_id)
        if task is None:
            raise AppError(code=_NOT_FOUND, title="Task not found", status_code=404)
        spec = self._registry.get(task.handler_key)
        if spec is None:
            raise AppError(code=_HANDLER_OFFLINE, title="Handler offline", status_code=409)
        if not spec.allow_manual:
            raise AppError(
                code=_MANUAL_NOT_ALLOWED, title="Manual trigger not allowed", status_code=409
            )
        outcome = await self._executor.run(
            task_id, trigger_type="manual", scheduled_at=None, actor_user_id=actor_user_id
        )
        if outcome is None or outcome.log_id is None:
            raise AppError(code=_RUN_CONFLICT, title="Task vanished during run", status_code=409)
        log = await self._repo.get_log(outcome.log_id)
        if log is None:
            raise AppError(code=_LOG_NOT_FOUND, title="Execution log not found", status_code=404)
        return ScheduledTaskLogRead.model_validate(log)
