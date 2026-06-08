"""p1_4_refresh_tokens

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # auth_refresh_tokens（P1.4）：opaque refresh token 服务端状态（轮换链 + 撤销 + 过期）。
    # 只存 token_hash（HMAC，不存明文）；jti/token_hash 唯一；FK ondelete=CASCADE（删用户清 token）。
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column("jti", sa.Uuid(), nullable=False, comment="当前token标识(UUID)"),
        sa.Column(
            "family_id", sa.Uuid(), nullable=False, comment="轮换链family(一次登录=一family)"
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="所属用户ID"),
        sa.Column(
            "token_hash",
            sa.String(length=64),
            nullable=False,
            comment="HMAC-SHA256(pepper,secret)的hex(不存明文)",
        ),
        sa.Column(
            "rotated_to_jti",
            sa.Uuid(),
            nullable=True,
            comment="轮换后继jti(非空=已被轮换,再用即reuse)",
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="撤销时间(非空=已撤销)",
        ),
        sa.Column(
            "revoked_reason",
            sa.String(length=32),
            nullable=True,
            comment="撤销原因(rotated/logout/reuse_detected/concurrency_limit/expired_cleanup)",
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, comment="签发时间(UTC)"),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="过期时间(UTC,absolute上限)",
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最后轮换时间(UTC)",
        ),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_auth_refresh_tokens_expires_at", "auth_refresh_tokens", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_auth_refresh_tokens_user_active",
        "auth_refresh_tokens",
        ["user_id", "revoked_at", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_refresh_tokens_user_family",
        "auth_refresh_tokens",
        ["user_id", "family_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_refresh_tokens_user_family", table_name="auth_refresh_tokens")
    op.drop_index("ix_auth_refresh_tokens_user_active", table_name="auth_refresh_tokens")
    op.drop_index("ix_auth_refresh_tokens_expires_at", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")
