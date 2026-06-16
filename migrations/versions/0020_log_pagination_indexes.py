"""日志分页复合索引（PK 项3）—— audit_events / login_logs 的「status 过滤 + 时间倒序翻页」。

支撑 operlog/logininfor 的 ``WHERE status=? ORDER BY <time> DESC, id DESC`` 深翻页：PG 反向扫描
复合索引免 sort，避免 OFFSET 深分页在百万级 append-only 日志表上「扫描 + 丢弃前 N 行」。
additive 迁移（仅加索引，不改表 / 不动数据）。为避免在大表上持 SHARE 锁阻塞日志写入，
建/删索引均走 ``CREATE/DROP INDEX CONCURRENTLY``（autocommit_block 跳出迁移链事务）。
生产执行与中断恢复（INVALID 索引）步骤见 docs/operations/RUNBOOK.md「迁移 0017 / 0020」。

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
    # CREATE INDEX CONCURRENTLY 不能在事务块内执行，而 env.py 用 begin_transaction() 把整条
    # 迁移链包成单个事务（transaction_per_migration 未开）。autocommit_block 临时提交外层事务、
    # 把连接切到 autocommit 跑并发建索引、结束后恢复事务——从而在百万级 append-only 日志热表上
    # 免 SHARE 锁，不阻塞 audit_events / login_logs 的写入（审计与登录日志落库）。
    # 注：CONCURRENTLY 中断会留 INVALID 索引，恢复步骤见 RUNBOOK.md「迁移 0017 / 0020」。
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_audit_events_status_time",
            "audit_events",
            ["result_status", "occurred_at", "id"],
            unique=False,
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_login_logs_status_time",
            "login_logs",
            ["status", "login_at_utc", "id"],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    # 对称回滚：DROP INDEX CONCURRENTLY 同样不能在事务内，且免 ACCESS EXCLUSIVE 锁。
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_login_logs_status_time",
            table_name="login_logs",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_audit_events_status_time",
            table_name="audit_events",
            postgresql_concurrently=True,
        )
