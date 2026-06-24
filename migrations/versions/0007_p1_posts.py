"""p1_posts

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # posts：全局岗位（单租户无 tenant_id，扁平无树）。code 全局唯一；status 带 ck 枚举约束。
    op.create_table(
        "posts",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="岗位名称"),
        sa.Column("code", sa.String(length=64), nullable=False, comment="岗位编码"),
        sa.Column("sort_order", sa.Integer(), nullable=False, comment="显示顺序"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态(active/disabled)"),
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
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_posts_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_posts_code"),
    )
    # user_posts：用户 ↔ 岗位多对多。FK ondelete=CASCADE（用户/岗位删除清理绑定）；uq 防重复。
    op.create_table(
        "user_posts",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("post_id", sa.BigInteger(), nullable=False, comment="岗位ID"),
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
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "post_id", name="uq_user_posts"),
    )
    op.create_index("ix_user_posts_post", "user_posts", ["post_id"], unique=False)
    op.create_index("ix_user_posts_user", "user_posts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_posts_user", table_name="user_posts")
    op.drop_index("ix_user_posts_post", table_name="user_posts")
    op.drop_table("user_posts")
    op.drop_table("posts")
