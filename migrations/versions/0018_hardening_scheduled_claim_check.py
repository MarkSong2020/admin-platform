"""hardening-r1 schedule claim CHECK：schedule 触发必须有 scheduled_at（L）

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # L：claim 正确性层兜底——生成列唯一索引只约束 trigger_type='schedule' 的 scheduled_at
    # 在 PG16 NULLS DISTINCT 下对 schedule+NULL 行完全失效（去重被静默旁路）。此 CHECK 让任何
    # schedule+NULL 插入直接失败，堵死未来代码/手写 SQL/回放工具绕过红线。manual 仍可 NULL。
    op.create_check_constraint(
        "ck_scheduled_task_logs_schedule_at",
        "scheduled_task_logs",
        "trigger_type <> 'schedule' OR scheduled_at IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_scheduled_task_logs_schedule_at", "scheduled_task_logs", type_="check")
