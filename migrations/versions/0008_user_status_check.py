"""user_status_check

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # users.status 枚举约束（Codex 系统级 PK）：与 dept/role/menu/post 同源 active/disabled，
    # 防脏状态（如拼错大小写）被 provider/login 当作隐式停用。既有行默认均为 active，加约束安全。
    op.create_check_constraint("ck_users_status", "users", "status IN ('active', 'disabled')")


def downgrade() -> None:
    op.drop_constraint("ck_users_status", "users", type_="check")
