"""创建 tags + todo_tags 多对多 — 第二个 example domain

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-18

新增：
  * ``tags`` 表（id / name UNIQUE / 时间戳）— 独立 Tag domain
  * ``todo_tags`` 关联表 — 复合 PK (todo_id, tag_id) + 两个 FK 都 ON DELETE
    CASCADE，删 todo 或 tag 自动清理其关联行

复合 PK 是 SA 推荐的「纯关联表」用法：自带去重、不需要管 surrogate id。
两个 FK 列上的索引在多数 Postgres 版本下会自动建，这里显式 declare 一份，
免去 query planner 等到 ANALYZE 才看到的延迟。
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
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
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
        sa.UniqueConstraint("name", name="uq_tags_name"),
    )

    op.create_table(
        "todo_tags",
        sa.Column(
            "todo_id",
            sa.Integer,
            sa.ForeignKey("todos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            sa.Integer,
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("todo_id", "tag_id", name="pk_todo_tags"),
    )
    # 显式声明 FK 索引 —— query planner 无须 ANALYZE 就能看到；对「按 tag
    # 反查 todos」或「selectinload 通过 Tag.id IN (...) 走 secondary」的
    # 路径有意义。
    op.create_index("ix_todo_tags_todo_id", "todo_tags", ["todo_id"])
    op.create_index("ix_todo_tags_tag_id", "todo_tags", ["tag_id"])


def downgrade() -> None:
    op.drop_index("ix_todo_tags_tag_id", table_name="todo_tags")
    op.drop_index("ix_todo_tags_todo_id", table_name="todo_tags")
    op.drop_table("todo_tags")
    op.drop_table("tags")
