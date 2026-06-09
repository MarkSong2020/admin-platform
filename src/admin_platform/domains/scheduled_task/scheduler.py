"""定时任务调度器控制器（P4c）—— leader election + AsyncIOScheduler 生命周期。

**多 worker 安全（roadmap P4 红线，Codex PK §2）**：
- 进程级 leader：每个 worker 起一条专用连接 ``pg_try_advisory_lock(leader_key)``，**仅抢到锁的
  worker** 起 AsyncIOScheduler 触发 cron；非 leader 周期重试夺锁（leader 进程死 → 连接断 → 锁释放
  → standby 接管）。
- 任务级 claim：``scheduled_task_logs`` 的 ``(task_id, scheduled_at)`` partial unique（见 0016
  迁移）兜 failover 窗口——即便新旧 leader 短暂同时触发同一分钟 tick，也只有一条 INSERT 成功。

调度器只注册一个 wrapper ``_fire``（逻辑全在 executor + DB + registry），**不用 SQLAlchemyJobStore**
（序列化 callable 与「无任意调用目标」安全模型冲突，也不解决多 worker）。``scheduler_enabled``
默认 False：本地/CI/单测不起调度器，CRUD + 手动触发不依赖它。

优雅 drain：stop 时按 ``scheduler_shutdown_grace_seconds`` 等 in-flight ``_fire`` 跑完。孤儿兜底：
``count_running`` 用 stale 阈值过滤崩溃遗留的 ``running``（见 executor），不让其永久冻结任务调度。
⚠️ 已知排期（Codex 风险 #6）：硬 kill（SIGKILL）仍可能留 ``running`` 孤儿日志（仅状态不准，靠
stale 过滤不影响调度）；显式启动恢复（把超期 running 标 abandoned）留后续，见 spec §4 非目标。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from admin_platform.core.config import Settings
from admin_platform.db.engine import get_engine
from admin_platform.db.session import db_session
from admin_platform.domains.scheduled_task.cron import CronValidationError, build_cron_trigger
from admin_platform.domains.scheduled_task.executor import WORKER_ID, TaskExecutor
from admin_platform.domains.scheduled_task.registry import JobHandlerRegistry
from admin_platform.domains.scheduled_task.repository import ScheduledTaskRepository

_log = logging.getLogger("admin_platform.scheduler")


class SchedulerController:
    def __init__(self, settings: Settings, registry: JobHandlerRegistry) -> None:
        self._settings = settings
        self._registry = registry
        self._executor = TaskExecutor(registry)
        self._scheduler: AsyncIOScheduler | None = None
        self._leader_conn: AsyncConnection | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._inflight: set[asyncio.Task[None]] = set()  # 正在跑的 _fire（关闭时优雅 drain）
        self._is_leader = False

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    async def start(self) -> None:
        """lifespan startup 调用。未启用直接返回；启用则尝试夺 leader + 起后台 reconcile/重试 loop。"""
        if not self._settings.scheduler_enabled:
            return
        await self._try_acquire_leader()
        self._loop_task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        # 单次 reconcile/夺锁抛错绝不能让 loop 死掉——否则 leader 持锁却停止调度（僵尸 leader，
        # 别的 worker 永远抢不到），或非 leader 永久不再夺锁。捕获 + 记录 + 下周期重试。
        while True:
            await asyncio.sleep(self._settings.scheduler_poll_seconds)
            try:
                if self._is_leader:
                    await self._reconcile()
                else:
                    await self._try_acquire_leader()
            except Exception:
                _log.exception("scheduler loop 周期出错，下周期重试")

    async def _try_acquire_leader(self) -> bool:
        """尝试夺 leader 锁。成功 → 起 scheduler + 装载任务。专用连接持到 stop（断开即释放锁）。"""
        if self._is_leader:
            return True
        conn = await get_engine().connect()
        try:
            got = (
                await conn.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": self._settings.scheduler_leader_lock_key},
                )
            ).scalar()
        except Exception:
            await conn.close()  # 拿锁查询出错也要回收连接，否则反复重试会耗尽 pool
            raise
        if not got:
            await conn.close()
            return False
        self._leader_conn = conn
        self._is_leader = True
        scheduler = AsyncIOScheduler(timezone=ZoneInfo(self._settings.scheduler_timezone))
        scheduler.start()
        self._scheduler = scheduler
        await self._reconcile()
        _log.info("scheduler 成为 leader (worker=%s)", WORKER_ID)
        return True

    async def _reconcile(self) -> None:
        """同步 scheduler 作业 ↔ DB enabled 任务：删已禁用/删除的，增/改启用的。"""
        if self._scheduler is None:
            return
        async with db_session() as session:
            tasks = await ScheduledTaskRepository(session).list_enabled()
        desired = {str(t.id): t for t in tasks}
        for job in self._scheduler.get_jobs():
            if job.id not in desired:
                self._scheduler.remove_job(job.id)
        for job_id, task in desired.items():
            try:
                trigger = build_cron_trigger(task.cron_expression, timezone=task.cron_timezone)
            except CronValidationError:
                _log.warning("task %s cron 非法，跳过调度: %s", task.id, task.cron_expression)
                continue
            self._scheduler.add_job(
                self._fire,
                trigger=trigger,
                id=job_id,
                args=[task.id],
                replace_existing=True,
                max_instances=1,
                coalesce=False,
                misfire_grace_time=task.misfire_grace_seconds,
            )

    async def _fire(self, task_id: int) -> None:
        """cron 触发 wrapper。scheduled_at 截断到分钟（cron 最小粒度）→ failover 同 tick 同值 →
        claim partial unique 去重。登记到 in-flight 供 stop 优雅 drain。"""
        task = asyncio.current_task()
        if task is not None:
            self._inflight.add(task)
        try:
            scheduled_at = datetime.now(UTC).replace(second=0, microsecond=0)
            await self._executor.run(
                task_id, trigger_type="schedule", scheduled_at=scheduled_at, actor_user_id=None
            )
        finally:
            if task is not None:
                self._inflight.discard(task)

    async def stop(self) -> None:
        """lifespan shutdown 调用。停 loop + scheduler，释放 leader 锁。"""
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
        if self._scheduler is not None:
            # wait=False：不阻塞事件循环；停止接收新触发。in-flight _fire 下面按 grace 优雅 drain。
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        # 优雅 drain：给正在跑的 _fire 至多 grace 秒跑完（超时则放手，靠 stale 兜底不冻任务）。
        if self._inflight:
            await asyncio.wait(
                self._inflight, timeout=self._settings.scheduler_shutdown_grace_seconds
            )
            self._inflight.clear()
        if self._leader_conn is not None:
            try:
                await self._leader_conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": self._settings.scheduler_leader_lock_key},
                )
            finally:
                await self._leader_conn.close()
            self._leader_conn = None
        self._is_leader = False
