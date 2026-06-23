"""users

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("username", sa.String(length=64), nullable=False, comment="用户名"),
        sa.Column("password_hash", sa.String(length=255), nullable=False, comment="密码哈希"),
        sa.Column("nickname", sa.String(length=64), nullable=False, comment="昵称"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态"),
        sa.Column("is_super_admin", sa.Boolean(), nullable=False, comment="是否超级管理员"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("is_super_admin IN (0, 1)", name="ck_users_is_super_admin_bool"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )


def downgrade() -> None:
    op.drop_table("users")
