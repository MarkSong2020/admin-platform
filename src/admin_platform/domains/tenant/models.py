"""Tenant ORM 映射 — 表 ``tenants``。

平台级表（**不**继承 ``TenantMixin``）：跨所有租户存在、由平台超管管理，自身
不参与租户隔离过滤（见 ADR-B）。租户隔离机制只作用于带 ``TenantMixin`` 的业务表，
``tenants`` 是那条边界的另一侧。

``code`` 是租户的业务自然键（全局唯一）；哨兵租户 ``code="PLATFORM"`` 承载平台
超管（``User.is_platform_admin=True``），由 Task 9 的 CLI 一次性创建，不在 lifespan
自动 seed。
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.db.base import Base, IdMixin, TimestampMixin


class Tenant(Base, IdMixin, TimestampMixin):
    __tablename__ = "tenants"

    code: Mapped[str] = mapped_column(String(64), unique=True, comment="租户编码(业务自然键)")
    name: Mapped[str] = mapped_column(String(128), comment="租户名称")
    status: Mapped[str] = mapped_column(String(16), default="active", comment="状态")
