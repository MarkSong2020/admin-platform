"""p3_configs

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # configs：运营参数键值（单租户无 tenant_id、无树）。config_key 全局唯一；config_value 存
    # 非敏感运营参数（禁存密钥）；is_builtin 标记内置参数（service 层禁删）。消费方读穿 DB（热更新）。
    op.create_table(
        "configs",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("name", sa.String(length=128), nullable=False, comment="参数名称"),
        sa.Column(
            "config_key", sa.String(length=128), nullable=False, comment="参数键名(全局唯一)"
        ),
        sa.Column("config_value", sa.Text(), nullable=False, comment="参数键值(非敏感运营参数)"),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, comment="是否系统内置(内置禁删)"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("is_builtin IN (0, 1)", name="ck_configs_is_builtin_bool"),
        sa.UniqueConstraint("config_key", name="uq_configs_key"),
    )


def downgrade() -> None:
    op.drop_table("configs")
