"""menu_seed_key

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # menus.seed_key（§13.1）：版本化 seed manifest 的稳定键。非空 = rbac seed 内置菜单
    # （幂等 upsert 锚点 + 系统管理标记）；NULL = 用户自建菜单（seed 不碰）。partial unique
    # 仅约束非空值，保证内置菜单 seed_key 唯一。
    op.add_column(
        "menus",
        sa.Column(
            "seed_key",
            sa.String(length=128),
            nullable=True,
            comment="seed稳定键(非空=内置菜单,NULL=用户自建)",
        ),
    )
    op.create_index(
        "uq_menus_seed_key",
        "menus",
        ["seed_key"],
        unique=True,
        postgresql_where=sa.text("seed_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_menus_seed_key", table_name="menus")
    op.drop_column("menus", "seed_key")
