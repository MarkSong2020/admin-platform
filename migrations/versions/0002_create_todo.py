"""创建 todos 表 — 教科书蓝本 example domain

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-18

手写 migration（不是 autogenerate），让模板的 CI build 时不依赖活的
Postgres 就能 ship 一个可跑的 migration。业务侧后续 migration 一般用
``alembic revision --autogenerate`` 生成。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TODO_STATUS_VALUES = ("OPEN", "IN_PROGRESS", "DONE")


def upgrade() -> None:
    # SQLAlchemy 的 Postgres dialect 在 CREATE TABLE 引用 Enum 列时会自动先
    # emit ``CREATE TYPE todo_status AS ENUM (...)``。**不要**再额外写
    # ``.create()`` 调用 —— 即使加 ``checkfirst=True``，在 async dialect +
    # transactional DDL 下 checkfirst 会被旁路，首次空库 migration 就会
    # DuplicateObjectError。
    op.create_table(
        "todos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_TODO_STATUS_VALUES, name="todo_status"),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "gmt_create",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "gmt_modified",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("title", name="uq_todos_title"),
    )
    op.create_index("ix_todos_status", "todos", ["status"])


def downgrade() -> None:
    op.drop_index("ix_todos_status", table_name="todos")
    op.drop_table("todos")
    sa.Enum(name="todo_status").drop(op.get_bind(), checkfirst=True)
