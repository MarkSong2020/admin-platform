"""p1_depts

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 部门树（邻接表，O1）：parent_id 自引用 FK ondelete=RESTRICT（DB 层硬保证有子禁删）；
    # code 全局唯一；复合索引覆盖「按父取子并排序」主查询路径。
    op.create_table(
        "depts",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("parent_id", sa.BigInteger(), nullable=True, comment="父部门ID(NULL=根)"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="部门名称"),
        sa.Column("code", sa.String(length=64), nullable=False, comment="部门编码"),
        sa.Column("sort_order", sa.Integer(), nullable=False, comment="显示顺序"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态(active/disabled)"),
        sa.Column("leader", sa.String(length=64), nullable=True, comment="负责人"),
        sa.Column("phone", sa.String(length=32), nullable=True, comment="联系电话"),
        sa.Column("email", sa.String(length=128), nullable=True, comment="邮箱"),
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
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_depts_status"),
        sa.ForeignKeyConstraint(["parent_id"], ["depts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_depts_code"),
    )
    # MySQL 8 不允许 CHECK 引用 auto-increment 列，self-parent 防护改用 trigger。
    op.execute(
        sa.text(
            """
            CREATE TRIGGER ck_depts_not_self_parent_bi
            BEFORE INSERT ON depts
            FOR EACH ROW
            BEGIN
                IF NEW.parent_id IS NOT NULL AND NEW.parent_id = NEW.id THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ck_depts_not_self_parent';
                END IF;
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER ck_depts_not_self_parent_bu
            BEFORE UPDATE ON depts
            FOR EACH ROW
            BEGIN
                IF NEW.parent_id IS NOT NULL AND NEW.parent_id = NEW.id THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ck_depts_not_self_parent';
                END IF;
            END
            """
        )
    )
    op.create_index(
        "ix_depts_parent_sort", "depts", ["parent_id", "sort_order", "id"], unique=False
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS ck_depts_not_self_parent_bu"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS ck_depts_not_self_parent_bi"))
    op.drop_index("ix_depts_parent_sort", table_name="depts")
    op.drop_table("depts")
