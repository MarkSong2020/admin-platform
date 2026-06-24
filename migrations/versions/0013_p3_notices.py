"""p3_notices

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # notices：运营公告（单租户无 tenant_id、无树、无唯一键——标题可重复）。
    # notice_type / status 带 ck 枚举约束；content 存富文本（渲染期净化是前端职责）。
    op.create_table(
        "notices",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("title", sa.String(length=128), nullable=False, comment="公告标题"),
        sa.Column(
            "notice_type",
            sa.String(length=16),
            nullable=False,
            comment="公告类型(notification/announcement)",
        ),
        sa.Column("content", sa.Text(), nullable=False, comment="公告内容(富文本，渲染期需净化)"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态(active/disabled)"),
        sa.Column("remark", sa.String(length=255), nullable=True, comment="备注"),
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
            "notice_type IN ('notification', 'announcement')", name="ck_notices_type"
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_notices_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notices_type_status", "notices", ["notice_type", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notices_type_status", table_name="notices")
    op.drop_table("notices")
