"""Dept ORM 映射 — 表 ``depts``（部门树，邻接表存储）。

部门树用 ``parent_id`` 自引用邻接表（O1 拍板：几百部门、深度 <10，闭包表 / 路径枚举
属过度工程）。查子孙 / 祖先用 PostgreSQL recursive CTE（见 ``repository.py``），只在展开
``visible_dept_ids`` 等少数路径触发。``code`` 全局唯一（业务编码，前端 / 数据权限引用）。
``parent_id`` 外键 ``ondelete=RESTRICT``：DB 层硬保证有子部门时禁删父部门；service 层另做
友好的 409 预检（``dept.HAS_CHILDREN``），避免裸 IntegrityError 退化成无意义的 conflict。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from admin_platform.core.errors import register_unique_constraint
from admin_platform.db.base import Base, IdMixin, TimestampMixin


class Dept(Base, IdMixin, TimestampMixin):
    __tablename__ = "depts"

    __table_args__ = (
        UniqueConstraint("code", name="uq_depts_code"),
        # 防自环：parent_id 不能指向自身（移动成环的更深检测在 service 层用子孙集合做）。
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_depts_not_self_parent"),
        # status 枚举约束：只允许 active / disabled（与 schemas Literal 对齐，防脏数据）。
        CheckConstraint("status IN ('active', 'disabled')", name="ck_depts_status"),
        # 按父节点取子节点并排序的复合索引（建树 / 同级排序的主查询路径）。
        Index("ix_depts_parent_sort", "parent_id", "sort_order", "id"),
    )

    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("depts.id", ondelete="RESTRICT"),
        nullable=True,
        comment="父部门ID(NULL=根)",
    )
    name: Mapped[str] = mapped_column(String(64), comment="部门名称")
    code: Mapped[str] = mapped_column(String(64), comment="部门编码")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="显示顺序")
    status: Mapped[str] = mapped_column(
        String(16), default="active", comment="状态(active/disabled)"
    )
    leader: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="负责人")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="联系电话")
    email: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="邮箱")


# DB 唯一约束 → 业务错误码：并发预检都通过时第二个 INSERT 撞 uq_depts_code →
# IntegrityError handler 据此把 500 翻成 409（与 service 的 dept.CODE_DUPLICATE 同码）。
register_unique_constraint(
    "uq_depts_code",
    "dept.CODE_DUPLICATE",
    "Dept code already exists",
)
