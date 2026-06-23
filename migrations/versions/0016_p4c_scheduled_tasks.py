"""p4c scheduled tasks —— 定时任务定义 + 执行日志（含多 worker 执行 claim 生成列唯一索引）

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_tasks",
        sa.Column("name", sa.String(length=128), nullable=False, comment="任务名称(唯一)"),
        sa.Column(
            "handler_key",
            sa.String(length=128),
            nullable=False,
            comment="处理器键(命中代码侧registry,非任意调用目标)",
        ),
        sa.Column(
            "params_json",
            sa.JSON(),
            nullable=False,
            comment="处理器参数(JSON)",
        ),
        sa.Column(
            "cron_expression",
            sa.String(length=128),
            nullable=False,
            comment="cron表达式(5字段标准crontab,经校验)",
        ),
        sa.Column(
            "cron_timezone",
            sa.String(length=64),
            server_default=sa.text("'Asia/Shanghai'"),
            nullable=False,
            comment="cron解释时区(库时间存UTC)",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'disabled'"),
            nullable=False,
            comment="状态(enabled/disabled)",
        ),
        sa.Column(
            "allow_concurrent",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
            comment="是否允许上次未跑完时并发执行",
        ),
        sa.Column(
            "misfire_grace_seconds",
            sa.Integer(),
            server_default=sa.text("300"),
            nullable=False,
            comment="错过触发的宽限秒数",
        ),
        sa.Column(
            "timeout_seconds", sa.Integer(), nullable=True, comment="单次执行超时秒数(空=不限)"
        ),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次执行时刻(UTC)",
        ),
        sa.Column(
            "last_status", sa.String(length=16), nullable=True, comment="最近一次执行结果状态"
        ),
        sa.Column("remark", sa.String(length=255), nullable=True, comment="备注"),
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="创建时间(UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="更新时间(UTC, ORM flush 触发)",
        ),
        sa.CheckConstraint("status IN ('enabled', 'disabled')", name="ck_scheduled_tasks_status"),
        sa.CheckConstraint(
            "allow_concurrent IN (0, 1)", name="ck_scheduled_tasks_allow_concurrent_bool"
        ),
        sa.CheckConstraint("misfire_grace_seconds >= 0", name="ck_scheduled_tasks_misfire_nonneg"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_scheduled_tasks_name"),
    )
    op.create_index(
        "ix_scheduled_tasks_handler_key", "scheduled_tasks", ["handler_key"], unique=False
    )
    op.create_index("ix_scheduled_tasks_status", "scheduled_tasks", ["status"], unique=False)
    op.create_table(
        "scheduled_task_logs",
        sa.Column(
            "task_id",
            sa.BigInteger(),
            nullable=True,
            comment="所属任务ID(任务删后置空,保留历史)",
        ),
        sa.Column("execution_id", sa.Uuid(), nullable=False, comment="执行唯一标识(UUID)"),
        sa.Column(
            "trigger_type",
            sa.String(length=16),
            nullable=False,
            comment="触发方式(schedule自动/manual手动)",
        ),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="计划触发时刻(UTC,自动触发用于claim去重)",
        ),
        sa.Column("handler_key", sa.String(length=128), nullable=False, comment="处理器键(快照)"),
        sa.Column(
            "params_json",
            sa.JSON(),
            nullable=False,
            comment="执行参数快照(JSON)",
        ),
        sa.Column(
            "schedule_claim_scheduled_at",
            sa.DateTime(timezone=True),
            sa.Computed(
                "CASE WHEN trigger_type = 'schedule' THEN scheduled_at ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
            comment="MySQL生成列: 自动触发claim计划时间, manual为NULL",
        ),
        sa.Column("status", sa.String(length=16), nullable=False, comment="执行状态"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=True, comment="开始执行时刻(UTC)"
        ),
        sa.Column(
            "finished_at", sa.DateTime(timezone=True), nullable=True, comment="结束时刻(UTC)"
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True, comment="执行耗时(毫秒)"),
        sa.Column("error_code", sa.String(length=128), nullable=True, comment="失败错误码"),
        sa.Column(
            "error_message",
            sa.String(length=1024),
            nullable=True,
            comment="失败信息(截断,禁写密钥)",
        ),
        sa.Column("result_summary", sa.String(length=1024), nullable=True, comment="成功结果摘要"),
        sa.Column("worker_id", sa.String(length=128), nullable=True, comment="执行所在worker标识"),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True, comment="手动触发操作者用户ID"),
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="创建时间(UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="更新时间(UTC, ORM flush 触发)",
        ),
        sa.CheckConstraint(
            "status IN ('waiting', 'running', 'success', 'failure', 'misfire', 'skipped')",
            name="ck_scheduled_task_logs_status",
        ),
        sa.CheckConstraint(
            "trigger_type IN ('schedule', 'manual')", name="ck_scheduled_task_logs_trigger"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["scheduled_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id"),
    )
    op.create_index(
        "ix_scheduled_task_logs_status_created",
        "scheduled_task_logs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_task_logs_task_started",
        "scheduled_task_logs",
        ["task_id", "started_at"],
        unique=False,
    )
    # 多 worker 执行 claim（P4 红线）：MySQL 生成列 + unique 实现条件唯一语义。
    op.create_index(
        "uq_scheduled_task_logs_schedule_claim",
        "scheduled_task_logs",
        ["task_id", "schedule_claim_scheduled_at"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_scheduled_task_logs_schedule_claim",
        table_name="scheduled_task_logs",
    )
    op.drop_index("ix_scheduled_task_logs_task_started", table_name="scheduled_task_logs")
    op.drop_index("ix_scheduled_task_logs_status_created", table_name="scheduled_task_logs")
    op.drop_table("scheduled_task_logs")
    op.drop_index("ix_scheduled_tasks_status", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_handler_key", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")
