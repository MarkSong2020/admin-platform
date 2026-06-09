"""p3_dicts

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # dict_types：字典类型（type 全局唯一，is_builtin 内置禁删）。
    op.create_table(
        "dict_types",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="字典名称"),
        sa.Column(
            "type",
            sa.String(length=128),
            nullable=False,
            comment="字典类型(全局唯一标识，如 sys_user_sex)",
        ),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态(active/disabled)"),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, comment="是否系统内置(内置禁删)"),
        sa.Column("remark", sa.String(length=255), nullable=True, comment="备注"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间(UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="更新时间(UTC, ORM flush 触发)",
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_dict_types_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("type", name="uq_dict_types_type"),
    )
    # dict_data：字典数据（FK→dict_types.id RESTRICT，删有数据的类型由 service 拦；同类型 value 唯一）。
    op.create_table(
        "dict_data",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column(
            "dict_type_id",
            sa.BigInteger(),
            nullable=False,
            comment="字典类型ID(关联 dict_types.id)",
        ),
        sa.Column("label", sa.String(length=128), nullable=False, comment="字典标签(显示文本)"),
        sa.Column("value", sa.String(length=128), nullable=False, comment="字典键值"),
        sa.Column("sort_order", sa.Integer(), nullable=False, comment="显示顺序"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态(active/disabled)"),
        sa.Column("is_default", sa.Boolean(), nullable=False, comment="是否默认(同类型仅一条)"),
        sa.Column("css_class", sa.String(length=128), nullable=True, comment="前端样式(CSS class)"),
        sa.Column("remark", sa.String(length=255), nullable=True, comment="备注"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间(UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="更新时间(UTC, ORM flush 触发)",
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_dict_data_status"),
        sa.ForeignKeyConstraint(
            ["dict_type_id"], ["dict_types.id"], ondelete="RESTRICT", name="fk_dict_data_type_id"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dict_type_id", "value", name="uq_dict_data_type_value"),
    )
    # 单默认值不变式（DB 兜底，对抗审查 B1）：同类型至多一行 is_default=true（partial unique index，
    # 镜像 0003 单超管约束）。
    op.create_index(
        "uq_dict_data_one_default_per_type",
        "dict_data",
        ["dict_type_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_index(
        "ix_dict_data_type_sort",
        "dict_data",
        ["dict_type_id", "sort_order", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dict_data_type_sort", table_name="dict_data")
    op.drop_index("uq_dict_data_one_default_per_type", table_name="dict_data")
    op.drop_table("dict_data")
    op.drop_table("dict_types")
