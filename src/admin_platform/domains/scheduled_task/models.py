"""定时任务 ORM 映射 — ``scheduled_tasks``（任务定义）+ ``scheduled_task_logs``（执行日志）。

对标 RuoYi sys_job / sys_job_log。安全模型（Codex PK §3）：任务只存 ``handler_key``（代码侧
预注册 registry 的键）+ ``params_json``，**不存任意调用目标字符串**（无 RCE 面）。

多 worker 安全（roadmap P4 红线）：自动触发的执行 claim 用 ``scheduled_task_logs`` 上
``(task_id, scheduled_at) WHERE trigger_type='schedule'`` 的 **partial unique index** 兜底——
即使 leader failover 窗口两个 worker 同时触发同一 cron tick，也只有一条 INSERT 成功，另一条
撞唯一约束被跳过。leader election（advisory lock）是效率层，此约束是正确性层。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.core.errors import register_unique_constraint
from admin_platform.db.base import Base, IdMixin, TimestampMixin


class ScheduledTask(Base, IdMixin, TimestampMixin):
    """定时任务定义。``handler_key`` 必须命中代码侧 registry，``cron_expression`` 经校验。"""

    __tablename__ = "scheduled_tasks"

    __table_args__ = (
        UniqueConstraint("name", name="uq_scheduled_tasks_name"),
        CheckConstraint("status IN ('enabled', 'disabled')", name="ck_scheduled_tasks_status"),
        CheckConstraint("misfire_grace_seconds >= 0", name="ck_scheduled_tasks_misfire_nonneg"),
        Index("ix_scheduled_tasks_status", "status"),
        Index("ix_scheduled_tasks_handler_key", "handler_key"),
    )

    name: Mapped[str] = mapped_column(String(128), comment="任务名称(唯一)")
    handler_key: Mapped[str] = mapped_column(
        String(128), comment="处理器键(命中代码侧registry,非任意调用目标)"
    )
    params_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="处理器参数(JSON)"
    )
    cron_expression: Mapped[str] = mapped_column(
        String(128), comment="cron表达式(5字段标准crontab,经校验)"
    )
    cron_timezone: Mapped[str] = mapped_column(
        String(64), server_default=text("'Asia/Shanghai'"), comment="cron解释时区(库时间存UTC)"
    )
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'disabled'"), comment="状态(enabled/disabled)"
    )
    allow_concurrent: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), comment="是否允许上次未跑完时并发执行"
    )
    misfire_grace_seconds: Mapped[int] = mapped_column(
        Integer, server_default=text("300"), comment="错过触发的宽限秒数"
    )
    timeout_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="单次执行超时秒数(空=不限)"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次执行时刻(UTC)"
    )
    last_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="最近一次执行结果状态"
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")


class ScheduledTaskLog(Base, IdMixin, TimestampMixin):
    """单次执行日志。append + 状态推进（waiting→running→success/failure）。任务删除后保留(FK SET NULL)。"""

    __tablename__ = "scheduled_task_logs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting', 'running', 'success', 'failure', 'misfire', 'skipped')",
            name="ck_scheduled_task_logs_status",
        ),
        CheckConstraint(
            "trigger_type IN ('schedule', 'manual')", name="ck_scheduled_task_logs_trigger"
        ),
        # L：schedule 触发必须有 scheduled_at（claim 正确性层兜底）——否则 partial unique 在 PG16
        # NULLS DISTINCT 下对 schedule+NULL 行完全失效，去重被静默旁路（防未来代码/手写 SQL/回放工具
        # 以 schedule+NULL 插入绕过红线）。manual 触发 scheduled_at 合法为 NULL，不受此约束。
        CheckConstraint(
            "trigger_type <> 'schedule' OR scheduled_at IS NOT NULL",
            name="ck_scheduled_task_logs_schedule_at",
        ),
        # 多 worker 执行 claim（P4 红线核心）：同一任务同一 cron tick 只能有一条自动触发记录。
        Index(
            "uq_scheduled_task_logs_schedule_claim",
            "task_id",
            "scheduled_at",
            unique=True,
            postgresql_where=text("trigger_type = 'schedule'"),
        ),
        Index("ix_scheduled_task_logs_task_started", "task_id", "started_at"),
        Index("ix_scheduled_task_logs_status_created", "status", "created_at"),
    )

    task_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("scheduled_tasks.id", ondelete="SET NULL"),
        nullable=True,
        comment="所属任务ID(任务删后置空,保留历史)",
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, comment="执行唯一标识(UUID)")
    trigger_type: Mapped[str] = mapped_column(
        String(16), comment="触发方式(schedule自动/manual手动)"
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划触发时刻(UTC,自动触发用于claim去重)"
    )
    handler_key: Mapped[str] = mapped_column(String(128), comment="处理器键(快照)")
    params_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="执行参数快照(JSON)"
    )
    status: Mapped[str] = mapped_column(String(16), comment="执行状态")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="开始执行时刻(UTC)"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="结束时刻(UTC)"
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="执行耗时(毫秒)"
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="失败错误码")
    error_message: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="失败信息(截断,禁写密钥)"
    )
    result_summary: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="成功结果摘要"
    )
    worker_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="执行所在worker标识"
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="手动触发操作者用户ID"
    )


# 竞态撞任务名唯一约束（两并发 create 都过 service 预检）→ IntegrityError handler 翻 409。
register_unique_constraint(
    "uq_scheduled_tasks_name", "scheduled_task.NAME_DUPLICATE", "任务名称已存在"
)
