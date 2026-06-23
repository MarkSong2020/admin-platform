"""p1_roles

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # roles：全局角色（单租户无 tenant_id）。code 全局唯一；data_scope / status 各带 ck 枚举约束。
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="角色名称"),
        sa.Column("code", sa.String(length=64), nullable=False, comment="角色编码"),
        sa.Column(
            "data_scope",
            sa.String(length=32),
            nullable=False,
            comment="数据权限范围(ScopeType值)",
        ),
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
        sa.CheckConstraint(
            "data_scope IN ('all', 'custom_dept', 'self_dept', 'self_dept_and_below', 'self')",
            name="ck_roles_data_scope",
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_roles_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )
    # user_roles：用户 ↔ 角色多对多。FK ondelete=CASCADE（用户/角色删除清理绑定）；uq 防重复。
    op.create_table(
        "user_roles",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户ID"),
        sa.Column("role_id", sa.BigInteger(), nullable=False, comment="角色ID"),
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
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles"),
    )
    op.create_index("ix_user_roles_role", "user_roles", ["role_id"], unique=False)
    op.create_index("ix_user_roles_user", "user_roles", ["user_id"], unique=False)
    # role_depts：角色 ↔ 部门（CUSTOM_DEPT 自定义数据范围）。FK ondelete=CASCADE；uq 防重复。
    op.create_table(
        "role_depts",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("role_id", sa.BigInteger(), nullable=False, comment="角色ID"),
        sa.Column("dept_id", sa.BigInteger(), nullable=False, comment="部门ID"),
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
        sa.ForeignKeyConstraint(["dept_id"], ["depts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "dept_id", name="uq_role_depts"),
    )
    op.create_index("ix_role_depts_dept", "role_depts", ["dept_id"], unique=False)
    op.create_index("ix_role_depts_role", "role_depts", ["role_id"], unique=False)
    # users.dept_id：所属部门（RBAC「本部门」载体）。FK ondelete=SET NULL（部门删除落为无部门）。
    op.add_column(
        "users",
        sa.Column("dept_id", sa.BigInteger(), nullable=True, comment="所属部门ID"),
    )
    op.create_foreign_key(
        "fk_users_dept", "users", "depts", ["dept_id"], ["id"], ondelete="SET NULL"
    )
    # dept_id 索引（Codex 深审）：部门删除 SET NULL 定位用户行 + data_scope 本部门按 dept_id 查。
    op.create_index("ix_users_dept_id", "users", ["dept_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_dept_id", table_name="users")
    op.drop_constraint("fk_users_dept", "users", type_="foreignkey")
    op.drop_column("users", "dept_id")
    op.drop_index("ix_role_depts_role", table_name="role_depts")
    op.drop_index("ix_role_depts_dept", table_name="role_depts")
    op.drop_table("role_depts")
    op.drop_index("ix_user_roles_user", table_name="user_roles")
    op.drop_index("ix_user_roles_role", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_table("roles")
