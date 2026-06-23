"""File ORM 映射 — 表 ``files``（对标 RuoYi sys_oss，文件元数据 + 软删）。

物理内容由 ``StorageBackend`` 按 ``object_key`` 存取；本表只存元数据 + 软删标记。
删除 = ``status='deleted'`` + ``deleted_at`` + 物理删文件（释放空间）；元数据保留供审计追溯。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class File(Base, IdMixin, TimestampMixin):
    __tablename__ = "files"

    __table_args__ = (
        UniqueConstraint("object_key", name="uq_files_object_key"),
        Index("ix_files_sha256", "sha256"),
        Index("ix_files_uploader_id", "uploader_id"),
        Index("ix_files_status_created", "status", "created_at"),
    )

    # 业务列必带中文 comment（机检门禁 tests/unit/test_column_comments.py）；
    # id/created_at/updated_at 由 IdMixin/TimestampMixin 提供。
    object_key: Mapped[str] = mapped_column(
        String(64), comment="存储对象键(uuid4 hex，不含原文件名，防穿越/覆盖)"
    )
    storage_backend: Mapped[str] = mapped_column(String(32), comment="存储后端(local/s3)")
    original_filename: Mapped[str] = mapped_column(
        String(255), comment="原始文件名(仅展示/下载用，不信任)"
    )
    content_type: Mapped[str] = mapped_column(String(128), comment="声明MIME类型(校验后落库)")
    size_bytes: Mapped[int] = mapped_column(BigInteger, comment="文件字节数(实际写入量)")
    sha256: Mapped[str] = mapped_column(String(64), comment="内容SHA256(完整性校验)")
    uploader_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_files_uploader_id"),
        comment="上传者用户ID",
    )
    status: Mapped[str] = mapped_column(
        String(16), default="active", comment="状态(active/deleted)"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True, comment="软删时间(NULL=未删)"
    )
