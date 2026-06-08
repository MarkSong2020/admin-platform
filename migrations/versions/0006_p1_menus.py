"""p1_menus

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # menus：菜单树（邻接表 parent_id 自引用，ondelete=RESTRICT 有子禁删）。三类 M/C/F。
    op.create_table(
        "menus",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("parent_id", sa.BigInteger(), nullable=True, comment="父菜单ID(NULL=根)"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="菜单名称"),
        sa.Column(
            "menu_type", sa.String(length=8), nullable=False, comment="类型(M目录/C菜单/F按钮)"
        ),
        sa.Column("path", sa.String(length=255), nullable=False, comment="路由地址(按钮类可空串)"),
        sa.Column(
            "component", sa.String(length=255), nullable=True, comment="前端组件路径(目录/按钮可空)"
        ),
        sa.Column(
            "perms",
            sa.String(length=128),
            nullable=True,
            comment="权限标识(如system:user:list,目录类可空)",
        ),
        sa.Column("icon", sa.String(length=64), nullable=False, comment="菜单图标"),
        sa.Column("sort_order", sa.Integer(), nullable=False, comment="显示顺序"),
        sa.Column("visible", sa.Boolean(), nullable=False, comment="是否显示(False=侧边栏隐藏)"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态(active/disabled)"),
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
        sa.CheckConstraint("menu_type IN ('M', 'C', 'F')", name="ck_menus_menu_type"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_menus_status"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_menus_not_self_parent"),
        sa.ForeignKeyConstraint(["parent_id"], ["menus.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_menus_parent_sort", "menus", ["parent_id", "sort_order", "id"], unique=False
    )
    # role_menus：角色 ↔ 菜单多对多。FK ondelete=CASCADE；uq 防重复；两列各加索引。
    op.create_table(
        "role_menus",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("role_id", sa.BigInteger(), nullable=False, comment="角色ID"),
        sa.Column("menu_id", sa.BigInteger(), nullable=False, comment="菜单ID"),
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
        sa.ForeignKeyConstraint(["menu_id"], ["menus.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "menu_id", name="uq_role_menus"),
    )
    op.create_index("ix_role_menus_menu", "role_menus", ["menu_id"], unique=False)
    op.create_index("ix_role_menus_role", "role_menus", ["role_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_role_menus_role", table_name="role_menus")
    op.drop_index("ix_role_menus_menu", table_name="role_menus")
    op.drop_table("role_menus")
    op.drop_index("ix_menus_parent_sort", table_name="menus")
    op.drop_table("menus")
