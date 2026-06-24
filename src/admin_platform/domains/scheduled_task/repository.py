"""定时任务数据访问 —— scheduled_tasks + scheduled_task_logs（SQLAlchemy 2.x async）。

返回 ORM 行 / None / 计数，不抛业务异常（业务判定在 service）。执行 claim 的唯一约束冲突
（生成列唯一索引）以 ``IntegrityError`` 上抛，由 executor 判为「已被其他 worker 抢占 → 跳过」。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin_platform.domains.scheduled_task.models import ScheduledTask, ScheduledTaskLog


class ScheduledTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- 任务 CRUD ----

    async def create(self, task: ScheduledTask) -> ScheduledTask:
        self._session.add(task)
        await self._session.flush()
        return task

    async def get(self, task_id: int) -> ScheduledTask | None:
        return await self._session.get(ScheduledTask, task_id)

    async def get_for_update(self, task_id: int) -> ScheduledTask | None:
        """``SELECT ... FOR UPDATE`` 锁任务行——执行 claim 用，串行化同一任务的并发触发
        （manual 触发无生成列唯一索引兜底，靠此行锁消除 count_running↔INSERT 的 TOCTOU）。"""
        stmt = select(ScheduledTask).where(ScheduledTask.id == task_id).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def refresh(self, task: ScheduledTask) -> None:
        """重载 server 端列（UPDATE 后 onupdate 的 updated_at 被 expire，model_validate 前需 refresh，
        否则 async 下同步访问触发 MissingGreenlet）。"""
        await self._session.refresh(task)

    async def get_by_name(self, name: str) -> ScheduledTask | None:
        return await self._session.scalar(select(ScheduledTask).where(ScheduledTask.name == name))

    def _task_filtered(
        self, *, status: str | None, handler_key: str | None
    ) -> Select[tuple[ScheduledTask]]:
        stmt = select(ScheduledTask)
        if status is not None:
            stmt = stmt.where(ScheduledTask.status == status)
        if handler_key is not None:
            stmt = stmt.where(ScheduledTask.handler_key == handler_key)
        return stmt

    async def list(
        self, *, status: str | None, handler_key: str | None, page: int, size: int
    ) -> list[ScheduledTask]:
        stmt = (
            self._task_filtered(status=status, handler_key=handler_key)
            .order_by(ScheduledTask.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count(self, *, status: str | None, handler_key: str | None) -> int:
        inner = self._task_filtered(status=status, handler_key=handler_key).subquery()
        return int(
            (await self._session.execute(select(func.count()).select_from(inner))).scalar_one()
        )

    async def list_enabled(self) -> list[ScheduledTask]:
        """调度器装载用：所有 enabled 任务。"""
        stmt = select(ScheduledTask).where(ScheduledTask.status == "enabled")
        return list((await self._session.execute(stmt)).scalars().all())

    async def delete(self, task: ScheduledTask) -> None:
        await self._session.delete(task)
        await self._session.flush()

    # ---- 执行日志 ----

    async def create_log(self, log: ScheduledTaskLog) -> ScheduledTaskLog:
        """新建执行日志。schedule claim 撞生成列唯一索引 → IntegrityError（executor 判跳过）。"""
        self._session.add(log)
        await self._session.flush()
        return log

    async def count_running(self, task_id: int, *, since: datetime) -> int:
        """该任务**新近** running 的执行数（allow_concurrent=false 的并发判定）。

        ``since`` 过滤掉「崩溃遗留的孤儿 running」（_finish 前进程死）——否则孤儿会让该任务
        之后所有自动触发被永久 skip（任务调度被冻死）。只计 ``started_at >= since`` 的活跃执行。
        """
        stmt = select(func.count()).where(
            ScheduledTaskLog.task_id == task_id,
            ScheduledTaskLog.status == "running",
            ScheduledTaskLog.started_at >= since,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def get_log(self, log_id: int) -> ScheduledTaskLog | None:
        return await self._session.get(ScheduledTaskLog, log_id)

    async def get_log_by_execution_id(self, execution_id: uuid.UUID) -> ScheduledTaskLog | None:
        return await self._session.scalar(
            select(ScheduledTaskLog).where(ScheduledTaskLog.execution_id == execution_id)
        )

    def _log_filtered(
        self, *, task_id: int | None, status: str | None
    ) -> Select[tuple[ScheduledTaskLog]]:
        stmt = select(ScheduledTaskLog)
        if task_id is not None:
            stmt = stmt.where(ScheduledTaskLog.task_id == task_id)
        if status is not None:
            stmt = stmt.where(ScheduledTaskLog.status == status)
        return stmt

    async def list_logs(
        self, *, task_id: int | None, status: str | None, page: int, size: int
    ) -> list[ScheduledTaskLog]:
        stmt = (
            self._log_filtered(task_id=task_id, status=status)
            .order_by(ScheduledTaskLog.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_logs(self, *, task_id: int | None, status: str | None) -> int:
        inner = self._log_filtered(task_id=task_id, status=status).subquery()
        return int(
            (await self._session.execute(select(func.count()).select_from(inner))).scalar_one()
        )

    async def mark_task_last_run(self, task: ScheduledTask, *, status: str, when: datetime) -> None:
        task.last_run_at = when
        task.last_status = status
        await self._session.flush()
