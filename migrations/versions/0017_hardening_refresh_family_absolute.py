"""hardening-r1 refresh family_absolute_at 落列 + family_id 索引（H2 + M）

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # H2：family 绝对过期上限落列（签发时锚定、轮换透传），取代 rotate 时的 min(issued_at) 聚合——
    # 后者随 cleanup_expired_refresh_tokens 删 family 早期行而前移，使每 7 天刷新一次的会话永不
    # 过期。先 nullable 加列 → 回填存量 → 置 NOT NULL（存量无默认值，不能直接 NOT NULL 加列）。
    op.add_column(
        "auth_refresh_tokens",
        sa.Column(
            "family_absolute_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="family绝对过期上限(UTC,首登锚定,轮换透传不随清理漂移)",
        ),
    )
    # 回填：按 family 取首签 issued_at + 30d（与原 absolute 语义一致；30d = absolute_ttl 默认）。
    op.execute(
        """
        UPDATE auth_refresh_tokens AS t
        SET family_absolute_at = origin.min_issued + interval '30 days'
        FROM (
            SELECT family_id, min(issued_at) AS min_issued
            FROM auth_refresh_tokens
            GROUP BY family_id
        ) AS origin
        WHERE t.family_id = origin.family_id
        """
    )
    op.alter_column("auth_refresh_tokens", "family_absolute_at", nullable=False)
    # M：family_id 前导索引——revoke_family / get_online_session / 在线用户 family_id IN(子查询)
    # 全按纯 family_id 过滤，(user_id,family_id) 复合索引前导是 user_id 服务不了，原为全表扫。
    op.create_index(
        "ix_auth_refresh_tokens_family", "auth_refresh_tokens", ["family_id"], unique=False
    )
    # expires_at 列注释订正（model 同步）：它是 min(idle, family_absolute) 而非纯 absolute 上限。
    op.alter_column(
        "auth_refresh_tokens",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        comment="过期时间(UTC,min(idle,family_absolute))",
        existing_comment="过期时间(UTC,absolute上限)",
    )


def downgrade() -> None:
    op.alter_column(
        "auth_refresh_tokens",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        comment="过期时间(UTC,absolute上限)",
        existing_comment="过期时间(UTC,min(idle,family_absolute))",
    )
    op.drop_index("ix_auth_refresh_tokens_family", table_name="auth_refresh_tokens")
    op.drop_column("auth_refresh_tokens", "family_absolute_at")
