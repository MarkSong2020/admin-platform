"""hardening-r1 refresh family_absolute_at 落列 + family_id 索引（H2 + M）

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

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
    # 回填 family_absolute_at = 首签 issued_at + absolute_ttl（PK 项2 收敛：保守不延长 / 不读运行时
    # config——迁移须自包含、且当前运行时 TTL 不等于历史 TTL）。absolute_ttl 默认 30 天（= 配置
    # auth_refresh_absolute_ttl_seconds 默认 2592000）。**若部署曾把该配置改成非 30 天**，生产首跑前
    # 必须显式传历史值精确回填，否则旧 family 上限被错填：
    #   alembic -x refresh_absolute_ttl_seconds=<历史秒数> upgrade 0017
    # 刻意不用现有 expires_at 兜底——它是 idle 滑动过期值（≈最近轮换+7d）、非 absolute 上限，cap 到它
    # 会把活跃 family 的绝对窗口误砍到下个 idle 周期、造成大面积非预期重登。
    x_args = context.get_x_argument(as_dictionary=True)
    ttl_seconds = int(x_args.get("refresh_absolute_ttl_seconds", "2592000"))
    op.execute(
        sa.text(
            """
            UPDATE auth_refresh_tokens AS t
            SET family_absolute_at = origin.min_issued + make_interval(secs => :ttl)
            FROM (
                SELECT family_id, min(issued_at) AS min_issued
                FROM auth_refresh_tokens
                GROUP BY family_id
            ) AS origin
            WHERE t.family_id = origin.family_id
            """
        ).bindparams(ttl=ttl_seconds)
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
