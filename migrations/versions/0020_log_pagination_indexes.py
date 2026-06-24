"""日志分页复合索引（PK 项3）—— audit_events / login_logs 的「status 过滤 + 时间倒序翻页」。

支撑 operlog/logininfor 的 ``WHERE status=? ORDER BY <time> DESC, id DESC`` 深翻页：MySQL 反向扫描
复合索引免 sort，避免 OFFSET 深分页在百万级 append-only 日志表上「扫描 + 丢弃前 N 行」。
additive 迁移（仅加索引，不改表 / 不动数据）。MySQL 在线 DDL 策略按目标版本与表量单独评估，
本迁移不使用 PostgreSQL 的 ``CONCURRENTLY`` / ``autocommit_block``。

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_events_status_time",
        "audit_events",
        ["result_status", "occurred_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_login_logs_status_time",
        "login_logs",
        ["status", "login_at_utc", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_login_logs_status_time", table_name="login_logs")
    op.drop_index("ix_audit_events_status_time", table_name="audit_events")
