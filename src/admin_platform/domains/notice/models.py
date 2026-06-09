"""Notice ORM 映射 —— 表 ``notices``（运营公告，对标 RuoYi ``sys_notice``）。

扁平域（单租户无 tenant_id、无树、无唯一键——标题可重复）：``notice_type`` 区分通知 /
公告，``content`` 存富文本（**后端存 raw，渲染期净化是 P6 前端职责**，spec §2.4 / XSS 风险）。
``notice_type`` / ``status`` 用 CheckConstraint 兜底（与 schemas ``Literal`` 同源）。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.db.base import Base, IdMixin, TimestampMixin


class Notice(Base, IdMixin, TimestampMixin):
    __tablename__ = "notices"

    __table_args__ = (
        CheckConstraint("notice_type IN ('notification', 'announcement')", name="ck_notices_type"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_notices_status"),
        # 列表常按类型 + 状态过滤（如「启用的公告」）。
        Index("ix_notices_type_status", "notice_type", "status"),
    )

    title: Mapped[str] = mapped_column(String(128), comment="公告标题")
    notice_type: Mapped[str] = mapped_column(
        String(16), comment="公告类型(notification/announcement)"
    )
    content: Mapped[str] = mapped_column(Text, comment="公告内容(富文本，渲染期需净化)")
    status: Mapped[str] = mapped_column(
        String(16), default="active", comment="状态(active/disabled)"
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")
