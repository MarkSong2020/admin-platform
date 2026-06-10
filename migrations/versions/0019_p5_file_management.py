"""P5 文件管理：files 表（对标 RuoYi sys_oss，元数据 + 软删）

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="主键"),
        sa.Column(
            "object_key",
            sa.String(length=64),
            nullable=False,
            comment="存储对象键(uuid4 hex，不含原文件名，防穿越/覆盖)",
        ),
        sa.Column(
            "storage_backend", sa.String(length=32), nullable=False, comment="存储后端(local/s3)"
        ),
        sa.Column(
            "original_filename",
            sa.String(length=255),
            nullable=False,
            comment="原始文件名(仅展示/下载用，不信任)",
        ),
        sa.Column(
            "content_type",
            sa.String(length=128),
            nullable=False,
            comment="声明MIME类型(校验后落库)",
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, comment="文件字节数(实际写入量)"),
        sa.Column("sha256", sa.String(length=64), nullable=False, comment="内容SHA256(完整性校验)"),
        sa.Column("uploader_id", sa.BigInteger(), nullable=False, comment="上传者用户ID"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态(active/deleted)"),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="软删时间(NULL=未删)",
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
        sa.ForeignKeyConstraint(
            ["uploader_id"], ["users.id"], name="fk_files_uploader_id", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_files_object_key"),
    )
    op.create_index("ix_files_sha256", "files", ["sha256"], unique=False)
    op.create_index("ix_files_uploader_id", "files", ["uploader_id"], unique=False)
    op.create_index("ix_files_status_created", "files", ["status", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_files_status_created", table_name="files")
    op.drop_index("ix_files_uploader_id", table_name="files")
    op.drop_index("ix_files_sha256", table_name="files")
    op.drop_table("files")
