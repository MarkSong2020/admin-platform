"""one_super_admin generated-column unique index

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 至多一个超管：MySQL 生成列 + unique 利用「多个 NULL 不冲突」实现条件唯一语义。
    op.add_column(
        "users",
        sa.Column(
            "super_admin_unique_key",
            sa.Integer(),
            sa.Computed("CASE WHEN is_super_admin = 1 THEN 1 ELSE NULL END", persisted=True),
            nullable=True,
            comment="MySQL生成列: is_super_admin=true时为1,否则NULL",
        ),
    )
    op.create_index(
        "uq_users_one_super_admin",
        "users",
        ["super_admin_unique_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_one_super_admin", table_name="users")
    op.drop_column("users", "super_admin_unique_key")
