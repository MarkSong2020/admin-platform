"""one_super_admin partial unique index

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
    # 至多一个超管：partial unique index 让 is_super_admin=true 的行唯一（P0.9 信任根约束）。
    op.create_index(
        "uq_users_one_super_admin",
        "users",
        ["is_super_admin"],
        unique=True,
        postgresql_where=sa.text("is_super_admin"),
    )


def downgrade() -> None:
    op.drop_index("uq_users_one_super_admin", table_name="users")
